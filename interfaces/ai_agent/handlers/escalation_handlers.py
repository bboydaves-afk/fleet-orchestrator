"""Handlers for escalation AI tools."""

import logging

logger = logging.getLogger("fleet.handlers.escalations")


async def handle_get_active_escalations(params, db, cred_mgr, config, **ctx):
    escalation_mgr = ctx.get("escalation_mgr")
    return {"escalations": escalation_mgr.get_active_escalations()}


async def handle_get_escalation_stats(params, db, cred_mgr, config, **ctx):
    escalation_mgr = ctx.get("escalation_mgr")
    return escalation_mgr.get_escalation_stats()


async def handle_acknowledge_escalation(params, db, cred_mgr, config, **ctx):
    escalation_mgr = ctx.get("escalation_mgr")
    ok = await escalation_mgr.acknowledge_issue(params["issue_key"])
    return {"status": "acknowledged" if ok else "not_found", "issue_key": params["issue_key"]}


async def handle_resolve_escalation(params, db, cred_mgr, config, **ctx):
    escalation_mgr = ctx.get("escalation_mgr")
    ok = await escalation_mgr.resolve_issue(params["issue_key"])
    return {"status": "resolved" if ok else "not_found", "issue_key": params["issue_key"]}
