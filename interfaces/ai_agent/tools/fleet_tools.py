"""Fleet management tools."""

FLEET_TOOLS = [
    {
        "name": "list_fleet_agents",
        "description": "List all agents in the fleet with their status and tool count.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_agent_details",
        "description": "Get detailed information about a specific agent including its tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Name of the agent (e.g. sysadmin_agent)"},
            },
            "required": ["agent_name"],
        },
    },
    {
        "name": "get_agent_health",
        "description": "Check the health status of a specific agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Name of the agent"},
            },
            "required": ["agent_name"],
        },
    },
    {
        "name": "get_fleet_status",
        "description": "Get comprehensive fleet status: online/offline agents, total tools, recent activity.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]
