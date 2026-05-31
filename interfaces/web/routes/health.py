"""Health monitoring API routes."""

import logging
from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user

logger = logging.getLogger("fleet.web.health")
router = APIRouter(tags=["health"])


@router.get("/api/health")
async def fleet_health(_user: str = Depends(get_current_user)):
    from ..app import app_state

    health = app_state.get("health_engine")
    return await health.get_fleet_status()


@router.get("/api/health/{agent_name}")
async def agent_health(agent_name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state

    fleet = app_state.get("fleet_engine")
    status = await fleet.health_check(agent_name)
    return {"agent_name": agent_name, "status": status.value}


@router.get("/api/health/history/{agent_name}")
async def health_history(agent_name: str, limit: int = 50,
                         _user: str = Depends(get_current_user)):
    from ..app import app_state

    health = app_state.get("health_engine")
    history = await health.get_health_history(agent_name, limit)
    return {"agent_name": agent_name, "history": history}


@router.get("/api/executions")
async def execution_log(limit: int = 50, _user: str = Depends(get_current_user)):
    from ..app import app_state

    db = app_state.get("db")
    execs = await db.get_recent_executions(limit)
    return {"executions": execs, "count": len(execs)}


@router.get("/api/audit")
async def audit_log(limit: int = 100, _user: str = Depends(get_current_user)):
    from ..app import app_state

    db = app_state.get("db")
    entries = await db.get_audit_log(limit)
    return {"entries": entries, "count": len(entries)}


@router.get("/api/backups")
async def list_backups(_user: str = Depends(get_current_user)):
    from ..app import app_state

    backup = app_state.get("backup_engine")
    if not backup:
        return {"backups": [], "stats": {}}
    backups = await backup.list_backups()
    stats = await backup.get_backup_stats()
    return {"backups": backups, "stats": stats}


@router.post("/api/backups/create")
async def create_backup(_user: str = Depends(get_current_user)):
    from ..app import app_state

    backup = app_state.get("backup_engine")
    if not backup:
        raise HTTPException(500, "Backup engine not initialized")
    result = await backup.create_backup()
    if result["success"]:
        await backup.cleanup_old(keep=30)
    return result
