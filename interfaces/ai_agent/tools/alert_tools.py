"""AI tools for alert and notification management."""

ALERT_TOOLS = [
    {
        "name": "list_alert_channels",
        "description": "List all configured notification channels (Slack, Teams, Email, Webhook).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_alert_channel",
        "description": "Add a notification channel (slack, teams, email, or webhook).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Channel name"},
                "channel_type": {"type": "string", "enum": ["slack", "teams", "email", "webhook"]},
                "config": {"type": "object", "description": "Channel config e.g. {webhook_url: ...}"},
            },
            "required": ["name", "channel_type", "config"],
        },
    },
    {
        "name": "test_alert_channel",
        "description": "Send a test notification to a specific channel.",
        "input_schema": {
            "type": "object",
            "properties": {"channel_name": {"type": "string"}},
            "required": ["channel_name"],
        },
    },
    {
        "name": "list_alert_rules",
        "description": "List all alert rules.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_alert_rule",
        "description": "Add a new alert rule (e.g. alert when agent goes offline).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Rule name"},
                "condition": {"type": "string", "enum": ["agent_offline", "agent_degraded", "workflow_failed", "health_check_slow"]},
                "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                "channels": {"type": "array", "items": {"type": "string"}, "description": "Channel names to notify"},
                "duration_seconds": {"type": "integer", "default": 0},
                "description": {"type": "string"},
            },
            "required": ["name", "condition", "severity", "channels"],
        },
    },
    {
        "name": "get_active_alerts",
        "description": "Get all currently firing alerts.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_alert_history",
        "description": "Get alert history (fired and resolved).",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 50}},
        },
    },
    {
        "name": "resolve_alert",
        "description": "Manually resolve a firing alert by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"alert_id": {"type": "integer"}},
            "required": ["alert_id"],
        },
    },
    {
        "name": "send_notification",
        "description": "Send a custom notification message to specified channels.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channels": {"type": "array", "items": {"type": "string"}},
                "message": {"type": "string"},
                "severity": {"type": "string", "default": "info"},
            },
            "required": ["channels", "message"],
        },
    },
]
