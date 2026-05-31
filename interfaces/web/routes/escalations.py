"""Escalation API routes."""

import logging
from fastapi import APIRouter, Depends
from ..auth import get_current_user

logger = logging.getLogger("fleet.web.escalations")
router = APIRouter(tags=["escalations"])


@router.get("/api/escalations/active")
async def active_escalations(_user: str = Depends(get_current_user)):
    from ..app import app_state
    escalation_mgr = app_state.get("escalation_mgr")
    return {"escalations": escalation_mgr.get_active_escalations()}


@router.get("/api/escalations/stats")
async def escalation_stats(_user: str = Depends(get_current_user)):
    from ..app import app_state
    escalation_mgr = app_state.get("escalation_mgr")
    return escalation_mgr.get_escalation_stats()


@router.post("/api/escalations/{key}/acknowledge")
async def acknowledge_escalation(key: str,
                                   _user: str = Depends(get_current_user)):
    from ..app import app_state
    escalation_mgr = app_state.get("escalation_mgr")
    ok = await escalation_mgr.acknowledge_issue(key)
    return {"status": "acknowledged" if ok else "not_found"}


@router.post("/api/escalations/{key}/resolve")
async def resolve_escalation(key: str,
                               _user: str = Depends(get_current_user)):
    from ..app import app_state
    escalation_mgr = app_state.get("escalation_mgr")
    ok = await escalation_mgr.resolve_issue(key)
    return {"status": "resolved" if ok else "not_found"}
