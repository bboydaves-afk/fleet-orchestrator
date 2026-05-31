"""Alert and notification API routes."""

import logging
from fastapi import APIRouter, Depends
from ..auth import get_current_user

logger = logging.getLogger("fleet.web.alerts")
router = APIRouter(tags=["alerts"])


@router.get("/api/alerts/channels")
async def list_channels(_user: str = Depends(get_current_user)):
    from ..app import app_state
    alert_engine = app_state.get("alert_engine")
    return {"channels": alert_engine.list_channels()}


@router.post("/api/alerts/channels")
async def add_channel(body: dict, _user: str = Depends(get_current_user)):
    from ..app import app_state
    alert_engine = app_state.get("alert_engine")
    await alert_engine.register_channel(
        body["name"], body["channel_type"], body["config"])
    return {"status": "created", "channel": body["name"]}


@router.post("/api/alerts/channels/{name}/test")
async def test_channel(name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state
    alert_engine = app_state.get("alert_engine")
    ok = await alert_engine.test_channel(name)
    return {"status": "sent" if ok else "failed"}


@router.get("/api/alerts/rules")
async def list_rules(_user: str = Depends(get_current_user)):
    from ..app import app_state
    alert_engine = app_state.get("alert_engine")
    return {"rules": alert_engine.list_rules()}


@router.post("/api/alerts/rules")
async def add_rule(body: dict, _user: str = Depends(get_current_user)):
    from ..app import app_state
    alert_engine = app_state.get("alert_engine")
    await alert_engine.add_rule(
        name=body["name"], condition=body["condition"],
        severity=body.get("severity", "warning"),
        channels=body.get("channels", []),
        duration_seconds=body.get("duration_seconds", 0),
        description=body.get("description", ""))
    return {"status": "created", "rule": body["name"]}


@router.get("/api/alerts/active")
async def active_alerts(_user: str = Depends(get_current_user)):
    from ..app import app_state
    alert_engine = app_state.get("alert_engine")
    return {"alerts": alert_engine.get_active_alerts()}


@router.get("/api/alerts/history")
async def alert_history(limit: int = 50, _user: str = Depends(get_current_user)):
    from ..app import app_state
    alert_engine = app_state.get("alert_engine")
    return {"alerts": await alert_engine.get_alert_history(limit)}


@router.post("/api/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int, _user: str = Depends(get_current_user)):
    from ..app import app_state
    alert_engine = app_state.get("alert_engine")
    ok = await alert_engine.resolve_alert_by_id(alert_id)
    return {"status": "resolved" if ok else "not_found"}


@router.post("/api/alerts/notify")
async def send_notification(body: dict, _user: str = Depends(get_current_user)):
    from ..app import app_state
    alert_engine = app_state.get("alert_engine")
    results = await alert_engine.send_notification(
        body["channels"], body["message"], body.get("severity", "info"))
    return {"status": "sent", "results": results}
