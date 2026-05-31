"""WebSocket chat route for AI interaction."""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("fleet.web.chat")
router = APIRouter(tags=["chat"])


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    from ..app import app_state
    from interfaces.ai_agent.tools import TOOLS
    from interfaces.ai_agent.handlers import TOOL_HANDLERS
    from interfaces.ai_agent.safety import is_dangerous

    config = app_state.get("config", {})
    db = app_state.get("db")
    ctx = {
        "fleet_engine": app_state.get("fleet_engine"),
        "health_engine": app_state.get("health_engine"),
        "orchestration_engine": app_state.get("orchestration_engine"),
        "workflow_engine": app_state.get("workflow_engine"),
        "briefing_engine": app_state.get("briefing_engine"),
        "alert_engine": app_state.get("alert_engine"),
        "escalation_mgr": app_state.get("escalation_mgr"),
        "policy_engine": app_state.get("policy_engine"),
        "fleet_monitor": app_state.get("fleet_monitor"),
        "scheduler_engine": app_state.get("scheduler_engine"),
    }

    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception:
        await websocket.send_json({"type": "error", "content": "Anthropic client not available"})
        await websocket.close()
        return

    model = config.get("ai_agent", {}).get("model", "claude-sonnet-4-5-20250929")
    max_tokens = config.get("ai_agent", {}).get("max_tokens", 4096)
    system_prompt = config.get("ai_agent", {}).get("system_prompt", "")

    tools_for_claude = [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in TOOLS
    ]

    messages = []

    try:
        while True:
            data = await websocket.receive_json()
            user_msg = data.get("message", "")

            if not user_msg:
                continue

            messages.append({"role": "user", "content": user_msg})

            # Claude tool-use loop
            while True:
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    tools=tools_for_claude,
                    messages=messages,
                )

                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                if response.stop_reason != "tool_use":
                    for block in assistant_content:
                        if hasattr(block, "text"):
                            await websocket.send_json({
                                "type": "message",
                                "content": block.text,
                            })
                    break

                # Handle tool calls
                tool_results = []
                for block in assistant_content:
                    if block.type != "tool_use":
                        continue

                    await websocket.send_json({
                        "type": "tool_call",
                        "tool": block.name,
                        "input": block.input,
                    })

                    handler = TOOL_HANDLERS.get(block.name)
                    if handler:
                        try:
                            result = await handler(block.input, db, None, config, **ctx)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result, default=str),
                            })
                        except Exception as exc:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"error": str(exc)}),
                                "is_error": True,
                            })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({"error": f"Unknown tool: {block.name}"}),
                            "is_error": True,
                        })

                messages.append({"role": "user", "content": tool_results})

    except WebSocketDisconnect:
        logger.info("Chat WebSocket disconnected")
    except Exception as exc:
        logger.exception("Chat error: %s", exc)
        try:
            await websocket.send_json({"type": "error", "content": str(exc)})
        except Exception:
            pass
