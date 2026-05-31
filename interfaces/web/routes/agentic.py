"""Agentic Loop API routes — trigger and monitor autonomous AI agent sessions.

Endpoints:
    POST /api/agentic/run          - Start an agentic loop (synchronous, waits for result)
    POST /api/agentic/run/async    - Start an agentic loop in the background
    POST /api/agentic/webhook      - Inbound webhook trigger (for n8n, Zapier, etc.)
    GET  /api/agentic/sessions     - List all sessions
    GET  /api/agentic/sessions/:id - Get session details
    POST /api/agentic/sessions/:id/cancel - Cancel a running session
"""

import hmac
import hashlib
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import get_current_user

logger = logging.getLogger("fleet.web.agentic")
router = APIRouter(tags=["agentic"])


# ------------------------------------------------------------------
# Request/response models
# ------------------------------------------------------------------

class AgenticRunRequest(BaseModel):
    goal: str = Field(..., description="Natural language goal for the agent to accomplish")
    max_iterations: Optional[int] = Field(None, description="Max reasoning cycles (default: from config)")
    timeout_seconds: Optional[int] = Field(None, description="Hard timeout in seconds (default: from config)")
    model: Optional[str] = Field(None, description="Claude model override")
    callback_url: Optional[str] = Field(None, description="URL to POST results to when complete")
    metadata: Optional[dict] = Field(None, description="Arbitrary metadata to attach")


class WebhookTriggerRequest(BaseModel):
    goal: str = Field(..., description="Natural language goal")
    max_iterations: Optional[int] = None
    timeout_seconds: Optional[int] = None
    callback_url: Optional[str] = None
    metadata: Optional[dict] = None
    api_key: Optional[str] = Field(None, description="API key for webhook auth (alternative to header)")


# ------------------------------------------------------------------
# Authenticated endpoints
# ------------------------------------------------------------------

@router.post("/api/agentic/run")
async def run_agentic_sync(req: AgenticRunRequest, _user: str = Depends(get_current_user)):
    """Run an agentic loop synchronously — blocks until complete."""
    from ..app import app_state

    engine = app_state.get("agentic_loop_engine")
    if not engine:
        raise HTTPException(500, "Agentic loop engine not initialized")

    session = await engine.run(
        goal=req.goal,
        max_iterations=req.max_iterations,
        timeout_seconds=req.timeout_seconds,
        model=req.model,
        callback_url=req.callback_url,
        metadata=req.metadata,
    )
    return session.to_dict()


@router.post("/api/agentic/run/async")
async def run_agentic_async(req: AgenticRunRequest, _user: str = Depends(get_current_user)):
    """Start an agentic loop in the background. Returns session_id immediately."""
    from ..app import app_state

    engine = app_state.get("agentic_loop_engine")
    if not engine:
        raise HTTPException(500, "Agentic loop engine not initialized")

    session_id = await engine.run_background(
        goal=req.goal,
        max_iterations=req.max_iterations,
        timeout_seconds=req.timeout_seconds,
        model=req.model,
        callback_url=req.callback_url,
        metadata=req.metadata,
    )
    return {
        "session_id": session_id,
        "status": "running",
        "message": "Agentic loop started in background. Poll /api/agentic/sessions/{session_id} for status.",
    }


@router.get("/api/agentic/sessions")
async def list_sessions(
    status: Optional[str] = None,
    limit: int = 50,
    _user: str = Depends(get_current_user),
):
    """List agentic loop sessions."""
    from ..app import app_state

    db = app_state.get("db")
    engine = app_state.get("agentic_loop_engine")

    # Try in-memory first for running sessions, fall back to DB
    if engine:
        sessions = engine.list_sessions(limit=limit)
        if status:
            sessions = [s for s in sessions if s["status"] == status]
        if sessions:
            return {"sessions": sessions, "count": len(sessions)}

    # Fall back to DB for historical sessions
    if db:
        rows = await db.get_agentic_sessions(status=status, limit=limit)
        for row in rows:
            if isinstance(row.get("tool_calls"), str):
                row["tool_calls"] = json.loads(row["tool_calls"])
            if isinstance(row.get("metadata"), str):
                row["metadata"] = json.loads(row["metadata"])
        return {"sessions": rows, "count": len(rows)}

    return {"sessions": [], "count": 0}


@router.get("/api/agentic/sessions/{session_id}")
async def get_session(session_id: str, _user: str = Depends(get_current_user)):
    """Get details of a specific agentic session."""
    from ..app import app_state

    engine = app_state.get("agentic_loop_engine")
    db = app_state.get("db")

    # Check in-memory first
    if engine:
        session = engine.get_session(session_id)
        if session:
            return session.to_dict()

    # Fall back to DB
    if db:
        row = await db.get_agentic_session(session_id)
        if row:
            if isinstance(row.get("tool_calls"), str):
                row["tool_calls"] = json.loads(row["tool_calls"])
            if isinstance(row.get("metadata"), str):
                row["metadata"] = json.loads(row["metadata"])
            return row

    raise HTTPException(404, f"Session not found: {session_id}")


@router.post("/api/agentic/sessions/{session_id}/cancel")
async def cancel_session(session_id: str, _user: str = Depends(get_current_user)):
    """Cancel a running agentic session."""
    from ..app import app_state

    engine = app_state.get("agentic_loop_engine")
    if not engine:
        raise HTTPException(500, "Agentic loop engine not initialized")

    if engine.cancel_session(session_id):
        return {"status": "cancelling", "session_id": session_id}
    raise HTTPException(404, f"Session not found or already completed: {session_id}")


# ------------------------------------------------------------------
# Webhook endpoint (for n8n, Zapier, Make, external triggers)
# ------------------------------------------------------------------

def _verify_webhook_key(provided_key: str, config: dict) -> bool:
    """Verify the webhook API key."""
    import os
    expected = (
        config.get("agentic_loop", {}).get("webhook_api_key", "")
        or os.environ.get("AGENTIC_WEBHOOK_API_KEY", "")
    )
    if not expected:
        return False  # No key configured = deny
    if not provided_key:
        return False
    return hmac.compare_digest(provided_key, expected)


@router.post("/api/agentic/webhook")
async def webhook_trigger(req: WebhookTriggerRequest, request: Request):
    """Inbound webhook to trigger an agentic loop.

    Authentication: Pass API key via X-API-Key header or api_key field.
    This endpoint does NOT require JWT auth — it's designed for external
    system integration (n8n, Zapier, Make, custom webhooks).

    The loop runs in the background. If callback_url is provided,
    results will be POSTed there when complete.
    """
    from ..app import app_state

    config = app_state.get("config", {})

    # Authenticate via API key
    api_key = (
        request.headers.get("X-API-Key")
        or request.headers.get("x-api-key")
        or req.api_key
        or ""
    )
    if not _verify_webhook_key(api_key, config):
        raise HTTPException(401, "Invalid API key")

    engine = app_state.get("agentic_loop_engine")
    if not engine:
        raise HTTPException(500, "Agentic loop engine not initialized")

    # Add webhook source to metadata
    metadata = req.metadata or {}
    metadata["trigger"] = "webhook"
    metadata["source_ip"] = request.client.host if request.client else "unknown"

    session_id = await engine.run_background(
        goal=req.goal,
        max_iterations=req.max_iterations,
        timeout_seconds=req.timeout_seconds,
        callback_url=req.callback_url,
        metadata=metadata,
    )

    return {
        "session_id": session_id,
        "status": "running",
        "message": "Agentic loop triggered. Results will be POSTed to callback_url if provided.",
    }
