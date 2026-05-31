"""Remediation policy API routes."""

import logging
from fastapi import APIRouter, Depends
from ..auth import get_current_user

logger = logging.getLogger("fleet.web.policies")
router = APIRouter(tags=["policies"])


@router.get("/api/policies")
async def list_policies(_user: str = Depends(get_current_user)):
    from ..app import app_state
    policy_engine = app_state.get("policy_engine")
    return {"policies": policy_engine.list_policies()}


@router.get("/api/policies/stats")
async def policy_stats(_user: str = Depends(get_current_user)):
    from ..app import app_state
    policy_engine = app_state.get("policy_engine")
    return await policy_engine.get_policy_stats()


@router.get("/api/policies/history")
async def policy_history(policy_name: str = "", limit: int = 50,
                          _user: str = Depends(get_current_user)):
    from ..app import app_state
    policy_engine = app_state.get("policy_engine")
    return {"history": await policy_engine.get_policy_history(policy_name, limit)}


@router.get("/api/policies/approvals")
async def pending_approvals(_user: str = Depends(get_current_user)):
    from ..app import app_state
    policy_engine = app_state.get("policy_engine")
    return {"approvals": await policy_engine.get_pending_approvals()}


@router.post("/api/policies/approvals/{approval_id}/approve")
async def approve_execution(approval_id: str,
                              _user: str = Depends(get_current_user)):
    from ..app import app_state
    policy_engine = app_state.get("policy_engine")
    ok = await policy_engine.approve_execution(approval_id)
    return {"status": "approved" if ok else "not_found"}


@router.get("/api/policies/{name}")
async def get_policy(name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state
    policy_engine = app_state.get("policy_engine")
    policy = policy_engine.get_policy(name)
    if not policy:
        return {"error": f"Policy not found: {name}"}
    return policy


@router.post("/api/policies/{name}/enable")
async def enable_policy(name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state
    policy_engine = app_state.get("policy_engine")
    ok = await policy_engine.enable_policy(name)
    return {"status": "enabled" if ok else "not_found"}


@router.post("/api/policies/{name}/disable")
async def disable_policy(name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state
    policy_engine = app_state.get("policy_engine")
    ok = await policy_engine.disable_policy(name)
    return {"status": "disabled" if ok else "not_found"}


@router.get("/api/fleet-events")
async def fleet_events(event_type: str = "", limit: int = 50,
                        _user: str = Depends(get_current_user)):
    from ..app import app_state
    fleet_monitor = app_state.get("fleet_monitor")
    return {"events": await fleet_monitor.get_fleet_events(
        event_type or None, limit)}
