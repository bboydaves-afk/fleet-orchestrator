"""Handlers for policy AI tools."""

import logging

logger = logging.getLogger("fleet.handlers.policies")


async def handle_list_policies(params, db, cred_mgr, config, **ctx):
    policy_engine = ctx.get("policy_engine")
    return {"policies": policy_engine.list_policies()}


async def handle_get_policy(params, db, cred_mgr, config, **ctx):
    policy_engine = ctx.get("policy_engine")
    policy = policy_engine.get_policy(params["policy_name"])
    if not policy:
        return {"error": f"Policy not found: {params['policy_name']}"}
    return policy


async def handle_enable_policy(params, db, cred_mgr, config, **ctx):
    policy_engine = ctx.get("policy_engine")
    ok = await policy_engine.enable_policy(params["policy_name"])
    return {"status": "enabled" if ok else "not_found", "policy": params["policy_name"]}


async def handle_disable_policy(params, db, cred_mgr, config, **ctx):
    policy_engine = ctx.get("policy_engine")
    ok = await policy_engine.disable_policy(params["policy_name"])
    return {"status": "disabled" if ok else "not_found", "policy": params["policy_name"]}


async def handle_get_policy_history(params, db, cred_mgr, config, **ctx):
    policy_engine = ctx.get("policy_engine")
    return {"history": await policy_engine.get_policy_history(
        params.get("policy_name", ""), params.get("limit", 50))}


async def handle_get_policy_stats(params, db, cred_mgr, config, **ctx):
    policy_engine = ctx.get("policy_engine")
    return await policy_engine.get_policy_stats()


async def handle_approve_policy_execution(params, db, cred_mgr, config, **ctx):
    policy_engine = ctx.get("policy_engine")
    ok = await policy_engine.approve_execution(params["approval_id"])
    return {"status": "approved" if ok else "not_found", "approval_id": params["approval_id"]}


async def handle_get_pending_approvals(params, db, cred_mgr, config, **ctx):
    policy_engine = ctx.get("policy_engine")
    return {"approvals": await policy_engine.get_pending_approvals()}


async def handle_get_fleet_events(params, db, cred_mgr, config, **ctx):
    fleet_monitor = ctx.get("fleet_monitor")
    return {"events": await fleet_monitor.get_fleet_events(
        params.get("event_type") or None, params.get("limit", 50))}
