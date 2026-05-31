"""Handlers for tool discovery tools."""

import logging

logger = logging.getLogger("fleet.handlers.discovery")


async def handle_list_agent_tools(params, db, cred_mgr, config, **ctx):
    fleet = ctx.get("fleet_engine")
    name = params.get("agent_name", "")
    tools = fleet.get_agent_tools(name)
    if not tools:
        return {"error": f"No tools found for agent: {name}", "tools": [], "count": 0}
    return {
        "agent_name": name,
        "tools": [{"name": t.get("name"), "description": t.get("description", "")} for t in tools],
        "count": len(tools),
    }


async def handle_search_fleet_tools(params, db, cred_mgr, config, **ctx):
    fleet = ctx.get("fleet_engine")
    query = params.get("query", "")
    results = fleet.search_tools(query)
    return {
        "query": query,
        "results": [
            {
                "agent": t.get("_agent"),
                "agent_display": t.get("_agent_display"),
                "name": t.get("name"),
                "description": t.get("description", ""),
            }
            for t in results
        ],
        "count": len(results),
    }


async def handle_refresh_tool_manifests(params, db, cred_mgr, config, **ctx):
    fleet = ctx.get("fleet_engine")
    results = await fleet.discover_all_tools()
    summary = {
        name: len(tools) for name, tools in results.items()
    }
    return {"refreshed": summary, "total_tools": fleet.total_tool_count}
