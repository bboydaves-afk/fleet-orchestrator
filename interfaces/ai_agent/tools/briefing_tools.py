"""Briefing and reporting tools."""

BRIEFING_TOOLS = [
    {
        "name": "morning_briefing",
        "description": "Generate a comprehensive morning briefing covering fleet health, recent activity, and key metrics.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "status_report",
        "description": "Generate a quick fleet status report showing agent health and tool availability.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "search_audit_log",
        "description": "Search the fleet audit log for recent actions and events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of entries to return", "default": 50},
            },
        },
    },
]
