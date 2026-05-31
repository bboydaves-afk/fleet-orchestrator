"""Tool execution tools."""

EXECUTION_TOOLS = [
    {
        "name": "execute_agent_tool",
        "description": "Execute a specific tool on a specific agent. Use list_agent_tools first to discover available tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Name of the agent (e.g. sysadmin_agent)"},
                "tool_name": {"type": "string", "description": "Name of the tool to execute"},
                "params": {
                    "type": "object",
                    "description": "Parameters to pass to the tool (as a JSON object)",
                    "default": {},
                },
            },
            "required": ["agent_name", "tool_name"],
        },
    },
    {
        "name": "batch_execute_tools",
        "description": "Execute multiple tools across agents in parallel. Each item needs agent_name, tool_name, and optional params.",
        "input_schema": {
            "type": "object",
            "properties": {
                "executions": {
                    "type": "array",
                    "description": "List of tool executions",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent_name": {"type": "string"},
                            "tool_name": {"type": "string"},
                            "params": {"type": "object", "default": {}},
                        },
                        "required": ["agent_name", "tool_name"],
                    },
                },
            },
            "required": ["executions"],
        },
    },
    {
        "name": "get_execution_log",
        "description": "View recent tool execution history across the fleet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of recent executions to show", "default": 20},
            },
        },
    },
]
