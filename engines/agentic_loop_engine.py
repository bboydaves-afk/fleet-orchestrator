"""Agentic Loop Engine — Autonomous Claude tool-use loop for the fleet.

Runs Claude in a genuine agentic loop: reason → act → observe → repeat,
until the goal is achieved or limits are hit. No human in the loop.

Designed for:
- Headless autonomous execution (scheduled jobs, webhooks, n8n triggers)
- Background task processing via REST API
- Multi-step fleet operations without human intervention
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

import anthropic

from core.models import ToolExecResult

logger = logging.getLogger("fleet.agentic_loop")


# ------------------------------------------------------------------
# Session state
# ------------------------------------------------------------------

class SessionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    MAX_ITERATIONS = "max_iterations"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class AgenticSession:
    """Tracks the state of a single agentic loop run."""

    def __init__(
        self,
        session_id: str,
        goal: str,
        max_iterations: int = 25,
        timeout_seconds: int = 600,
        model: str = "claude-sonnet-4-5-20250929",
        callback_url: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        self.session_id = session_id
        self.goal = goal
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.callback_url = callback_url
        self.metadata = metadata or {}

        self.status = SessionStatus.RUNNING
        self.iterations = 0
        self.tool_calls: list[dict] = []
        self.final_answer: Optional[str] = None
        self.error: Optional[str] = None
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.completed_at: Optional[str] = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "goal": self.goal,
            "status": self.status.value,
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "tool_calls": self.tool_calls,
            "final_answer": self.final_answer,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "model": self.model,
            "callback_url": self.callback_url,
            "metadata": self.metadata,
        }


# ------------------------------------------------------------------
# Agentic Loop Engine
# ------------------------------------------------------------------

class AgenticLoopEngine:
    """Runs Claude in an autonomous tool-use loop against the fleet.

    The engine:
    1. Builds a tool palette from the fleet orchestrator's handler tools
    2. Sends the goal to Claude with the tool palette
    3. Loops: Claude reasons → calls tools → engine executes → feeds results back
    4. Terminates when Claude gives a final answer, or limits are hit
    5. Logs everything to DB and optionally fires a callback webhook
    """

    def __init__(
        self,
        fleet_engine,
        health_engine,
        orchestration_engine,
        workflow_engine,
        briefing_engine,
        alert_engine,
        escalation_mgr,
        policy_engine,
        fleet_monitor,
        scheduler_engine,
        db,
        config: dict,
    ):
        self._fleet = fleet_engine
        self._health = health_engine
        self._orchestration = orchestration_engine
        self._workflow = workflow_engine
        self._briefing = briefing_engine
        self._alert = alert_engine
        self._escalation = escalation_mgr
        self._policy = policy_engine
        self._fleet_monitor = fleet_monitor
        self._scheduler = scheduler_engine
        self._db = db
        self._config = config

        self._client = anthropic.Anthropic()
        self._sessions: dict[str, AgenticSession] = {}
        self._cancelled: set[str] = set()

        # Concurrency limiter — max simultaneous agentic sessions
        max_concurrent = config.get("agentic_loop", {}).get("max_concurrent_sessions", 3)
        self._semaphore = asyncio.Semaphore(max_concurrent)

        # Build handler context (same as chat agent uses)
        self._ctx = {
            "fleet_engine": fleet_engine,
            "health_engine": health_engine,
            "orchestration_engine": orchestration_engine,
            "workflow_engine": workflow_engine,
            "briefing_engine": briefing_engine,
            "alert_engine": alert_engine,
            "escalation_mgr": escalation_mgr,
            "policy_engine": policy_engine,
            "fleet_monitor": fleet_monitor,
            "scheduler_engine": scheduler_engine,
        }

    # ------------------------------------------------------------------
    # Tool palette — reuse the existing handler infrastructure
    # ------------------------------------------------------------------

    def _build_tools(self) -> tuple[list[dict], dict]:
        """Build Claude tool definitions and handler map.

        Returns (tools_for_claude, handler_map).
        """
        from interfaces.ai_agent.tools import TOOLS
        from interfaces.ai_agent.handlers import TOOL_HANDLERS

        tools_for_claude = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
            for t in TOOLS
        ]

        # Add a special "complete_task" tool so Claude can signal completion
        tools_for_claude.append({
            "name": "complete_task",
            "description": (
                "Call this tool when you have fully accomplished the goal. "
                "Provide a summary of what was done and the results."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary of what was accomplished",
                    },
                    "results": {
                        "type": "object",
                        "description": "Structured results data (optional)",
                    },
                },
                "required": ["summary"],
            },
        })

        return tools_for_claude, TOOL_HANDLERS

    async def _load_knowledge_context(self, goal: str) -> str:
        """Load org knowledge and relevant learned patterns for the system prompt."""
        if not self._db:
            return ""

        sections = []

        # 1. Org knowledge facts
        try:
            facts = await self._db.get_all_org_knowledge()
            if facts:
                lines = [f"- {f['key']}: {f['value']}" for f in facts]
                sections.append(
                    "## Organization Knowledge\n" + "\n".join(lines)
                )
        except Exception as exc:
            logger.debug("Failed to load org knowledge: %s", exc)

        # 2. Learned patterns matching this goal
        try:
            patterns = await self._db.search_learned_patterns(goal, limit=5)
            if patterns:
                pat_lines = []
                for p in patterns:
                    pat_lines.append(
                        f"- [{p['pattern_type']}] {p['successful_approach']} "
                        f"(used {p['times_used']}x)"
                    )
                sections.append(
                    "## Learned Patterns (from past successful sessions)\n"
                    + "\n".join(pat_lines)
                )
        except Exception as exc:
            logger.debug("Failed to load learned patterns: %s", exc)

        # 3. Recent successful sessions with similar goals
        try:
            recent = await self._db.get_agentic_sessions(status="completed", limit=10)
            # Simple keyword overlap scoring
            goal_words = {w.lower() for w in goal.split() if len(w) > 3}
            scored = []
            for s in recent:
                s_words = {w.lower() for w in s.get("goal", "").split() if len(w) > 3}
                overlap = len(goal_words & s_words)
                if overlap >= 2:
                    scored.append((overlap, s))
            scored.sort(key=lambda x: x[0], reverse=True)

            if scored:
                example_lines = []
                for _, s in scored[:3]:
                    tool_chain = json.loads(s.get("tool_calls", "[]"))
                    tools_used = [t.get("tool", "?") for t in tool_chain
                                  if t.get("tool") != "complete_task"]
                    summary = (s.get("final_answer") or "")[:200]
                    example_lines.append(
                        f"- Goal: \"{s['goal'][:120]}...\"\n"
                        f"  Tools: {' -> '.join(tools_used[:8])}\n"
                        f"  Result: {summary}"
                    )
                sections.append(
                    "## Recent Similar Sessions (for reference)\n"
                    + "\n".join(example_lines)
                )
        except Exception as exc:
            logger.debug("Failed to load recent sessions: %s", exc)

        return "\n\n".join(sections)

    async def _build_system_prompt(self, session: AgenticSession) -> str:
        """Build the system prompt for autonomous operation."""
        base = self._config.get("ai_agent", {}).get("system_prompt", "")
        agentic_config = self._config.get("agentic_loop", {})
        extra_instructions = agentic_config.get("system_prompt_suffix", "")

        # Load institutional knowledge
        knowledge_context = await self._load_knowledge_context(session.goal)

        return f"""{base}

## Autonomous Mode

You are operating AUTONOMOUSLY — there is no human in the loop. You must
complete the goal entirely on your own by using the available tools.

Rules:
1. Break the goal into steps and execute them one by one.
2. After each tool call, assess the result and decide your next action.
3. If a tool fails, try an alternative approach before giving up.
4. When the goal is fully accomplished, call the `complete_task` tool with a summary.
5. Do NOT ask for human input — you are autonomous.
6. Be efficient: don't call tools unnecessarily or repeat the same call.
7. If you determine the goal is impossible with available tools, call
   `complete_task` explaining why.

Session ID: {session.session_id}
Max iterations: {session.max_iterations}

{knowledge_context}

{extra_instructions}"""

    async def _extract_learnings(self, session: AgenticSession) -> None:
        """Extract and store learnings from a completed session."""
        if not self._db or session.status != SessionStatus.COMPLETED:
            return

        try:
            goal_lower = session.goal.lower()
            tool_chain = session.tool_calls or []

            # Only learn from sessions that actually executed tools (not just triage)
            exec_tools = [t for t in tool_chain
                          if t.get("tool") == "execute_agent_tool"
                          and not t.get("error")]
            if not exec_tools:
                return

            tools_summary = " -> ".join(
                t.get("input", {}).get("tool_name", "?") for t in exec_tools
            )

            # Classify the pattern type
            pattern_type = "general"
            keywords = []
            if any(w in goal_lower for w in ["create user", "new user", "add user", "onboard"]):
                pattern_type = "user_creation"
                keywords = ["create", "user", "new", "onboard", "account", "entra"]
            elif any(w in goal_lower for w in ["create group", "new group", "add group"]):
                pattern_type = "group_creation"
                keywords = ["create", "group", "new", "security", "entra"]
            elif any(w in goal_lower for w in ["disable", "terminate", "offboard", "remove user"]):
                pattern_type = "user_termination"
                keywords = ["disable", "terminate", "offboard", "remove", "user"]
            elif any(w in goal_lower for w in ["printer", "print", "scanner"]):
                pattern_type = "troubleshooting_printer"
                keywords = ["printer", "print", "scanner", "troubleshoot"]
            elif any(w in goal_lower for w in ["password", "reset", "unlock"]):
                pattern_type = "password_reset"
                keywords = ["password", "reset", "unlock", "account"]
            elif any(w in goal_lower for w in ["license", "assign", "e3", "m365"]):
                pattern_type = "license_management"
                keywords = ["license", "assign", "m365", "e3", "subscription"]
            elif any(w in goal_lower for w in ["network", "connectivity", "vpn", "dns"]):
                pattern_type = "troubleshooting_network"
                keywords = ["network", "connectivity", "vpn", "dns", "internet"]
            else:
                # Extract top keywords from goal
                keywords = [w for w in goal_lower.split()
                            if len(w) > 3 and w not in {"this", "that", "from", "with", "have", "been"}][:6]

            # Store pattern
            approach = f"Used {len(exec_tools)} tool(s): {tools_summary}"
            if session.final_answer:
                approach += f" | Outcome: {session.final_answer[:200]}"

            await self._db.insert_learned_pattern({
                "pattern_type": pattern_type,
                "trigger_keywords": ",".join(keywords),
                "successful_approach": approach,
                "context": {
                    "tools_used": [t.get("input", {}).get("tool_name", "?") for t in exec_tools],
                    "agent": exec_tools[0].get("input", {}).get("agent_name", "") if exec_tools else "",
                    "iterations": session.iterations,
                },
                "source_session_id": session.session_id,
            })

            # Auto-learn org facts from tool results
            for tc in exec_tools:
                tool_name = tc.get("input", {}).get("tool_name", "")
                output = tc.get("output", {})

                # Learn domain from list_m365_domains
                if tool_name == "list_m365_domains" and isinstance(output, dict):
                    domains = output.get("domains") or output.get("result", {}).get("domains", [])
                    if isinstance(domains, list):
                        for d in domains:
                            name = d.get("id", "") if isinstance(d, dict) else str(d)
                            if name and "." in name:
                                await self._db.set_org_knowledge(
                                    "verified_domain", name, session.session_id)

                # Learn license info from list_m365_subscribed_skus
                if tool_name == "list_m365_subscribed_skus" and isinstance(output, dict):
                    skus = output.get("skus") or output.get("result", {}).get("skus", [])
                    if isinstance(skus, list):
                        for sku in skus:
                            if isinstance(sku, dict) and sku.get("sku_part_number"):
                                consumed = sku.get("consumed_units", 0)
                                enabled = sku.get("enabled_units", 0)
                                available = enabled - consumed
                                await self._db.set_org_knowledge(
                                    f"license_{sku['sku_part_number']}_available",
                                    str(available),
                                    session.session_id,
                                )

            logger.info(
                "Extracted learnings from session %s: type=%s, tools=%d",
                session.session_id, pattern_type, len(exec_tools),
            )

        except Exception as exc:
            logger.warning("Failed to extract learnings from session %s: %s",
                           session.session_id, exc)

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def run(
        self,
        goal: str,
        max_iterations: int = None,
        timeout_seconds: int = None,
        model: str = None,
        callback_url: str = None,
        metadata: dict = None,
        session_id: str = None,
    ) -> AgenticSession:
        """Run an autonomous agentic loop to accomplish the given goal.

        Args:
            goal: Natural language description of what to accomplish.
            max_iterations: Max Claude reasoning cycles (default from config).
            timeout_seconds: Hard timeout for the entire session.
            model: Claude model to use.
            callback_url: URL to POST results to when complete.
            metadata: Arbitrary metadata to attach to the session.
            session_id: Optional pre-assigned session ID.

        Returns:
            AgenticSession with results.
        """
        async with self._semaphore:
            return await self._run_inner(
                goal=goal,
                max_iterations=max_iterations,
                timeout_seconds=timeout_seconds,
                model=model,
                callback_url=callback_url,
                metadata=metadata,
                session_id=session_id,
            )

    async def _run_inner(
        self,
        goal: str,
        max_iterations: int = None,
        timeout_seconds: int = None,
        model: str = None,
        callback_url: str = None,
        metadata: dict = None,
        session_id: str = None,
    ) -> AgenticSession:
        agentic_config = self._config.get("agentic_loop", {})
        max_iter = max_iterations or agentic_config.get("max_iterations", 25)
        timeout = timeout_seconds or agentic_config.get("timeout_seconds", 600)
        mdl = model or agentic_config.get("model") or self._config.get("ai_agent", {}).get("model", "claude-sonnet-4-5-20250929")

        session = AgenticSession(
            session_id=session_id or str(uuid.uuid4()),
            goal=goal,
            max_iterations=max_iter,
            timeout_seconds=timeout,
            model=mdl,
            callback_url=callback_url,
            metadata=metadata,
        )
        self._sessions[session.session_id] = session

        # Persist session start
        if self._db:
            await self._db.insert_agentic_session(session.to_dict())
            await self._db.audit(
                "agentic_loop_started",
                details={"session_id": session.session_id, "goal": goal},
            )

        logger.info("Agentic loop started: %s — goal: %s", session.session_id, goal)

        tools_for_claude, handler_map = self._build_tools()
        system_prompt = await self._build_system_prompt(session)

        messages = [{"role": "user", "content": goal}]
        start_time = time.monotonic()

        try:
            for iteration in range(max_iter):
                # Check cancellation
                if session.session_id in self._cancelled:
                    session.status = SessionStatus.CANCELLED
                    session.error = "Cancelled by user"
                    break

                # Check timeout
                elapsed = time.monotonic() - start_time
                if elapsed > timeout:
                    session.status = SessionStatus.TIMEOUT
                    session.error = f"Timeout after {elapsed:.0f}s"
                    break

                session.iterations = iteration + 1

                # Call Claude (run sync SDK in thread to avoid blocking event loop)
                # Retry with exponential backoff on rate-limit (429) errors
                response = None
                for _attempt in range(5):
                    try:
                        response = await asyncio.to_thread(
                            self._client.messages.create,
                            model=mdl,
                            max_tokens=self._config.get("ai_agent", {}).get("max_tokens", 4096),
                            system=system_prompt,
                            tools=tools_for_claude,
                            messages=messages,
                        )
                        break  # success
                    except anthropic.RateLimitError:
                        wait = 2 ** _attempt * 15  # 15, 30, 60, 120, 240s
                        logger.warning(
                            "Rate limited (attempt %d/5), waiting %ds: %s",
                            _attempt + 1, wait, session.session_id,
                        )
                        await asyncio.sleep(wait)
                    except anthropic.APIError as exc:
                        session.status = SessionStatus.FAILED
                        session.error = f"Claude API error: {exc}"
                        break
                if response is None:
                    if session.status != SessionStatus.FAILED:
                        session.status = SessionStatus.FAILED
                        session.error = "Rate limited after 5 retries"
                    break

                # Track token usage
                session.total_input_tokens += response.usage.input_tokens
                session.total_output_tokens += response.usage.output_tokens

                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                # If Claude didn't call any tools, it's done
                if response.stop_reason != "tool_use":
                    text_parts = [
                        block.text for block in assistant_content
                        if hasattr(block, "text")
                    ]
                    session.final_answer = "\n".join(text_parts)
                    session.status = SessionStatus.COMPLETED
                    break

                # Execute tool calls
                tool_results = []
                for block in assistant_content:
                    if block.type != "tool_use":
                        continue

                    tool_name = block.name
                    tool_input = block.input

                    # Handle the special complete_task tool
                    if tool_name == "complete_task":
                        session.final_answer = tool_input.get("summary", "")
                        session.status = SessionStatus.COMPLETED
                        session.tool_calls.append({
                            "iteration": iteration + 1,
                            "tool": "complete_task",
                            "input": tool_input,
                            "output": {"status": "completed"},
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({"status": "completed"}),
                        })
                        break

                    # Execute via existing handler infrastructure
                    handler = handler_map.get(tool_name)
                    if handler:
                        try:
                            result = await handler(
                                tool_input, self._db, None, self._config,
                                **self._ctx,
                            )
                            result_str = json.dumps(result, default=str)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_str,
                            })
                            session.tool_calls.append({
                                "iteration": iteration + 1,
                                "tool": tool_name,
                                "input": tool_input,
                                "output": result,
                            })
                        except Exception as exc:
                            error_result = {"error": str(exc)}
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(error_result),
                                "is_error": True,
                            })
                            session.tool_calls.append({
                                "iteration": iteration + 1,
                                "tool": tool_name,
                                "input": tool_input,
                                "output": error_result,
                                "error": True,
                            })
                    else:
                        error_result = {"error": f"Unknown tool: {tool_name}"}
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(error_result),
                            "is_error": True,
                        })

                # If complete_task was called, stop the loop
                if session.status == SessionStatus.COMPLETED:
                    break

                messages.append({"role": "user", "content": tool_results})

                # Update DB after each iteration
                if self._db:
                    await self._db.update_agentic_session(
                        session.session_id,
                        iterations=session.iterations,
                        tool_calls=session.tool_calls,
                        input_tokens=session.total_input_tokens,
                        output_tokens=session.total_output_tokens,
                    )
            else:
                # Exhausted all iterations
                session.status = SessionStatus.MAX_ITERATIONS
                session.error = f"Reached max iterations ({max_iter})"

        except Exception as exc:
            session.status = SessionStatus.FAILED
            session.error = str(exc)
            logger.exception("Agentic loop failed: %s", session.session_id)

        # Finalize
        session.completed_at = datetime.now(timezone.utc).isoformat()

        if self._db:
            await self._db.finalize_agentic_session(session.to_dict())
            await self._db.audit(
                "agentic_loop_completed",
                details={
                    "session_id": session.session_id,
                    "status": session.status.value,
                    "iterations": session.iterations,
                    "input_tokens": session.total_input_tokens,
                    "output_tokens": session.total_output_tokens,
                },
            )

        logger.info(
            "Agentic loop finished: %s — status=%s iterations=%d tokens=%d/%d",
            session.session_id,
            session.status.value,
            session.iterations,
            session.total_input_tokens,
            session.total_output_tokens,
        )

        # Extract and store learnings from completed sessions
        await self._extract_learnings(session)

        # Fire callback webhook if configured
        if session.callback_url:
            await self._fire_callback(session)

        return session

    async def run_background(self, **kwargs) -> str:
        """Launch an agentic loop in the background. Returns session_id."""
        session_id = kwargs.get("session_id") or str(uuid.uuid4())
        kwargs["session_id"] = session_id

        async def _run():
            try:
                if self._semaphore.locked():
                    logger.info(
                        "Session %s waiting for concurrency slot", session_id,
                    )
                await self.run(**kwargs)
            except Exception:
                logger.exception("Background agentic loop failed: %s", session_id)

        asyncio.create_task(_run())
        return session_id

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Optional[AgenticSession]:
        return self._sessions.get(session_id)

    def list_sessions(self, limit: int = 50) -> list[dict]:
        sessions = sorted(
            self._sessions.values(),
            key=lambda s: s.started_at,
            reverse=True,
        )
        return [s.to_dict() for s in sessions[:limit]]

    def cancel_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            self._cancelled.add(session_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Callback webhook
    # ------------------------------------------------------------------

    async def _fire_callback(self, session: AgenticSession) -> None:
        """POST session results to the callback URL (for n8n, etc.)."""
        import httpx

        payload = session.to_dict()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    session.callback_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                logger.info(
                    "Callback fired for %s → %s (status %d)",
                    session.session_id,
                    session.callback_url,
                    resp.status_code,
                )
        except Exception as exc:
            logger.warning(
                "Callback failed for %s → %s: %s",
                session.session_id,
                session.callback_url,
                exc,
            )
