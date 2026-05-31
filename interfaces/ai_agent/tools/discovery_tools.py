"""Tool discovery tools."""

DISCOVERY_TOOLS = [
    {
        "name": "list_agent_tools",
        "description": "List all tools available on a specific agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Name of the agent"},
            },
            "required": ["agent_name"],
        },
    },
    {
        "name": "search_fleet_tools",
        "description": "Search for tools across all agents by name or description keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'backup', 'deploy', 'scan')"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "refresh_tool_manifests",
        "description": "Re-discover tools from all agents (refreshes the cached tool list).",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]
