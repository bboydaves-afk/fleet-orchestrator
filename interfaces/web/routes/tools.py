"""Tool discovery and execution API routes."""

import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user

logger = logging.getLogger("fleet.web.tools")
router = APIRouter(tags=["tools"])


class ToolExecRequest(BaseModel):
    agent: str
    tool: str
    params: dict[str, Any] = {}


@router.get("/api/tools/all")
async def list_all_tools(_user: str = Depends(get_current_user)):
    from ..app import app_state

    fleet = app_state.get("fleet_engine")
    tools = fleet.get_all_tools()
    return {
        "tools": [
            {"agent": t.get("_agent"), "name": t.get("name"),
             "description": t.get("description", "")}
            for t in tools
        ],
        "count": len(tools),
    }


@router.get("/api/agents/{agent_name}/tools")
async def list_agent_tools(agent_name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state

    fleet = app_state.get("fleet_engine")
    tools = fleet.get_agent_tools(agent_name)
    return {"agent": agent_name, "tools": tools, "count": len(tools)}


@router.get("/api/tools/search")
async def search_tools(q: str = "", _user: str = Depends(get_current_user)):
    from ..app import app_state

    fleet = app_state.get("fleet_engine")
    results = fleet.search_tools(q) if q else fleet.get_all_tools()
    return {
        "query": q,
        "results": [
            {"agent": t.get("_agent"), "name": t.get("name"),
             "description": t.get("description", "")}
            for t in results
        ],
        "count": len(results),
    }


@router.post("/api/tools/execute")
async def execute_tool(req: ToolExecRequest, _user: str = Depends(get_current_user)):
    from ..app import app_state

    fleet = app_state.get("fleet_engine")
    db = app_state.get("db")

    result = await fleet.execute_tool(req.agent, req.tool, req.params)
    return result.model_dump()
