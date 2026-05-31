"""Handlers for scheduler AI tools."""

import json
import logging

logger = logging.getLogger("fleet.handlers.scheduler")


async def handle_list_scheduled_jobs(params, db, cred_mgr, config, **ctx):
    scheduler = ctx.get("scheduler_engine")
    return {"jobs": scheduler.list_jobs()}


async def handle_get_scheduled_job(params, db, cred_mgr, config, **ctx):
    scheduler = ctx.get("scheduler_engine")
    job = scheduler.get_job(params["job_name"])
    if not job:
        return {"error": f"Job not found: {params['job_name']}"}
    return job


async def handle_add_scheduled_job(params, db, cred_mgr, config, **ctx):
    scheduler = ctx.get("scheduler_engine")
    trigger_config = {}
    if params.get("cron"):
        trigger_config["cron"] = params["cron"]
    if params.get("interval_seconds"):
        trigger_config["interval_seconds"] = params["interval_seconds"]
    result = await scheduler.add_job(
        name=params["name"],
        description=params.get("description", ""),
        trigger_type=params["trigger_type"],
        trigger_config=trigger_config,
        action_type=params["action_type"],
        action_config=params.get("action_config", {}),
        enabled=params.get("enabled", False),
    )
    return {"status": "created", "job": result.get("name", params["name"])}


async def handle_enable_scheduled_job(params, db, cred_mgr, config, **ctx):
    scheduler = ctx.get("scheduler_engine")
    ok = await scheduler.enable_job(params["job_name"])
    return {"status": "enabled" if ok else "not_found", "job": params["job_name"]}


async def handle_disable_scheduled_job(params, db, cred_mgr, config, **ctx):
    scheduler = ctx.get("scheduler_engine")
    ok = await scheduler.disable_job(params["job_name"])
    return {"status": "disabled" if ok else "not_found", "job": params["job_name"]}


async def handle_trigger_job_now(params, db, cred_mgr, config, **ctx):
    scheduler = ctx.get("scheduler_engine")
    return await scheduler.trigger_job_now(params["job_name"])


async def handle_remove_scheduled_job(params, db, cred_mgr, config, **ctx):
    scheduler = ctx.get("scheduler_engine")
    ok = await scheduler.remove_job(params["job_name"])
    return {"status": "removed" if ok else "not_found", "job": params["job_name"]}
