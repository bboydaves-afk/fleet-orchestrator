"""Handlers for fleet management tools."""

import logging

logger = logging.getLogger("fleet.handlers.fleet")


async def handle_list_fleet_agents(params, db, cred_mgr, config, **ctx):
    fleet = ctx.get("fleet_engine")
    agents = fleet.get_agents()
    return {
        "agents": [a.model_dump() for a in agents],
        "count": len(agents),
    }


async def handle_get_agent_details(params, db, cred_mgr, config, **ctx):
    fleet = ctx.get("fleet_engine")
    name = params.get("agent_name", "")
    agent = fleet.get_agent(name)
    if not agent:
        return {"error": f"Agent not found: {name}"}

    tools = fleet.get_agent_tools(name)
    return {
        "agent": agent.model_dump(),
        "tools": [{"name": t.get("name"), "description": t.get("description", "")} for t in tools],
        "tool_count": len(tools),
    }


async def handle_get_agent_health(params, db, cred_mgr, config, **ctx):
    fleet = ctx.get("fleet_engine")
    name = params.get("agent_name", "")
    status = await fleet.health_check(name)
    return {"agent_name": name, "status": status.value}


async def handle_get_fleet_status(params, db, cred_mgr, config, **ctx):
    health = ctx.get("health_engine")
    return await health.get_fleet_status()
