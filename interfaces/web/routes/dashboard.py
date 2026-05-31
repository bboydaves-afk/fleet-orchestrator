"""Dashboard and authentication routes."""

import logging
import os
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel

from ..auth import create_access_token, DEFAULT_USERNAME, DEFAULT_PASSWORD

logger = logging.getLogger("fleet.web.dashboard")
router = APIRouter(tags=["dashboard"])

# In-memory login rate limiter: 5 attempts per IP per 5-minute window
_login_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = 300  # seconds


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/")
async def index():
    static_dir = Path(__file__).parent.parent / "static"
    return FileResponse(str(static_dir / "index.html"))


@router.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"

    # Rate limit check
    now = time.time()
    _login_attempts[client_ip] = [
        t for t in _login_attempts[client_ip] if now - t < _RATE_LIMIT_WINDOW
    ]
    if len(_login_attempts[client_ip]) >= _RATE_LIMIT_MAX:
        logger.warning("Rate limited login from %s", client_ip)
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in 5 minutes.")

    _login_attempts[client_ip].append(now)

    if req.username != DEFAULT_USERNAME or req.password != DEFAULT_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(req.username)
    return {"token": token, "username": req.username, "token_type": "bearer"}


@router.get("/api/branding")
async def get_branding():
    return {
        "company_name": os.environ.get("COMPANY_NAME", "Fleet Orchestrator"),
        "logo_url": os.environ.get("LOGO_URL", ""),
        "accent_color": os.environ.get("ACCENT_COLOR", "#6366f1"),
    }


@router.get("/api/dashboard/stats")
async def dashboard_stats():
    from ..app import app_state

    fleet = app_state.get("fleet_engine")
    db = app_state.get("db")

    agents = fleet.get_agents() if fleet else []
    online = sum(1 for a in agents if a.status.value == "online")

    recent_execs = await db.get_recent_executions(10) if db else []

    # Autonomous stats
    active_alerts = await db.get_active_alerts() if db else []
    escalation_mgr = app_state.get("escalation_mgr")
    escalation_stats = escalation_mgr.get_escalation_stats() if escalation_mgr else {}
    policy_engine = app_state.get("policy_engine")
    policy_stats = policy_engine.get_policy_stats() if policy_engine else {}
    scheduler = app_state.get("scheduler_engine")
    jobs = scheduler.list_jobs() if scheduler else []

    return {
        "agents": {
            "total": len(agents),
            "online": online,
            "offline": len(agents) - online,
        },
        "tools": {
            "total": fleet.total_tool_count if fleet else 0,
        },
        "recent_executions": len(recent_execs),
        "autonomous": {
            "active_alerts": len(active_alerts),
            "active_escalations": escalation_stats.get("active_count", 0),
            "policies_enabled": policy_stats.get("enabled_count", 0),
            "policies_total": policy_stats.get("total_count", 0),
            "scheduled_jobs": len(jobs),
        },
    }
