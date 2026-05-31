"""FastAPI web application for Fleet Orchestrator dashboard."""

import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from core.database import Database
from core.credentials import CredentialManager
from engines.fleet_engine import FleetEngine
from engines.health_engine import HealthEngine
from engines.orchestration_engine import OrchestrationEngine
from engines.workflow_engine import WorkflowEngine
from engines.briefing_engine import BriefingEngine
from engines.alert_engine import AlertEngine
from engines.escalation_manager import EscalationManager
from engines.fleet_monitoring_engine import FleetMonitoringEngine
from engines.policy_engine import PolicyEngine
from engines.scheduler_engine import SchedulerEngine
from engines.agentic_loop_engine import AgenticLoopEngine
from engines.backup_engine import BackupEngine
from engines.process_manager import ProcessManager
from engines.credential_rotation import CredentialRotation

logger = logging.getLogger("fleet.web")

app_state = {}


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    db_path = config.get("database", {}).get("path", "data/fleet_orchestrator.db")
    db = Database(db_path)
    await db.connect()

    cred_mgr = CredentialManager(db)

    fleet = FleetEngine(config)
    await fleet.initialize(db)

    # Connect to all agents in background
    try:
        await fleet.connect_all()
    except Exception as exc:
        logger.warning("Initial fleet connection partially failed: %s", exc)

    health = HealthEngine(fleet, db)
    orchestration = OrchestrationEngine(fleet, db, config)
    workflow = WorkflowEngine(fleet, db)
    await workflow.initialize()
    briefing = BriefingEngine(fleet, health, db, config)

    # --- Autonomous operations layer ---
    auto_config = config.get("autonomous", {})

    alert_engine = AlertEngine(db)
    await alert_engine.initialize()
    await alert_engine.auto_configure_from_config(config)

    escalation_mgr = EscalationManager(db=db, config=config)

    policy_engine = PolicyEngine(
        fleet_engine=fleet,
        workflow_engine=workflow,
        alert_engine=alert_engine,
        escalation_manager=escalation_mgr,
        db=db,
        config=config,
    )
    await policy_engine.start()

    # Auto-enable safe policies
    if auto_config.get("auto_enable_safe_policies", False):
        await policy_engine.auto_enable_safe_policies()

    fleet_monitor = FleetMonitoringEngine(fleet, health, db)
    fleet_monitor.register_policy_callback(policy_engine.on_fleet_event)
    fleet_monitor.register_alert_callback(alert_engine.evaluate_fleet_event)

    backup_engine = BackupEngine(db_path)
    process_manager = ProcessManager(db=db)
    cred_rotation = CredentialRotation(fleet_engine=fleet, db=db)

    scheduler = SchedulerEngine(
        workflow_engine=workflow,
        briefing_engine=briefing,
        fleet_engine=fleet,
        db=db,
        config=config,
        backup_engine=backup_engine,
    )
    await scheduler.initialize()
    await scheduler.start()

    # Agentic loop engine
    agentic_loop_engine = AgenticLoopEngine(
        fleet_engine=fleet,
        health_engine=health,
        orchestration_engine=orchestration,
        workflow_engine=workflow,
        briefing_engine=briefing,
        alert_engine=alert_engine,
        escalation_mgr=escalation_mgr,
        policy_engine=policy_engine,
        fleet_monitor=fleet_monitor,
        scheduler_engine=scheduler,
        db=db,
        config=config,
    )

    # Start fleet monitoring
    monitor_interval = auto_config.get("fleet_monitor_interval_seconds", 120)
    await fleet_monitor.start_monitoring(interval_sec=monitor_interval)

    app_state.update({
        "config": config,
        "db": db,
        "cred_mgr": cred_mgr,
        "fleet_engine": fleet,
        "health_engine": health,
        "orchestration_engine": orchestration,
        "workflow_engine": workflow,
        "briefing_engine": briefing,
        "alert_engine": alert_engine,
        "escalation_mgr": escalation_mgr,
        "policy_engine": policy_engine,
        "fleet_monitor": fleet_monitor,
        "scheduler_engine": scheduler,
        "agentic_loop_engine": agentic_loop_engine,
        "backup_engine": backup_engine,
        "process_manager": process_manager,
        "cred_rotation": cred_rotation,
    })

    logger.info("Fleet Orchestrator web app started: %d agents, %d tools",
                fleet.agent_count, fleet.total_tool_count)

    yield

    await scheduler.stop()
    await fleet_monitor.stop_monitoring()
    await policy_engine.stop()
    await fleet.shutdown()
    await db.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Fleet Orchestrator",
        description="AI Agent Fleet Management Dashboard",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from .routes import (
        dashboard, agents, tools, workflows, health, chat,
        scheduler, alerts, policies, escalations, agentic, slack,
    )
    app.include_router(dashboard.router)
    app.include_router(agents.router)
    app.include_router(tools.router)
    app.include_router(workflows.router)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(scheduler.router)
    app.include_router(alerts.router)
    app.include_router(policies.router)
    app.include_router(escalations.router)
    app.include_router(agentic.router)
    app.include_router(slack.router)

    return app
