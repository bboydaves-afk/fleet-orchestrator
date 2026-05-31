"""Workflow management API routes."""

import logging
from fastapi import APIRouter, Depends

from ..auth import get_current_user

logger = logging.getLogger("fleet.web.workflows")
router = APIRouter(tags=["workflows"])


@router.get("/api/workflows")
async def list_workflows(_user: str = Depends(get_current_user)):
    from ..app import app_state

    wf = app_state.get("workflow_engine")
    return {"workflows": wf.list_workflows()}


@router.post("/api/workflows/{name}/execute")
async def execute_workflow(name: str, _user: str = Depends(get_current_user)):
    from ..app import app_state

    wf = app_state.get("workflow_engine")
    return await wf.execute_workflow(name)


@router.get("/api/briefing")
async def morning_briefing(_user: str = Depends(get_current_user)):
    from ..app import app_state

    briefing = app_state.get("briefing_engine")
    return await briefing.morning_briefing()


@router.get("/api/status-report")
async def status_report(_user: str = Depends(get_current_user)):
    from ..app import app_state

    briefing = app_state.get("briefing_engine")
    return await briefing.status_report()
