"""Health Engine — continuous monitoring and fleet status reporting."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from core.models import AgentStatus

logger = logging.getLogger("fleet.health")


class HealthEngine:
    """Monitors fleet health, provides status reports, manages circuit breakers."""

    def __init__(self, fleet_engine, db=None):
        self._fleet = fleet_engine
        self._db = db
        self._monitoring_task: Optional[asyncio.Task] = None
        self._interval_sec: int = 120

    async def start_monitoring(self, interval_sec: int = 120) -> None:
        """Start background health monitoring loop."""
        self._interval_sec = interval_sec
        if self._monitoring_task and not self._monitoring_task.done():
            return
        self._monitoring_task = asyncio.create_task(self._monitor_loop())
        logger.info("Health monitoring started (interval=%ds)", interval_sec)

    async def stop_monitoring(self) -> None:
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None
            logger.info("Health monitoring stopped")

    async def _monitor_loop(self) -> None:
        while True:
            try:
                await self._fleet.health_check_all()
            except Exception as exc:
                logger.exception("Health check cycle error: %s", exc)
            await asyncio.sleep(self._interval_sec)

    async def get_fleet_status(self) -> dict:
        """Get comprehensive fleet status report."""
        agents = self._fleet.get_agents()
        statuses = await self._fleet.health_check_all()

        online = sum(1 for s in statuses.values() if s == AgentStatus.ONLINE)
        degraded = sum(1 for s in statuses.values() if s == AgentStatus.DEGRADED)
        offline = sum(1 for s in statuses.values() if s == AgentStatus.OFFLINE)

        agent_details = []
        for agent in agents:
            status = statuses.get(agent.name, AgentStatus.UNKNOWN)
            agent_details.append({
                "name": agent.name,
                "display_name": agent.display_name,
                "url": agent.url,
                "status": status.value,
                "tool_count": agent.tool_count,
            })

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_agents": len(agents),
                "online": online,
                "degraded": degraded,
                "offline": offline,
                "total_tools": self._fleet.total_tool_count,
            },
            "agents": agent_details,
        }

    async def get_health_history(self, agent_name: str = None,
                                  limit: int = 50) -> list[dict]:
        """Get health check history from database."""
        if not self._db:
            return []

        if agent_name:
            return await self._db.fetch_all(
                "SELECT * FROM health_snapshots WHERE agent_name=? ORDER BY checked_at DESC LIMIT ?",
                (agent_name, limit),
            )
        return await self._db.fetch_all(
            "SELECT * FROM health_snapshots ORDER BY checked_at DESC LIMIT ?",
            (limit,),
        )
