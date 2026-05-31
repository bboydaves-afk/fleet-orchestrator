"""Scheduler Engine -- APScheduler-based recurring job execution."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("fleet.scheduler")


class SchedulerEngine:
    """Manages recurring jobs: workflows, briefings, health reports, tool executions."""

    def __init__(self, fleet_engine, workflow_engine, briefing_engine,
                 db=None, config: dict = None, backup_engine=None):
        self._fleet = fleet_engine
        self._workflow = workflow_engine
        self._briefing = briefing_engine
        self._backup = backup_engine
        self._db = db
        self._config = config or {}
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._jobs: dict[str, dict] = {}

    async def initialize(self) -> None:
        """Create the APScheduler and load jobs from DB + config."""
        self._scheduler = AsyncIOScheduler(timezone="UTC")

        # Load saved jobs from DB
        if self._db:
            saved_jobs = await self._db.get_scheduled_jobs()
            for job in saved_jobs:
                if job.get("enabled"):
                    self._register_job_from_db(job)
                self._jobs[job["name"]] = job

        # Register built-in jobs from config
        self._register_builtin_jobs()

    async def start(self) -> None:
        """Start the scheduler."""
        if self._scheduler and not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started with %d registered jobs",
                        len(self._scheduler.get_jobs()))

    async def stop(self) -> None:
        """Shutdown the scheduler."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def _register_builtin_jobs(self) -> None:
        """Register default jobs from config.yaml autonomous section."""
        auto_config = self._config.get("autonomous", {})
        scheduled = auto_config.get("scheduled_jobs", [])

        # Handle both list format [{name: ..., ...}] and dict format {name: {...}}
        if isinstance(scheduled, dict):
            items = [(k, v) for k, v in scheduled.items()]
        elif isinstance(scheduled, list):
            items = [(j.get("name", f"job_{i}"), j) for i, j in enumerate(scheduled)]
        else:
            items = []

        for name, job_conf in items:
            if name in self._jobs:
                continue  # already loaded from DB
            trigger = job_conf.get("trigger", {})
            trigger_type = trigger.get("type", "cron")
            job_data = {
                "name": name,
                "description": job_conf.get("description", f"Built-in: {name}"),
                "trigger_type": trigger_type,
                "trigger_config": json.dumps({
                    "cron": trigger.get("cron", job_conf.get("cron")),
                    "interval_seconds": trigger.get("interval_seconds",
                                                     job_conf.get("interval_seconds")),
                    "timezone": trigger.get("timezone", "UTC"),
                }),
                "action_type": job_conf.get("action_type", "workflow"),
                "action_config": json.dumps(job_conf.get("action_config", {})),
                "enabled": int(job_conf.get("enabled", False)),
            }
            self._jobs[name] = job_data
            if job_conf.get("enabled"):
                self._register_job_from_db(job_data)

    def _register_job_from_db(self, job_row: dict) -> None:
        """Register a job from a DB row."""
        name = job_row["name"]
        trigger_type = job_row.get("trigger_type", "cron")
        trigger_config = job_row.get("trigger_config", "{}")
        if isinstance(trigger_config, str):
            trigger_config = json.loads(trigger_config)
        action_type = job_row.get("action_type", "workflow")
        action_config = job_row.get("action_config", "{}")
        if isinstance(action_config, str):
            action_config = json.loads(action_config)

        try:
            trigger = self._build_trigger(trigger_type, trigger_config)
        except Exception as exc:
            logger.warning("Failed to build trigger for job '%s': %s", name, exc)
            return

        job_func = self._get_job_func(action_type)
        if not job_func:
            logger.warning("Unknown action type '%s' for job '%s'", action_type, name)
            return

        try:
            self._scheduler.add_job(
                job_func,
                trigger=trigger,
                id=name,
                name=name,
                kwargs={"job_name": name, "action_config": action_config},
                replace_existing=True,
            )
            logger.info("Registered scheduled job: %s (%s)", name, trigger_type)
        except Exception as exc:
            logger.warning("Failed to register job '%s': %s", name, exc)

    def _build_trigger(self, trigger_type: str, config: dict):
        """Build an APScheduler trigger from config."""
        if trigger_type == "cron":
            cron_expr = config.get("cron", "0 8 * * *")
            parts = cron_expr.split()
            if len(parts) == 5:
                return CronTrigger(
                    minute=parts[0], hour=parts[1], day=parts[2],
                    month=parts[3], day_of_week=parts[4])
            return CronTrigger.from_crontab(cron_expr)
        elif trigger_type == "interval":
            seconds = config.get("interval_seconds", 3600)
            return IntervalTrigger(seconds=seconds)
        raise ValueError(f"Unknown trigger type: {trigger_type}")

    def _get_job_func(self, action_type: str):
        """Get the job runner function for an action type."""
        return {
            "workflow": self._run_workflow_job,
            "briefing": self._run_briefing_job,
            "health_report": self._run_health_report_job,
            "tool_exec": self._run_tool_exec_job,
            "backup": self._run_backup_job,
        }.get(action_type)

    async def add_job(self, name: str, description: str, trigger_type: str,
                       trigger_config: dict, action_type: str,
                       action_config: dict, enabled: bool = False) -> dict:
        """Add a new scheduled job."""
        job_data = {
            "name": name,
            "description": description,
            "trigger_type": trigger_type,
            "trigger_config": json.dumps(trigger_config),
            "action_type": action_type,
            "action_config": json.dumps(action_config),
            "enabled": int(enabled),
        }
        self._jobs[name] = job_data

        if self._db:
            await self._db.upsert_scheduled_job(
                name, description, trigger_type, trigger_config,
                action_type, action_config, enabled)

        if enabled:
            self._register_job_from_db(job_data)

        logger.info("Added scheduled job: %s (enabled=%s)", name, enabled)
        return job_data

    async def remove_job(self, name: str) -> bool:
        """Remove a scheduled job."""
        removed = self._jobs.pop(name, None) is not None
        try:
            if self._scheduler:
                self._scheduler.remove_job(name)
        except Exception:
            pass
        if self._db:
            await self._db.delete_scheduled_job(name)
        return removed

    async def enable_job(self, name: str) -> bool:
        """Enable a scheduled job."""
        if name not in self._jobs:
            return False
        self._jobs[name]["enabled"] = 1
        if self._db:
            await self._db.set_job_enabled(name, True)
        self._register_job_from_db(self._jobs[name])
        return True

    async def disable_job(self, name: str) -> bool:
        """Disable a scheduled job."""
        if name not in self._jobs:
            return False
        self._jobs[name]["enabled"] = 0
        if self._db:
            await self._db.set_job_enabled(name, False)
        try:
            if self._scheduler:
                self._scheduler.remove_job(name)
        except Exception:
            pass
        return True

    def list_jobs(self) -> list[dict]:
        """List all scheduled jobs with their next run time."""
        result = []
        for name, job_data in self._jobs.items():
            next_run = None
            if self._scheduler:
                try:
                    ap_job = self._scheduler.get_job(name)
                    if ap_job and hasattr(ap_job, "next_run_time") and ap_job.next_run_time:
                        next_run = ap_job.next_run_time.isoformat()
                except Exception:
                    pass
            result.append({
                "name": name,
                "description": job_data.get("description", ""),
                "trigger_type": job_data.get("trigger_type", ""),
                "action_type": job_data.get("action_type", ""),
                "enabled": bool(job_data.get("enabled", 0)),
                "last_run": job_data.get("last_run"),
                "next_run": next_run,
                "run_count": job_data.get("run_count", 0),
            })
        return result

    def get_job(self, name: str) -> Optional[dict]:
        """Get details of a specific job."""
        job_data = self._jobs.get(name)
        if not job_data:
            return None
        tc = job_data.get("trigger_config", "{}")
        ac = job_data.get("action_config", "{}")
        return {
            "name": name,
            "description": job_data.get("description", ""),
            "trigger_type": job_data.get("trigger_type", ""),
            "trigger_config": json.loads(tc) if isinstance(tc, str) else tc,
            "action_type": job_data.get("action_type", ""),
            "action_config": json.loads(ac) if isinstance(ac, str) else ac,
            "enabled": bool(job_data.get("enabled", 0)),
            "last_run": job_data.get("last_run"),
            "run_count": job_data.get("run_count", 0),
        }

    async def trigger_job_now(self, name: str) -> dict:
        """Manually trigger a job immediately."""
        job_data = self._jobs.get(name)
        if not job_data:
            return {"status": "error", "message": f"Job '{name}' not found"}
        action_type = job_data.get("action_type", "workflow")
        ac = job_data.get("action_config", "{}")
        action_config = json.loads(ac) if isinstance(ac, str) else ac
        job_func = self._get_job_func(action_type)
        if not job_func:
            return {"status": "error", "message": f"Unknown action: {action_type}"}
        try:
            await job_func(job_name=name, action_config=action_config)
            return {"status": "success", "message": f"Job '{name}' triggered"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Internal job runners
    # ------------------------------------------------------------------

    async def _run_workflow_job(self, job_name: str = "",
                                 action_config: dict = None) -> None:
        """Execute a workflow as a scheduled job."""
        config = action_config or {}
        workflow_name = config.get("workflow_name", job_name)
        logger.info("Scheduler executing workflow: %s", workflow_name)
        try:
            result = await self._workflow.execute_workflow(workflow_name)
            result_str = "success"
        except Exception as exc:
            logger.error("Scheduled workflow '%s' failed: %s", workflow_name, exc)
            result_str = f"error: {exc}"
        if self._db:
            await self._db.update_job_run(job_name, result_str)
            await self._db.audit("scheduled_job_executed", details={
                "job": job_name, "action": "workflow", "result": result_str})

    async def _run_briefing_job(self, job_name: str = "",
                                  action_config: dict = None) -> None:
        """Generate a morning briefing."""
        logger.info("Scheduler generating briefing")
        try:
            result = await self._briefing.morning_briefing()
            result_str = "success"
        except Exception as exc:
            logger.error("Scheduled briefing failed: %s", exc)
            result_str = f"error: {exc}"
        if self._db:
            await self._db.update_job_run(job_name, result_str)

    async def _run_health_report_job(self, job_name: str = "",
                                       action_config: dict = None) -> None:
        """Generate a fleet health report."""
        logger.info("Scheduler generating health report")
        try:
            result = await self._briefing.status_report()
            result_str = "success"
        except Exception as exc:
            logger.error("Scheduled health report failed: %s", exc)
            result_str = f"error: {exc}"
        if self._db:
            await self._db.update_job_run(job_name, result_str)

    async def _run_tool_exec_job(self, job_name: str = "",
                                   action_config: dict = None) -> None:
        """Execute a specific tool as a scheduled job."""
        config = action_config or {}
        agent_name = config.get("agent_name", "")
        tool_name = config.get("tool_name", "")
        params = config.get("params", {})
        logger.info("Scheduler executing tool: %s.%s", agent_name, tool_name)
        try:
            result = await self._fleet.execute_tool(agent_name, tool_name, params)
            result_str = "success"
        except Exception as exc:
            logger.error("Scheduled tool exec failed: %s", exc)
            result_str = f"error: {exc}"
        if self._db:
            await self._db.update_job_run(job_name, result_str)

    async def _run_backup_job(self, job_name: str = "",
                                action_config: dict = None) -> None:
        """Create a database backup and clean up old backups."""
        logger.info("Scheduler running database backup")
        result_str = "success"
        try:
            if self._backup:
                result = await self._backup.create_backup()
                if result.get("success"):
                    deleted = await self._backup.cleanup_old(keep=30)
                    logger.info("Backup complete, cleaned %d old backups", deleted)
                else:
                    result_str = f"error: {result.get('error')}"
            else:
                result_str = "error: backup engine not initialized"
        except Exception as exc:
            logger.error("Scheduled backup failed: %s", exc)
            result_str = f"error: {exc}"
        if self._db:
            await self._db.update_job_run(job_name, result_str)
            await self._db.audit("scheduled_job_executed", details={
                "job": job_name, "action": "backup", "result": result_str})
