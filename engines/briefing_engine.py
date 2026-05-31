"""Briefing Engine — fleet-wide status reports and morning briefings."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("fleet.briefing")


class BriefingEngine:
    """Generates fleet-wide status reports and morning briefings."""

    def __init__(self, fleet_engine, health_engine, db=None, config: dict = None):
        self._fleet = fleet_engine
        self._health = health_engine
        self._db = db
        self._config = config or {}

    async def morning_briefing(self) -> dict:
        """Generate a comprehensive morning briefing."""
        fleet_status = await self._health.get_fleet_status()
        recent_execs = []
        audit_entries = []

        if self._db:
            recent_execs = await self._db.get_recent_executions(20)
            audit_entries = await self._db.get_audit_log(20)

        # Count execution stats
        success_count = sum(1 for e in recent_execs if e.get("status") == "success")
        error_count = sum(1 for e in recent_execs if e.get("status") == "error")

        briefing = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fleet_health": fleet_status["summary"],
            "agents": fleet_status["agents"],
            "recent_activity": {
                "total_executions": len(recent_execs),
                "successful": success_count,
                "errors": error_count,
            },
            "summary": self._generate_summary(fleet_status, recent_execs),
        }

        if self._db:
            await self._db.audit("morning_briefing_generated")

        return briefing

    async def status_report(self) -> dict:
        """Generate a quick fleet status report."""
        fleet_status = await self._health.get_fleet_status()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fleet": fleet_status["summary"],
            "agents": [
                {
                    "name": a["name"],
                    "display_name": a["display_name"],
                    "status": a["status"],
                    "tools": a["tool_count"],
                }
                for a in fleet_status["agents"]
            ],
        }

    def _generate_summary(self, fleet_status: dict, recent_execs: list) -> str:
        """Generate a human-readable summary string."""
        summary = fleet_status["summary"]
        lines = [
            f"Fleet Status: {summary['online']}/{summary['total_agents']} agents online, "
            f"{summary['total_tools']} total tools available.",
        ]

        if summary["offline"] > 0:
            offline_agents = [
                a["display_name"] for a in fleet_status["agents"]
                if a["status"] == "offline"
            ]
            lines.append(f"Offline: {', '.join(offline_agents)}")

        if summary["degraded"] > 0:
            degraded_agents = [
                a["display_name"] for a in fleet_status["agents"]
                if a["status"] == "degraded"
            ]
            lines.append(f"Degraded: {', '.join(degraded_agents)}")

        if recent_execs:
            lines.append(f"Recent activity: {len(recent_execs)} tool executions.")

        return " ".join(lines)
