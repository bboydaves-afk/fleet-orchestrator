"""MCP Server — Exposes fleet tools to Claude Code via the MCP protocol.

Supports two transports:
  - stdio (default): For local Claude Code on the same machine
  - sse: For remote Claude Code (e.g., NemoClaw sandbox)

Usage:
  claude mcp add fleet-orchestrator -- python fleet_orchestrator/mcp/server.py
  python fleet_orchestrator/mcp/server.py --transport sse --port 9000
"""

import asyncio
import json
import logging
import os
import sys

# Ensure project root on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP

from .tool_bridge import ToolBridge

logger = logging.getLogger("fleet.mcp")

mcp = FastMCP("fleet-orchestrator")
bridge = ToolBridge()
_initialized = False


async def _ensure_init():
    global _initialized
    if not _initialized:
        await bridge.initialize()
        await bridge.discover_all()
        _initialized = True


# ------------------------------------------------------------------
# Tier 1: Always-registered MCP tools (~15)
# ------------------------------------------------------------------

@mcp.tool()
async def list_fleet_agents() -> str:
    """List all agents in the fleet with their status and tool count."""
    await _ensure_init()
    agents = bridge.list_agents()
    return json.dumps(agents, indent=2)


@mcp.tool()
async def list_agent_tools(agent_name: str) -> str:
    """List all tools available on a specific agent.

    Args:
        agent_name: Name of the agent (e.g. sysadmin_agent, marketing_agent)
    """
    await _ensure_init()
    tools = await bridge.discover_tools(agent_name)
    result = [{"name": t.get("name"), "description": t.get("description", "")}
              for t in tools]
    return json.dumps(result, indent=2)


@mcp.tool()
async def search_fleet_tools(query: str) -> str:
    """Search for tools across all agents by name or description keyword.

    Args:
        query: Search query (e.g. 'backup', 'deploy', 'scan', 'publish')
    """
    await _ensure_init()
    results = await bridge.search_tools(query)
    return json.dumps(results, indent=2)


@mcp.tool()
async def execute_agent_tool(agent_name: str, tool_name: str, params: str = "{}") -> str:
    """Execute any tool on any agent in the fleet.

    Use list_agent_tools or search_fleet_tools first to discover available tools
    and their required parameters.

    Args:
        agent_name: Name of the agent (e.g. sysadmin_agent)
        tool_name: Name of the tool to execute (e.g. list_servers)
        params: JSON string of parameters to pass to the tool
    """
    await _ensure_init()
    try:
        parsed_params = json.loads(params)
    except json.JSONDecodeError:
        return json.dumps({"error": f"Invalid JSON params: {params}"})

    result = await bridge.execute(agent_name, tool_name, parsed_params)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def batch_execute_tools(executions: str) -> str:
    """Execute multiple tools across agents in parallel.

    Args:
        executions: JSON array of objects with agent_name, tool_name, and optional params.
                    Example: [{"agent_name":"sysadmin_agent","tool_name":"list_servers"}]
    """
    await _ensure_init()
    try:
        exec_list = json.loads(executions)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON"})

    tasks = [
        bridge.execute(
            e.get("agent_name", ""),
            e.get("tool_name", ""),
            e.get("params", {}),
        )
        for e in exec_list
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return json.dumps([
        r if isinstance(r, dict) else {"error": str(r)}
        for r in results
    ], indent=2, default=str)


@mcp.tool()
async def get_fleet_status() -> str:
    """Get comprehensive fleet status: which agents are reachable, how many tools each has."""
    await _ensure_init()
    agents = bridge.list_agents()
    total_tools = sum(a.get("tool_count", 0) for a in agents)
    authenticated = sum(1 for a in agents if a.get("authenticated"))
    return json.dumps({
        "total_agents": len(agents),
        "authenticated": authenticated,
        "total_tools": total_tools,
        "agents": agents,
    }, indent=2)


@mcp.tool()
async def refresh_fleet() -> str:
    """Re-authenticate with all agents and refresh tool manifests."""
    await _ensure_init()
    results = await bridge.discover_all()
    summary = {name: len(tools) for name, tools in results.items()}
    total = sum(summary.values())
    return json.dumps({
        "refreshed": summary,
        "total_tools": total,
    }, indent=2)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def run_server(transport: str = "stdio", port: int = 9000):
    """Start the MCP server."""
    if transport == "sse":
        mcp.run(transport="sse", port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fleet Orchestrator MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    run_server(transport=args.transport, port=args.port)
