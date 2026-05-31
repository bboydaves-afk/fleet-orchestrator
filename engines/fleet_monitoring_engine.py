"""Fleet Monitoring Engine -- state change detection for the agent fleet.

Wraps the existing HealthEngine's polling loop and adds state transition
detection. When an agent's status changes (online->offline, etc.), it emits
FleetEvents that trigger the PolicyEngine and AlertEngine.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger("fleet.monitoring")


class FleetMonitoringEngine:
    """Active fleet monitoring with state change detection."""

    def __init__(self, fleet_engine, health_engine, db=None):
        self._fleet = fleet_engine
        self._health = health_engine
        self._db = db
        self._monitoring_task: Optional[asyncio.Task] = None
        self._interval_sec: int = 120

        # State tracking
        self._previous_states: dict[str, str] = {}
        self._state_timestamps: dict[str, float] = {}

        # Callbacks
        self._policy_callback: Optional[Callable] = None
        self._alert_callback: Optional[Callable] = None

    def register_policy_callback(self, callback: Callable) -> None:
        """Register: async def callback(event_type: str, event_data: dict)"""
        self._policy_callback = callback

    def register_alert_callback(self, callback: Callable) -> None:
        """Register: async def callback(fleet_event)"""
        self._alert_callback = callback

    async def start_monitoring(self, interval_sec: int = 120) -> None:
        """Start the active monitoring loop."""
        self._interval_sec = interval_sec
        if self._monitoring_task and not self._monitoring_task.done():
            return
        self._monitoring_task = asyncio.create_task(self._monitor_loop())
        logger.info("Fleet monitoring started (interval=%ds)", interval_sec)

    async def stop_monitoring(self) -> None:
        """Stop the monitoring loop."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None
            logger.info("Fleet monitoring stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while True:
            try:
                statuses = await self._fleet.health_check_all()
                await self._detect_state_changes(statuses)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Fleet monitoring cycle error: %s", exc)
            await asyncio.sleep(self._interval_sec)

    async def _detect_state_changes(self, statuses: dict) -> None:
        """Compare current statuses against previous, emit events on changes."""
        for agent_name, current_status in statuses.items():
            current_val = current_status.value if hasattr(current_status, "value") else str(current_status)
            previous_val = self._previous_states.get(agent_name)

            if previous_val is None:
                self._previous_states[agent_name] = current_val
                self._state_timestamps[agent_name] = time.monotonic()
                continue

            if current_val != previous_val:
                event_type = self._map_transition(previous_val, current_val)
                if event_type:
                    await self._emit_fleet_event(
                        event_type, agent_name,
                        {"previous_status": previous_val,
                         "current_status": current_val})
                self._previous_states[agent_name] = current_val
                self._state_timestamps[agent_name] = time.monotonic()

    def _map_transition(self, prev: str, current: str) -> Optional[str]:
        """Map a state transition to a fleet event type."""
        if current == "offline":
            return "agent_offline"
        if current == "degraded":
            return "agent_degraded"
        if current == "online" and prev in ("offline", "unknown"):
            return "agent_recovered"
        if current == "online" and prev == "degraded":
            return "agent_recovered"
        if current == "online":
            return "agent_online"
        return None

    async def _emit_fleet_event(self, event_type: str, agent_name: str,
                                 details: dict) -> None:
        """Store event in DB and notify callbacks."""
        logger.info("Fleet event: %s for %s", event_type, agent_name)

        if self._db:
            try:
                await self._db.insert_fleet_event(event_type, agent_name, details)
            except Exception as exc:
                logger.warning("Failed to store fleet event: %s", exc)

        event_data = {
            "event_type": event_type,
            "agent_name": agent_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **details,
        }

        # Notify PolicyEngine
        if self._policy_callback:
            try:
                await self._policy_callback(event_type, event_data)
            except Exception as exc:
                logger.error("Policy callback error: %s", exc)

        # Notify AlertEngine
        if self._alert_callback:
            try:
                from core.models import FleetEvent, FleetEventType
                event_enum = FleetEventType(event_type) if event_type in FleetEventType.__members__.values() else None
                if event_enum:
                    fe = FleetEvent(
                        event_type=event_enum,
                        agent_name=agent_name,
                        timestamp=event_data["timestamp"],
                        details=details,
                    )
                    await self._alert_callback(fe)
                else:
                    await self._alert_callback(event_data)
            except Exception as exc:
                logger.error("Alert callback error: %s", exc)

    def get_agent_states(self) -> dict[str, dict]:
        """Get current tracked agent states with timestamps."""
        result = {}
        now = time.monotonic()
        for name, status in self._previous_states.items():
            ts = self._state_timestamps.get(name, now)
            result[name] = {
                "status": status,
                "since_seconds": int(now - ts),
            }
        return result

    async def get_fleet_events(self, event_type: str = None,
                                limit: int = 50) -> list[dict]:
        """Query fleet events from DB."""
        if self._db:
            return await self._db.get_fleet_events(event_type, limit)
        return []
