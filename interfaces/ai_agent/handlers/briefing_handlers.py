"""Handlers for briefing and reporting tools."""

import logging

logger = logging.getLogger("fleet.handlers.briefing")


async def handle_morning_briefing(params, db, cred_mgr, config, **ctx):
    briefing = ctx.get("briefing_engine")
    return await briefing.morning_briefing()


async def handle_status_report(params, db, cred_mgr, config, **ctx):
    briefing = ctx.get("briefing_engine")
    return await briefing.status_report()


async def handle_search_audit_log(params, db, cred_mgr, config, **ctx):
    limit = params.get("limit", 50)
    if db:
        entries = await db.get_audit_log(limit)
        return {"entries": entries, "count": len(entries)}
    return {"entries": [], "count": 0}
