"""Policy Engine -- YAML-driven automated remediation for fleet events.

Evaluates incoming fleet events against configured remediation policies.
When a match is found, executes the policy's action chain with cooldown,
retry tracking, and escalation support.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("fleet.policy")


class FleetPolicy:
    """Parsed fleet remediation policy from YAML."""

    def __init__(self):
        self.name: str = ""
        self.version: str = "1.0"
        self.description: str = ""
        self.enabled: bool = False
        self.trigger_type: str = "fleet_event"
        self.conditions: dict = {}
        self.target_filter: dict = {}
        self.actions: list[dict] = []
        self.cooldown_seconds: int = 300
        self.max_retries: int = 3
        self.escalate_after_retries: int = 3
        self.escalation_channels: list[str] = []
        self.require_approval: bool = False

    @classmethod
    def from_yaml(cls, filepath: str) -> "FleetPolicy":
        """Load a policy from a YAML file."""
        with open(filepath, "r") as f:
            data = yaml.safe_load(f) or {}
        p = cls()
        p.name = data.get("name", Path(filepath).stem)
        p.version = data.get("version", "1.0")
        p.description = data.get("description", "")
        p.enabled = data.get("enabled", False)
        p.trigger_type = data.get("trigger_type", "fleet_event")
        p.conditions = data.get("conditions", {})
        p.target_filter = data.get("target_filter", {})
        p.actions = data.get("actions", [])
        p.cooldown_seconds = data.get("cooldown_seconds", 300)
        p.max_retries = data.get("max_retries", 3)
        p.escalate_after_retries = data.get("escalate_after_retries", 3)
        p.escalation_channels = data.get("escalation_channels", [])
        p.require_approval = data.get("require_approval", False)
        return p

    @classmethod
    def load_directory(cls, directory: str) -> dict[str, "FleetPolicy"]:
        """Load all policies from a directory."""
        policies = {}
        dirpath = Path(directory)
        if not dirpath.exists():
            return policies
        for fp in sorted(dirpath.glob("*.yaml")):
            try:
                p = cls.from_yaml(str(fp))
                policies[p.name] = p
                logger.info("Loaded policy: %s from %s", p.name, fp.name)
            except Exception as exc:
                logger.warning("Failed to load policy %s: %s", fp, exc)
        return policies

    def to_dict(self) -> dict:
        return {
            "name": self.name, "version": self.version,
            "description": self.description, "enabled": self.enabled,
            "trigger_type": self.trigger_type, "conditions": self.conditions,
            "target_filter": self.target_filter, "actions": self.actions,
            "cooldown_seconds": self.cooldown_seconds,
            "max_retries": self.max_retries,
            "escalate_after_retries": self.escalate_after_retries,
            "escalation_channels": self.escalation_channels,
            "require_approval": self.require_approval,
        }

    def matches_fleet_event(self, event_data: dict) -> bool:
        """Check if a fleet event matches this policy's conditions."""
        if not self.conditions:
            return True
        cond_event_type = self.conditions.get("event_type")
        if cond_event_type and event_data.get("event_type") != cond_event_type:
            return False
        return True

    def matches_target(self, event_data: dict) -> bool:
        """Check if an event's agent matches the target filter."""
        if not self.target_filter:
            return True
        agent_names = self.target_filter.get("agent_names", [])
        if agent_names:
            return event_data.get("agent_name", "") in agent_names
        return True


class PolicyEngine:
    """Evaluates fleet events against policies and executes action chains."""

    def __init__(self, fleet_engine, workflow_engine, alert_engine,
                 escalation_manager, db=None, config: dict = None):
        self._fleet = fleet_engine
        self._workflow = workflow_engine
        self._alert_engine = alert_engine
        self._escalation = escalation_manager
        self._db = db
        self._config = config or {}
        self._policy_dir = self._config.get("autonomous", {}).get(
            "policy_dir", "data/policies")
        self._policies: dict[str, FleetPolicy] = {}
        self._cooldowns: dict[str, float] = {}
        self._retry_tracker: dict[str, int] = {}
        self._running = False

    async def start(self) -> None:
        """Load policies from YAML files and sync DB state."""
        self._policies = FleetPolicy.load_directory(self._policy_dir)

        # Sync DB state -> override enabled flag from DB
        if self._db:
            for name, policy in self._policies.items():
                await self._db.upsert_policy_state(name, policy.enabled)
            db_states = await self._db.get_policy_states()
            for row in db_states:
                if row["name"] in self._policies:
                    self._policies[row["name"]].enabled = bool(row.get("enabled", 0))

        self._running = True
        logger.info("PolicyEngine started with %d policies", len(self._policies))

    async def stop(self) -> None:
        """Stop the policy engine."""
        self._running = False
        logger.info("PolicyEngine stopped")

    async def on_fleet_event(self, event_type: str, event_data: dict) -> None:
        """Handle fleet events from FleetMonitoringEngine."""
        if not self._running:
            return

        for name, policy in self._policies.items():
            if not policy.enabled:
                continue
            if policy.trigger_type != "fleet_event":
                continue
            if not policy.matches_fleet_event(event_data):
                continue
            if not policy.matches_target(event_data):
                continue

            await self._execute_policy(name, policy, event_data)

    async def on_alert_event(self, event_type: str, alert_data: dict) -> None:
        """Handle alert events."""
        if not self._running:
            return

        for name, policy in self._policies.items():
            if not policy.enabled:
                continue
            if policy.trigger_type != "alert":
                continue
            if not policy.matches_fleet_event(alert_data):
                continue

            await self._execute_policy(name, policy, alert_data)

    async def _execute_policy(self, name: str, policy: FleetPolicy,
                               trigger_data: dict) -> None:
        """Execute a matched policy with cooldown/retry/approval checks."""
        agent_name = trigger_data.get("agent_name", "")
        cooldown_key = f"{name}:{agent_name}" if agent_name else name

        # Check cooldown
        if cooldown_key in self._cooldowns:
            elapsed = time.monotonic() - self._cooldowns[cooldown_key]
            if elapsed < policy.cooldown_seconds:
                remaining = int(policy.cooldown_seconds - elapsed)
                logger.info("Policy '%s' on cooldown (%ds remaining)", name, remaining)
                return

        # Check retry limit
        retry_key = cooldown_key
        retry_count = self._retry_tracker.get(retry_key, 0)
        if retry_count >= policy.max_retries:
            logger.warning("Policy '%s' exceeded max retries (%d)",
                           name, policy.max_retries)
            if retry_count >= policy.escalate_after_retries:
                await self._escalate(name, policy, trigger_data, retry_count)
            return

        # Approval gate
        if policy.require_approval:
            approval_id = str(uuid.uuid4())[:8]
            if self._db:
                await self._db.insert_policy_execution(
                    name, agent_name, policy.trigger_type,
                    trigger_data, approval_id=approval_id)
                await self._db.execute(
                    "UPDATE policy_executions SET status='pending_approval' WHERE approval_id=?",
                    (approval_id,))
            logger.info("Policy '%s' requires approval (id=%s)", name, approval_id)
            # Notify about pending approval
            if self._alert_engine:
                await self._alert_engine.send_notification(
                    policy.escalation_channels or ["slack"],
                    f"Policy '{name}' requires approval (id={approval_id}): "
                    f"agent={agent_name}, event={trigger_data.get('event_type', '')}",
                    "warning")
            return

        # Execute action chain
        logger.info("Executing policy '%s' for agent '%s'", name, agent_name)
        exec_id = None
        start = time.monotonic()
        if self._db:
            exec_id = await self._db.insert_policy_execution(
                name, agent_name, policy.trigger_type, trigger_data)

        success = True
        result = {}
        error_msg = None

        for i, action in enumerate(policy.actions):
            try:
                action_result = await self._execute_policy_action(
                    action, trigger_data, policy)
                result[f"action_{i}"] = action_result
                if not action_result.get("success", True):
                    success = False
                    error_msg = action_result.get("error", "Action failed")
                    break
            except Exception as exc:
                success = False
                error_msg = str(exc)
                result[f"action_{i}"] = {"success": False, "error": str(exc)}
                logger.error("Policy action %d failed: %s", i, exc)
                break

        duration = time.monotonic() - start

        # Update cooldown and retry tracking
        self._cooldowns[cooldown_key] = time.monotonic()
        if success:
            self._retry_tracker.pop(retry_key, None)
        else:
            self._retry_tracker[retry_key] = retry_count + 1

        # Persist result
        if self._db and exec_id:
            status = "completed" if success else "failed"
            await self._db.update_policy_execution(
                exec_id, status, result, error_msg, duration)
            await self._db.update_policy_triggered(name, status)

        if self._db:
            await self._db.audit(
                "policy_executed", agent_name=agent_name,
                details={"policy": name, "success": success,
                         "duration_s": round(duration, 2)})

    async def _execute_policy_action(self, action: dict, trigger_data: dict,
                                      policy: FleetPolicy) -> dict:
        """Dispatch a single policy action."""
        action_type = action.get("type", "")
        agent_name = trigger_data.get("agent_name", "")

        if action_type == "workflow":
            wf_name = action.get("workflow_name", "")
            try:
                result = await self._workflow.execute_workflow(wf_name)
                return {"success": True, "type": "workflow", "result": result}
            except Exception as exc:
                return {"success": False, "type": "workflow", "error": str(exc)}

        elif action_type == "tool_exec":
            target_agent = action.get("agent_name", agent_name)
            # Resolve ${{trigger.agent_name}} template
            if target_agent and "${{trigger.agent_name}}" in target_agent:
                target_agent = agent_name
            tool_name = action.get("tool_name", "")
            params = action.get("params", {})
            try:
                result = await self._fleet.execute_tool(
                    target_agent, tool_name, params)
                return {"success": True, "type": "tool_exec",
                        "result": result.model_dump() if hasattr(result, "model_dump") else result}
            except Exception as exc:
                return {"success": False, "type": "tool_exec", "error": str(exc)}

        elif action_type == "alert":
            message = action.get("message", "Policy alert")
            # Resolve templates in message
            message = message.replace("${{agent_name}}", agent_name)
            channels = action.get("channels", [])
            severity = trigger_data.get("severity", "warning")
            if self._alert_engine:
                await self._alert_engine.send_notification(
                    channels, message, severity)
            return {"success": True, "type": "alert", "message": message}

        elif action_type == "escalate":
            level = action.get("level", 1)
            message = action.get("message", "Policy escalation")
            message = message.replace("${{agent_name}}", agent_name)
            channels = action.get("channels", [])
            if self._alert_engine and channels:
                await self._alert_engine.send_notification(
                    channels, message, "critical")
            return {"success": True, "type": "escalate", "level": level}

        else:
            return {"success": False, "type": action_type,
                    "error": f"Unknown action type: {action_type}"}

    async def _escalate(self, name: str, policy: FleetPolicy,
                         trigger_data: dict, retry_count: int) -> None:
        """Escalate when retry limit exceeded."""
        if self._escalation:
            event_data = {
                **trigger_data,
                "severity": "critical",
                "policy_name": name,
                "retry_count": retry_count,
            }
            decision = await self._escalation.evaluate_escalation(
                "policy_retry_exceeded", event_data)
            if decision.get("channel") and self._alert_engine:
                await self._alert_engine.send_notification(
                    [decision["channel"]], decision.get("message", ""),
                    "critical")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_policies(self) -> list[dict]:
        """List all policies."""
        return [p.to_dict() for p in self._policies.values()]

    def get_policy(self, name: str) -> Optional[dict]:
        """Get a specific policy."""
        p = self._policies.get(name)
        return p.to_dict() if p else None

    async def enable_policy(self, name: str) -> bool:
        """Enable a policy."""
        p = self._policies.get(name)
        if not p:
            return False
        p.enabled = True
        if self._db:
            await self._db.set_policy_enabled(name, True)
        logger.info("Policy enabled: %s", name)
        return True

    async def disable_policy(self, name: str) -> bool:
        """Disable a policy."""
        p = self._policies.get(name)
        if not p:
            return False
        p.enabled = False
        if self._db:
            await self._db.set_policy_enabled(name, False)
        logger.info("Policy disabled: %s", name)
        return True

    async def approve_execution(self, approval_id: str,
                                 approved_by: str = "admin") -> bool:
        """Approve a pending policy execution."""
        if self._db:
            return await self._db.approve_policy_execution(approval_id, approved_by)
        return False

    async def get_pending_approvals(self) -> list[dict]:
        """Get pending approval requests."""
        if self._db:
            return await self._db.get_pending_approvals()
        return []

    async def get_policy_history(self, policy_name: str = "",
                                  limit: int = 50) -> list[dict]:
        """Get policy execution history."""
        if self._db:
            return await self._db.get_policy_executions(
                policy_name or None, limit)
        return []

    async def auto_enable_safe_policies(self) -> list[str]:
        """Enable all policies that only send notifications (no approval required).

        Safe policies are those where `require_approval` is False and all
        actions are either `alert` or `escalate` type (not `workflow`/`tool_exec`),
        OR have `require_approval: true` (which is inherently safe since it
        won't execute without human confirmation).
        """
        enabled_names = []
        for name, policy in self._policies.items():
            if policy.enabled:
                continue  # already enabled
            # Always safe to enable approval-gated policies
            if policy.require_approval:
                await self.enable_policy(name)
                enabled_names.append(name)
                continue
            # Enable notification-only policies (alert/escalate actions only)
            action_types = {a.get("type", "") for a in policy.actions}
            safe_types = {"alert", "escalate"}
            if action_types.issubset(safe_types):
                await self.enable_policy(name)
                enabled_names.append(name)
                continue
            # Enable workflow policies with cooldowns > 0 (conservative)
            if "workflow" in action_types and policy.cooldown_seconds >= 300:
                await self.enable_policy(name)
                enabled_names.append(name)

        if enabled_names:
            logger.info("Auto-enabled %d safe policies: %s",
                        len(enabled_names), ", ".join(enabled_names))
        return enabled_names

    def get_policy_stats(self) -> dict:
        """Get aggregate policy stats."""
        total = len(self._policies)
        enabled = sum(1 for p in self._policies.values() if p.enabled)
        cooldowns_active = len(self._cooldowns)
        retries_active = sum(v for v in self._retry_tracker.values())
        return {
            "total_count": total,
            "enabled_count": enabled,
            "disabled_count": total - enabled,
            "cooldowns_active": cooldowns_active,
            "retries_pending": retries_active,
        }
