"""Orchestration Engine — Claude-powered task decomposition and execution.

Takes high-level directives like "Launch product next week" and decomposes
them into multi-agent task plans, then executes them as a DAG.
"""

import asyncio
import json
import logging
from typing import Any, Optional

from core.models import TaskPlan, TaskStep, ToolExecResult

logger = logging.getLogger("fleet.orchestration")


class OrchestrationEngine:
    """Decomposes directives into multi-agent task plans and executes them."""

    def __init__(self, fleet_engine, db=None, config: dict = None):
        self._fleet = fleet_engine
        self._db = db
        self._config = config or {}

    async def decompose_directive(self, directive: str) -> TaskPlan:
        """Use Claude to decompose a high-level directive into agent steps.

        Falls back to a simple single-step plan if Claude is unavailable.
        """
        agents = self._fleet.get_agents()
        all_tools = self._fleet.get_all_tools()

        # Build context for Claude
        agent_summary = "\n".join(
            f"- {a.name} ({a.display_name}): {a.tool_count} tools"
            for a in agents
        )

        # Sample tools per agent (top 10)
        tool_samples = {}
        for tool in all_tools:
            agent = tool.get("_agent", "")
            if agent not in tool_samples:
                tool_samples[agent] = []
            if len(tool_samples[agent]) < 10:
                tool_samples[agent].append(tool.get("name", ""))

        tool_context = "\n".join(
            f"- {agent}: {', '.join(tools)}"
            for agent, tools in tool_samples.items()
        )

        try:
            import anthropic
            client = anthropic.Anthropic()

            model = self._config.get("ai_agent", {}).get("model", "claude-sonnet-4-5-20250929")

            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system="You are a task planner for a fleet of AI agents. Decompose directives into concrete agent tool calls. Return JSON only.",
                messages=[{
                    "role": "user",
                    "content": f"""Decompose this directive into a multi-agent task plan.

Directive: {directive}

Available agents:
{agent_summary}

Sample tools per agent:
{tool_context}

Return a JSON object with this structure:
{{
  "directive": "the original directive",
  "steps": [
    {{
      "step_number": 1,
      "agent": "agent_name",
      "tool": "tool_name",
      "params": {{}},
      "description": "what this step does",
      "depends_on": []
    }}
  ],
  "estimated_agents": ["agent1", "agent2"]
}}

Return ONLY valid JSON, no markdown fences."""
                }],
            )

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]

            plan_data = json.loads(text)
            return TaskPlan(**plan_data)

        except Exception as exc:
            logger.warning("Claude decomposition failed: %s — using fallback", exc)
            return TaskPlan(
                directive=directive,
                steps=[TaskStep(
                    step_number=1,
                    agent="sysadmin_agent",
                    tool="list_servers",
                    description=f"Fallback: could not decompose '{directive}'",
                )],
                estimated_agents=["sysadmin_agent"],
            )

    async def execute_task_plan(self, plan: TaskPlan) -> dict[int, ToolExecResult]:
        """Execute a task plan respecting step dependencies (DAG)."""
        results: dict[int, ToolExecResult] = {}
        completed: set[int] = set()

        # Group steps by dependency level
        remaining = {s.step_number: s for s in plan.steps}

        if self._db:
            await self._db.audit(
                "plan_execution_started",
                details={"directive": plan.directive, "steps": len(plan.steps)},
            )

        while remaining:
            # Find steps whose dependencies are all satisfied
            ready = [
                s for s in remaining.values()
                if all(d in completed for d in s.depends_on)
            ]

            if not ready:
                logger.error("Deadlock detected in task plan — no ready steps")
                break

            # Execute ready steps concurrently
            exec_tasks = []
            for step in ready:
                exec_tasks.append(self._execute_step(step))

            step_results = await asyncio.gather(*exec_tasks, return_exceptions=True)

            for step, result in zip(ready, step_results):
                if isinstance(result, Exception):
                    results[step.step_number] = ToolExecResult(
                        agent_name=step.agent, tool_name=step.tool,
                        status="error", error=str(result),
                    )
                else:
                    results[step.step_number] = result

                completed.add(step.step_number)
                del remaining[step.step_number]

        if self._db:
            success_count = sum(1 for r in results.values() if r.status == "success")
            await self._db.audit(
                "plan_execution_completed",
                details={
                    "directive": plan.directive,
                    "total_steps": len(plan.steps),
                    "successful": success_count,
                },
            )

        return results

    async def _execute_step(self, step: TaskStep) -> ToolExecResult:
        """Execute a single plan step."""
        logger.info("Executing step %d: %s.%s", step.step_number, step.agent, step.tool)
        return await self._fleet.execute_tool(step.agent, step.tool, step.params)
