"""Scheduler API routes."""

import json
import logging
from fastapi import APIRouter, Depends
from ..auth import get_current_user

logger = logging.getLogger("fleet.web.scheduler")
router = APIRouter(tags=["scheduler"])


@router.get("/api/scheduler/jobs")
async def list_jobs(_user: str = Depends(get_current_user)):
    from ..app import app_state
    scheduler = app_state.get("scheduler_engine")
    return {"jobs": scheduler.list_jobs()}


@router.get("/api/scheduler/jobs/{name}")
async def get_job(name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state
    scheduler = app_state.get("scheduler_engine")
    job = scheduler.get_job(name)
    if not job:
        return {"error": f"Job not found: {name}"}
    return job


@router.post("/api/scheduler/jobs")
async def add_job(body: dict, _user: str = Depends(get_current_user)):
    from ..app import app_state
    scheduler = app_state.get("scheduler_engine")
    trigger_config = {}
    if body.get("cron"):
        trigger_config["cron"] = body["cron"]
    if body.get("interval_seconds"):
        trigger_config["interval_seconds"] = body["interval_seconds"]
    result = await scheduler.add_job(
        name=body["name"],
        description=body.get("description", ""),
        trigger_type=body.get("trigger_type", "cron"),
        trigger_config=trigger_config,
        action_type=body.get("action_type", "workflow"),
        action_config=body.get("action_config", {}),
        enabled=body.get("enabled", False),
    )
    return {"status": "created", "job": body["name"]}


@router.post("/api/scheduler/jobs/{name}/enable")
async def enable_job(name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state
    scheduler = app_state.get("scheduler_engine")
    ok = await scheduler.enable_job(name)
    return {"status": "enabled" if ok else "not_found"}


@router.post("/api/scheduler/jobs/{name}/disable")
async def disable_job(name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state
    scheduler = app_state.get("scheduler_engine")
    ok = await scheduler.disable_job(name)
    return {"status": "disabled" if ok else "not_found"}


@router.post("/api/scheduler/jobs/{name}/trigger")
async def trigger_job(name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state
    scheduler = app_state.get("scheduler_engine")
    return await scheduler.trigger_job_now(name)


@router.delete("/api/scheduler/jobs/{name}")
async def remove_job(name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state
    scheduler = app_state.get("scheduler_engine")
    ok = await scheduler.remove_job(name)
    return {"status": "removed" if ok else "not_found"}
