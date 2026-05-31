"""Workflow Engine — YAML-defined cross-agent workflow execution.

Enhanced with state passing (${{step.result.field}} templates),
retry logic, and step timeouts.
"""

import asyncio
import copy
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from core.models import WorkflowDefinition, WorkflowStep, WorkflowExecStatus, ToolExecResult

logger = logging.getLogger("fleet.workflow")

# Template pattern: ${{step_name.result.field_name}}
_TEMPLATE_RE = re.compile(r'\$\{\{(\w+)\.result\.(\w+)\}\}')


class WorkflowEngine:
    """Loads and executes YAML workflow definitions with state passing and retries."""

    def __init__(self, fleet_engine, db=None, workflow_dir: str = "data/workflows"):
        self._fleet = fleet_engine
        self._db = db
        self._workflow_dir = Path(workflow_dir)
        self._workflows: dict[str, WorkflowDefinition] = {}

    async def initialize(self) -> None:
        """Load all workflow definitions from disk."""
        self._workflow_dir.mkdir(parents=True, exist_ok=True)
        for path in self._workflow_dir.glob("*.yaml"):
            try:
                with open(path, "r") as f:
                    raw = yaml.safe_load(f)
                wf = WorkflowDefinition(
                    name=raw.get("name", path.stem),
                    description=raw.get("description", ""),
                    steps=[WorkflowStep(**s) for s in raw.get("steps", [])],
                )
                self._workflows[wf.name] = wf
                logger.info("Loaded workflow: %s (%d steps)", wf.name, len(wf.steps))
            except Exception as exc:
                logger.warning("Failed to load workflow %s: %s", path.name, exc)

        # Also load from DB
        if self._db:
            db_workflows = await self._db.fetch_all("SELECT * FROM workflows")
            for row in db_workflows:
                try:
                    defn = json.loads(row["definition"])
                    wf = WorkflowDefinition(**defn)
                    self._workflows[wf.name] = wf
                except Exception:
                    pass

    def list_workflows(self) -> list[dict]:
        """List all available workflows."""
        return [
            {
                "name": wf.name,
                "description": wf.description,
                "steps": len(wf.steps),
                "agents": list(set(s.agent for s in wf.steps)),
            }
            for wf in self._workflows.values()
        ]

    def get_workflow(self, name: str) -> Optional[WorkflowDefinition]:
        return self._workflows.get(name)

    async def execute_workflow(self, name: str,
                                initial_context: dict = None) -> dict:
        """Execute a named workflow with state passing and retry support."""
        wf = self._workflows.get(name)
        if not wf:
            return {"error": f"Workflow not found: {name}"}

        logger.info("Executing workflow: %s (%d steps)", name, len(wf.steps))

        if self._db:
            await self._db.audit("workflow_started", details={"workflow": name})

        status = WorkflowExecStatus(
            workflow_name=name,
            status="running",
            steps_total=len(wf.steps),
        )

        # State context: stores results from completed steps
        context = dict(initial_context or {})
        results = {}
        completed_steps: set[str] = set()
        remaining = {s.name: s for s in wf.steps}

        while remaining:
            # Find ready steps (all dependencies completed)
            ready = [
                s for s in remaining.values()
                if all(d in completed_steps for d in s.depends_on)
            ]

            if not ready:
                logger.error("Workflow %s: deadlock — no ready steps", name)
                status.status = "failed"
                break

            for step in ready:
                # Resolve template params from context
                resolved_params = self._resolve_params(step.params, context)

                # Get retry/timeout settings (defaults for backward compat)
                retries = getattr(step, "retries", 0) or 0
                retry_delay = getattr(step, "retry_delay_seconds", 5) or 5
                timeout = getattr(step, "timeout_seconds", 60) or 60

                logger.info("Workflow %s: executing step '%s' (%s.%s)",
                            name, step.name, step.agent, step.tool)

                # Execute with retry logic
                result = await self._execute_step_with_retry(
                    step, resolved_params, retries, retry_delay, timeout)

                # Store in results
                results[step.name] = {
                    "agent": step.agent,
                    "tool": step.tool,
                    "status": result.status,
                    "result": result.result,
                    "error": result.error,
                    "duration_ms": result.duration_ms,
                }

                # Store in context for state passing
                context[step.name] = {
                    "result": result.result,
                    "status": result.status,
                    "error": result.error,
                }

                if result.status == "error":
                    on_error = step.on_error
                    if on_error == "stop":
                        logger.error("Workflow %s: step '%s' failed — stopping",
                                     name, step.name)
                        status.status = "failed"
                        remaining.clear()
                        break
                    elif on_error == "skip":
                        logger.warning("Workflow %s: step '%s' failed — skipping",
                                       name, step.name)
                    # "continue" and "retry" (retries exhausted) fall through

                completed_steps.add(step.name)
                status.steps_completed += 1
                del remaining[step.name]

        if status.status != "failed":
            status.status = "completed"

        status.results = results

        if self._db:
            await self._db.audit(
                "workflow_completed",
                details={"workflow": name, "status": status.status,
                         "steps_completed": status.steps_completed},
            )

        return status.model_dump()

    async def _execute_step_with_retry(self, step: WorkflowStep,
                                        params: dict, retries: int,
                                        retry_delay: int,
                                        timeout: int) -> ToolExecResult:
        """Execute a tool with optional timeout and retries."""
        last_result = None
        attempts = retries + 1  # at least 1 attempt

        for attempt in range(attempts):
            try:
                result = await asyncio.wait_for(
                    self._fleet.execute_tool(step.agent, step.tool, params),
                    timeout=timeout,
                )
                if result.status != "error" or attempt >= retries:
                    return result
                last_result = result
                logger.warning(
                    "Step '%s' attempt %d/%d failed, retrying in %ds",
                    step.name, attempt + 1, attempts, retry_delay)
                await asyncio.sleep(retry_delay)
            except asyncio.TimeoutError:
                last_result = ToolExecResult(
                    agent_name=step.agent,
                    tool_name=step.tool,
                    status="error",
                    error=f"Timeout after {timeout}s",
                )
                if attempt < retries:
                    logger.warning(
                        "Step '%s' timed out, retrying in %ds",
                        step.name, retry_delay)
                    await asyncio.sleep(retry_delay)
            except Exception as exc:
                last_result = ToolExecResult(
                    agent_name=step.agent,
                    tool_name=step.tool,
                    status="error",
                    error=str(exc),
                )
                if attempt < retries:
                    await asyncio.sleep(retry_delay)

        return last_result

    def _resolve_params(self, params: dict, context: dict) -> dict:
        """Replace ${{step_name.result.field}} templates with actual values."""
        if not context:
            return params
        resolved = copy.deepcopy(params)
        self._resolve_dict(resolved, context)
        return resolved

    def _resolve_dict(self, obj: Any, context: dict) -> None:
        """Recursively resolve templates in a dict/list."""
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                val = obj[key]
                if isinstance(val, str):
                    obj[key] = self._resolve_string(val, context)
                elif isinstance(val, (dict, list)):
                    self._resolve_dict(val, context)
        elif isinstance(obj, list):
            for i, val in enumerate(obj):
                if isinstance(val, str):
                    obj[i] = self._resolve_string(val, context)
                elif isinstance(val, (dict, list)):
                    self._resolve_dict(val, context)

    def _resolve_string(self, value: str, context: dict) -> Any:
        """Resolve template references in a string value."""
        def replacer(match):
            step_name = match.group(1)
            field_name = match.group(2)
            step_ctx = context.get(step_name, {})
            result = step_ctx.get("result", {})
            if isinstance(result, dict):
                return str(result.get(field_name, match.group(0)))
            return match.group(0)

        return _TEMPLATE_RE.sub(replacer, value)
