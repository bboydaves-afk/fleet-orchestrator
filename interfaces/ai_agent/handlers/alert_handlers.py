"""Handlers for alert AI tools."""

import logging

logger = logging.getLogger("fleet.handlers.alerts")


async def handle_list_alert_channels(params, db, cred_mgr, config, **ctx):
    alert_engine = ctx.get("alert_engine")
    return {"channels": alert_engine.list_channels()}


async def handle_add_alert_channel(params, db, cred_mgr, config, **ctx):
    alert_engine = ctx.get("alert_engine")
    await alert_engine.register_channel(
        params["name"], params["channel_type"], params["config"])
    return {"status": "created", "channel": params["name"]}


async def handle_test_alert_channel(params, db, cred_mgr, config, **ctx):
    alert_engine = ctx.get("alert_engine")
    ok = await alert_engine.test_channel(params["channel_name"])
    return {"status": "sent" if ok else "failed", "channel": params["channel_name"]}


async def handle_list_alert_rules(params, db, cred_mgr, config, **ctx):
    alert_engine = ctx.get("alert_engine")
    return {"rules": alert_engine.list_rules()}


async def handle_add_alert_rule(params, db, cred_mgr, config, **ctx):
    alert_engine = ctx.get("alert_engine")
    await alert_engine.add_rule(
        name=params["name"],
        condition=params["condition"],
        severity=params["severity"],
        channels=params["channels"],
        duration_seconds=params.get("duration_seconds", 0),
        description=params.get("description", ""),
    )
    return {"status": "created", "rule": params["name"]}


async def handle_get_active_alerts(params, db, cred_mgr, config, **ctx):
    alert_engine = ctx.get("alert_engine")
    return {"alerts": alert_engine.get_active_alerts()}


async def handle_get_alert_history(params, db, cred_mgr, config, **ctx):
    alert_engine = ctx.get("alert_engine")
    limit = params.get("limit", 50)
    return {"alerts": await alert_engine.get_alert_history(limit)}


async def handle_resolve_alert(params, db, cred_mgr, config, **ctx):
    alert_engine = ctx.get("alert_engine")
    ok = await alert_engine.resolve_alert_by_id(params["alert_id"])
    return {"status": "resolved" if ok else "not_found", "alert_id": params["alert_id"]}


async def handle_send_notification(params, db, cred_mgr, config, **ctx):
    alert_engine = ctx.get("alert_engine")
    results = await alert_engine.send_notification(
        params["channels"], params["message"], params.get("severity", "info"))
    return {"status": "sent", "results": results}
