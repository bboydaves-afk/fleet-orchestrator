"""Escalation Manager -- 4-level intelligent escalation for fleet issues.

L0: Auto-fix (execute workflow/tool)
L1: Notify team (Slack/email)
L2: Page on-call (urgent channel)
L3: Management escalation
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("fleet.escalation")


@dataclass
class EscalationState:
    """Per-issue escalation tracking."""
    issue_key: str
    severity: str
    first_seen: float  # monotonic time
    last_attempt: float  # monotonic time
    attempt_count: int = 0
    current_level: int = 0
    auto_fix_attempted: bool = False
    auto_fix_result: Optional[str] = None
    acknowledged: bool = False


class EscalationManager:
    """Context-aware escalation decisions based on severity x attempts x business hours."""

    def __init__(self, db=None, config: dict = None):
        self._db = db
        self._config = config or {}
        self._escalation_state: dict[str, EscalationState] = {}
        esc_config = self._config.get("autonomous", {}).get("escalation", {})
        self._business_hours_start = esc_config.get("business_hours_start", 9)
        self._business_hours_end = esc_config.get("business_hours_end", 17)
        self._default_channel = esc_config.get("default_channel", "slack")
        self._page_channel = esc_config.get("page_channel", "slack")

    async def evaluate_escalation(self, event_type: str, event_data: dict,
                                   auto_fix_result: str = None) -> dict:
        """Decide escalation action.

        Returns dict with: action, level, channel, message, reason
        Actions: auto_fix | notify | page | escalate | suppress
        """
        issue_key = self._generate_issue_key(event_data)
        now = time.monotonic()

        if issue_key not in self._escalation_state:
            self._escalation_state[issue_key] = EscalationState(
                issue_key=issue_key,
                severity=event_data.get("severity", "warning"),
                first_seen=now,
                last_attempt=now,
            )

        state = self._escalation_state[issue_key]
        state.attempt_count += 1
        state.last_attempt = now

        if auto_fix_result:
            state.auto_fix_attempted = True
            state.auto_fix_result = auto_fix_result

        decision = self._make_decision(state, event_data, auto_fix_result)

        state.current_level = decision["level"]

        # Persist to DB
        if self._db:
            try:
                await self._db.upsert_escalation(
                    issue_key=issue_key,
                    severity=state.severity,
                    current_level=state.current_level,
                    attempt_count=state.attempt_count,
                    auto_fix_attempted=state.auto_fix_attempted,
                    auto_fix_result=state.auto_fix_result,
                )
            except Exception as exc:
                logger.warning("Failed to persist escalation: %s", exc)

        logger.info("Escalation decision for %s: %s (level %d, attempt %d)",
                     issue_key, decision["action"], decision["level"],
                     state.attempt_count)
        return decision

    def _make_decision(self, state: EscalationState, event_data: dict,
                        auto_fix_result: str = None) -> dict:
        """Core decision tree."""
        severity = state.severity
        attempts = state.attempt_count

        if state.acknowledged:
            return {
                "action": "suppress",
                "level": state.current_level,
                "channel": "",
                "message": f"Issue {state.issue_key} acknowledged, suppressing",
                "reason": "Issue acknowledged by operator",
            }

        # Auto-fix succeeded -> L0 informational
        if auto_fix_result and auto_fix_result.lower() in ("success", "ok", "fixed"):
            return {
                "action": "notify",
                "level": 0,
                "channel": self._default_channel,
                "message": self._format_message(state, event_data, "Auto-fix succeeded"),
                "reason": "Auto-fix resolved the issue",
            }

        # Critical + first occurrence -> immediate L2 page
        if severity == "critical" and attempts <= 1:
            return {
                "action": "page",
                "level": 2,
                "channel": self._page_channel,
                "message": self._format_message(state, event_data, "CRITICAL"),
                "reason": "Critical severity requires immediate attention",
            }

        # First occurrence -> L0 auto-fix attempt
        if attempts <= 1:
            return {
                "action": "auto_fix",
                "level": 0,
                "channel": "",
                "message": self._format_message(state, event_data, "Attempting auto-fix"),
                "reason": "First occurrence, attempting automatic remediation",
            }

        # 2-3 failures -> L1 team notification
        if attempts <= 3:
            return {
                "action": "notify",
                "level": 1,
                "channel": self._default_channel,
                "message": self._format_message(state, event_data,
                    f"Recurring issue (attempt {attempts})"),
                "reason": f"Failed {attempts} times, notifying team",
            }

        # 4-5 failures -> L2 page on-call
        if attempts <= 5:
            return {
                "action": "page",
                "level": 2,
                "channel": self._page_channel,
                "message": self._format_message(state, event_data,
                    f"ESCALATED - {attempts} failures"),
                "reason": f"Failed {attempts} times, paging on-call",
            }

        # 6+ failures -> L3 management escalation
        return {
            "action": "escalate",
            "level": 3,
            "channel": self._page_channel,
            "message": self._format_message(state, event_data,
                f"MANAGEMENT ESCALATION - {attempts} failures"),
            "reason": f"Failed {attempts} times, escalating to management",
        }

    async def resolve_issue(self, issue_key: str) -> bool:
        """Resolve an escalation issue."""
        if issue_key in self._escalation_state:
            del self._escalation_state[issue_key]
        if self._db:
            return await self._db.resolve_escalation(issue_key)
        return True

    async def acknowledge_issue(self, issue_key: str) -> bool:
        """Acknowledge an issue (suppresses further escalation)."""
        if issue_key in self._escalation_state:
            self._escalation_state[issue_key].acknowledged = True
        if self._db:
            return await self._db.acknowledge_escalation(issue_key)
        return True

    def get_active_escalations(self) -> list[dict]:
        """Get all active (non-resolved) escalations."""
        return [
            {
                "issue_key": s.issue_key,
                "severity": s.severity,
                "current_level": s.current_level,
                "attempt_count": s.attempt_count,
                "auto_fix_attempted": s.auto_fix_attempted,
                "auto_fix_result": s.auto_fix_result,
                "acknowledged": s.acknowledged,
                "age_seconds": int(time.monotonic() - s.first_seen),
            }
            for s in self._escalation_state.values()
        ]

    def get_escalation_stats(self) -> dict:
        """Get aggregate escalation stats."""
        active = list(self._escalation_state.values())
        by_level = {}
        by_severity = {}
        for s in active:
            by_level[s.current_level] = by_level.get(s.current_level, 0) + 1
            by_severity[s.severity] = by_severity.get(s.severity, 0) + 1
        return {
            "total_active": len(active),
            "by_level": by_level,
            "by_severity": by_severity,
            "acknowledged": sum(1 for s in active if s.acknowledged),
        }

    async def cleanup_resolved(self, max_age_seconds: float = 3600) -> int:
        """Remove old resolved entries from in-memory state."""
        now = time.monotonic()
        to_remove = [
            k for k, s in self._escalation_state.items()
            if (now - s.last_attempt) > max_age_seconds
        ]
        for k in to_remove:
            del self._escalation_state[k]
        return len(to_remove)

    def _is_business_hours(self) -> bool:
        """Check if current time is within business hours."""
        hour = datetime.now(timezone.utc).hour
        return self._business_hours_start <= hour < self._business_hours_end

    def _generate_issue_key(self, event_data: dict) -> str:
        """Generate a unique key for an issue."""
        event_type = event_data.get("event_type", "unknown")
        agent = event_data.get("agent_name", "unknown")
        return f"{event_type}:{agent}"

    def _format_message(self, state: EscalationState, event_data: dict,
                         prefix: str) -> str:
        """Format a human-readable escalation message."""
        agent = event_data.get("agent_name", "unknown")
        event_type = event_data.get("event_type", "unknown")
        return (
            f"[{prefix}] Agent: {agent} | Event: {event_type} | "
            f"Level: L{state.current_level} | Attempts: {state.attempt_count}"
        )
