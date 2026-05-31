"""AI tools for escalation management."""

ESCALATION_TOOLS = [
    {
        "name": "get_active_escalations",
        "description": "Get all active escalation issues with their current level.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_escalation_stats",
        "description": "Get escalation statistics (by level, by severity).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "acknowledge_escalation",
        "description": "Acknowledge an escalation issue (suppresses further escalation).",
        "input_schema": {
            "type": "object",
            "properties": {"issue_key": {"type": "string"}},
            "required": ["issue_key"],
        },
    },
    {
        "name": "resolve_escalation",
        "description": "Resolve an escalation issue.",
        "input_schema": {
            "type": "object",
            "properties": {"issue_key": {"type": "string"}},
            "required": ["issue_key"],
        },
    },
]
