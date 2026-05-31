"""Slack slash command handler for Fleet Orchestrator.

Handles /fleet commands from Slack:
    /fleet status   - Fleet health summary
    /fleet agents   - List all agents with status
    /fleet alerts   - Active alerts
    /fleet tools <q>- Search tools
    /fleet run <goal> - Trigger agentic loop
    /fleet help     - Show available commands
"""

import asyncio
import hashlib
import hmac
import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("fleet.web.slack")
router = APIRouter(tags=["slack"])

SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")


# ------------------------------------------------------------------
# Signature verification
# ------------------------------------------------------------------

def _verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify request came from Slack using HMAC-SHA256."""
    if not SLACK_SIGNING_SECRET:
        logger.warning("SLACK_SIGNING_SECRET not configured")
        return False

    # Reject requests older than 5 minutes (replay protection)
    if abs(time.time() - int(timestamp)) > 300:
        return False

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


# ------------------------------------------------------------------
# Response formatters (Slack Block Kit)
# ------------------------------------------------------------------

def _status_blocks(fleet_engine, health_engine, alert_engine) -> list[dict]:
    """Build Block Kit blocks for /fleet status."""
    agents = fleet_engine.get_agents()
    online = sum(1 for a in agents if a.status.value == "online")
    total = len(agents)
    tools = fleet_engine.total_tool_count

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Fleet Status"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Agents:* {online}/{total} online"},
                {"type": "mrkdwn", "text": f"*Tools:* {tools:,}"},
            ]
        },
    ]

    # Agent status summary
    statuses = {}
    for a in agents:
        s = a.status.value
        statuses.setdefault(s, []).append(a.display_name or a.name)

    if statuses.get("offline"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Offline:* {', '.join(statuses['offline'])}"}
        })

    if statuses.get("degraded"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Degraded:* {', '.join(statuses['degraded'])}"}
        })

    return blocks


def _agents_blocks(fleet_engine) -> list[dict]:
    """Build Block Kit blocks for /fleet agents."""
    agents = fleet_engine.get_agents()
    status_emoji = {"online": ":large_green_circle:", "offline": ":red_circle:", "degraded": ":large_yellow_circle:", "unknown": ":white_circle:"}

    lines = []
    for a in sorted(agents, key=lambda x: x.name):
        emoji = status_emoji.get(a.status.value, ":white_circle:")
        name = a.display_name or a.name
        lines.append(f"{emoji} *{name}* — {a.tool_count} tools")

    return [
        {"type": "header", "text": {"type": "plain_text", "text": "Fleet Agents"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]


async def _alerts_blocks(alert_engine) -> list[dict]:
    """Build Block Kit blocks for /fleet alerts."""
    active = await alert_engine.get_active_alerts()

    if not active:
        return [
            {"type": "section", "text": {"type": "mrkdwn", "text": ":white_check_mark: No active alerts."}}
        ]

    sev_emoji = {"critical": ":rotating_light:", "warning": ":warning:", "info": ":information_source:"}
    lines = []
    for a in active[:10]:
        emoji = sev_emoji.get(a.get("severity", "info"), ":information_source:")
        lines.append(f"{emoji} *{a.get('title', 'Alert')}* — {a.get('message', '')[:80]}")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Active Alerts ({len(active)})"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]
    if len(active) > 10:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_...and {len(active) - 10} more_"}]
        })
    return blocks


def _tools_blocks(fleet_engine, query: str) -> list[dict]:
    """Build Block Kit blocks for /fleet tools <query>."""
    if not query:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": "Usage: `/fleet tools <search query>`"}}]

    results = fleet_engine.search_tools(query)[:15]
    if not results:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": f"No tools matching *{query}*"}}]

    lines = []
    for t in results:
        agent = t.get("_agent_display") or t.get("_agent", "?")
        name = t.get("name", "?")
        desc = (t.get("description") or "")[:60]
        lines.append(f"*{name}* ({agent}) — {desc}")

    return [
        {"type": "header", "text": {"type": "plain_text", "text": f"Tools matching '{query}' ({len(results)})"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]


def _help_blocks() -> list[dict]:
    """Build Block Kit blocks for /fleet help."""
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "Fleet Commands"}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "`/fleet status` — Fleet health overview\n"
                    "`/fleet agents` — List all agents with status\n"
                    "`/fleet alerts` — Active alerts\n"
                    "`/fleet tools <query>` — Search tools across agents\n"
                    "`/fleet run <goal>` — Run an AI task (e.g. `/fleet run check server health`)\n"
                    "`/fleet help` — This message"
                ),
            },
        },
    ]


# ------------------------------------------------------------------
# Async result poster
# ------------------------------------------------------------------

async def _post_agentic_result(response_url: str, session_id: str, engine):
    """Wait for agentic session to complete, then post result to Slack."""
    try:
        # Poll until complete (max 5 minutes)
        for _ in range(60):
            await asyncio.sleep(5)
            session = engine.get_session(session_id)
            if not session:
                break
            status = session.status if hasattr(session, "status") else session.get("status", "")
            if status in ("completed", "failed", "cancelled"):
                break

        # Build result message
        session = engine.get_session(session_id)
        if session:
            s = session.to_dict() if hasattr(session, "to_dict") else session
            status = s.get("status", "unknown")
            summary = s.get("summary") or s.get("result", {}).get("summary", "")
            tools_used = s.get("tools_called", []) or s.get("tool_calls", [])
            tool_count = len(tools_used) if isinstance(tools_used, list) else 0

            status_emoji = {"completed": ":white_check_mark:", "failed": ":x:", "cancelled": ":no_entry_sign:"}
            emoji = status_emoji.get(status, ":question:")

            text = f"{emoji} *Agentic Task {status.title()}*\n"
            if summary:
                text += f"\n{summary[:2000]}\n"
            if tool_count:
                text += f"\n_Used {tool_count} tool calls_"
        else:
            text = ":warning: Could not retrieve session result."

        async with httpx.AsyncClient() as client:
            await client.post(response_url, json={
                "response_type": "in_channel",
                "text": text,
            })

    except Exception as exc:
        logger.error("Failed to post agentic result to Slack: %s", exc)


# ------------------------------------------------------------------
# Slash command endpoint
# ------------------------------------------------------------------

@router.post("/api/slack/command")
async def slack_command(request: Request):
    """Handle Slack slash command: /fleet <subcommand>."""
    from ..app import app_state

    # Read raw body for signature verification
    body = await request.body()

    # Verify Slack signature
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not _verify_slack_signature(body, timestamp, signature):
        raise HTTPException(401, "Invalid Slack signature")

    # Parse form data (Slack sends application/x-www-form-urlencoded)
    from urllib.parse import parse_qs
    form = parse_qs(body.decode("utf-8"))

    command_text = (form.get("text", [""])[0]).strip()
    response_url = form.get("response_url", [""])[0]

    # Parse subcommand
    parts = command_text.split(None, 1)
    subcommand = parts[0].lower() if parts else "help"
    args = parts[1] if len(parts) > 1 else ""

    fleet_engine = app_state.get("fleet_engine")
    health_engine = app_state.get("health_engine")
    alert_engine = app_state.get("alert_engine")
    agentic_engine = app_state.get("agentic_loop_engine")

    # Route to handler
    if subcommand == "status":
        blocks = _status_blocks(fleet_engine, health_engine, alert_engine)
        return JSONResponse({"response_type": "in_channel", "blocks": blocks})

    elif subcommand == "agents":
        blocks = _agents_blocks(fleet_engine)
        return JSONResponse({"response_type": "in_channel", "blocks": blocks})

    elif subcommand == "alerts":
        blocks = await _alerts_blocks(alert_engine)
        return JSONResponse({"response_type": "in_channel", "blocks": blocks})

    elif subcommand == "tools":
        blocks = _tools_blocks(fleet_engine, args)
        return JSONResponse({"response_type": "in_channel", "blocks": blocks})

    elif subcommand == "run":
        if not args:
            return JSONResponse({
                "response_type": "ephemeral",
                "text": "Usage: `/fleet run <goal>` — e.g. `/fleet run check all server health`",
            })

        if not agentic_engine:
            return JSONResponse({
                "response_type": "ephemeral",
                "text": ":x: Agentic loop engine not available.",
            })

        # Start agentic loop in background
        session_id = await agentic_engine.run_background(
            goal=args,
            metadata={"trigger": "slack", "response_url": response_url},
        )

        # Post result back when done
        if response_url:
            asyncio.create_task(_post_agentic_result(response_url, session_id, agentic_engine))

        return JSONResponse({
            "response_type": "in_channel",
            "text": f":robot_face: Running: _{args}_\nSession `{session_id}` — results will be posted when complete.",
        })

    elif subcommand == "help":
        blocks = _help_blocks()
        return JSONResponse({"response_type": "ephemeral", "blocks": blocks})

    else:
        return JSONResponse({
            "response_type": "ephemeral",
            "text": f"Unknown command: `{subcommand}`. Type `/fleet help` for available commands.",
        })
