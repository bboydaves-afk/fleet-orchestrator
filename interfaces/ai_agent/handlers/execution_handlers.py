"""Handlers for tool execution tools."""

import asyncio
import logging

logger = logging.getLogger("fleet.handlers.execution")


async def handle_execute_agent_tool(params, db, cred_mgr, config, **ctx):
    fleet = ctx.get("fleet_engine")
    agent_name = params.get("agent_name", "")
    tool_name = params.get("tool_name", "")
    tool_params = params.get("params", {})

    result = await fleet.execute_tool(agent_name, tool_name, tool_params)
    return result.model_dump()


async def handle_batch_execute_tools(params, db, cred_mgr, config, **ctx):
    fleet = ctx.get("fleet_engine")
    executions = params.get("executions", [])

    tasks = [
        fleet.execute_tool(
            e.get("agent_name", ""),
            e.get("tool_name", ""),
            e.get("params", {}),
        )
        for e in executions
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    return {
        "results": [
            r.model_dump() if hasattr(r, "model_dump") else {"error": str(r)}
            for r in results
        ],
        "count": len(results),
    }


async def handle_get_execution_log(params, db, cred_mgr, config, **ctx):
    limit = params.get("limit", 20)
    if db:
        execs = await db.get_recent_executions(limit)
        return {"executions": execs, "count": len(execs)}
    return {"executions": [], "count": 0}
