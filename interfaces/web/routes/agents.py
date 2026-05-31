"""Agent management API routes."""

import logging
from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user

logger = logging.getLogger("fleet.web.agents")
router = APIRouter(tags=["agents"])


@router.get("/api/agents")
async def list_agents(_user: str = Depends(get_current_user)):
    from ..app import app_state

    fleet = app_state.get("fleet_engine")
    agents = fleet.get_agents()
    return {
        "agents": [a.model_dump() for a in agents],
        "count": len(agents),
    }


@router.get("/api/agents/{agent_name}")
async def get_agent(agent_name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state

    fleet = app_state.get("fleet_engine")
    agent = fleet.get_agent(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_name}")

    tools = fleet.get_agent_tools(agent_name)
    return {
        "agent": agent.model_dump(),
        "tools": [{"name": t.get("name"), "description": t.get("description", "")} for t in tools],
    }


@router.post("/api/agents/{agent_name}/connect")
async def connect_agent(agent_name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state

    fleet = app_state.get("fleet_engine")
    auth_ok = await fleet.authenticate(agent_name)
    if auth_ok:
        tools = await fleet.discover_tools(agent_name)
        return {"status": "connected", "tools_discovered": len(tools)}
    return {"status": "failed", "tools_discovered": 0}


@router.post("/api/agents/connect-all")
async def connect_all(_user: str = Depends(get_current_user)):
    from ..app import app_state

    fleet = app_state.get("fleet_engine")
    results = await fleet.connect_all()
    return {
        "results": {k: "connected" if v else "failed" for k, v in results.items()},
        "total_tools": fleet.total_tool_count,
    }


@router.post("/api/agents/{agent_name}/restart")
async def restart_agent(agent_name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state

    pm = app_state.get("process_manager")
    if not pm:
        raise HTTPException(500, "Process manager not initialized")
    result = await pm.restart_agent(agent_name)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Restart failed"))
    return result


@router.post("/api/agents/{agent_name}/rotate-password")
async def rotate_password(agent_name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state

    cr = app_state.get("cred_rotation")
    if not cr:
        raise HTTPException(500, "Credential rotation not initialized")
    result = await cr.rotate_password(agent_name)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Rotation failed"))
    return result


@router.post("/api/agents/rotate-all-passwords")
async def rotate_all_passwords(_user: str = Depends(get_current_user)):
    from ..app import app_state

    cr = app_state.get("cred_rotation")
    if not cr:
        raise HTTPException(500, "Credential rotation not initialized")
    return await cr.rotate_all()


@router.get("/api/agents/password-ages")
async def password_ages(_user: str = Depends(get_current_user)):
    from ..app import app_state

    cr = app_state.get("cred_rotation")
    if not cr:
        raise HTTPException(500, "Credential rotation not initialized")
    return cr.get_password_ages()
