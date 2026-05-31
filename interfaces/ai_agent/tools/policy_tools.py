"""AI tools for remediation policy management."""

POLICY_TOOLS = [
    {
        "name": "list_policies",
        "description": "List all fleet remediation policies with their enabled status.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_policy",
        "description": "Get details of a specific remediation policy.",
        "input_schema": {
            "type": "object",
            "properties": {"policy_name": {"type": "string"}},
            "required": ["policy_name"],
        },
    },
    {
        "name": "enable_policy",
        "description": "Enable a remediation policy (it will start auto-responding to fleet events).",
        "input_schema": {
            "type": "object",
            "properties": {"policy_name": {"type": "string"}},
            "required": ["policy_name"],
        },
    },
    {
        "name": "disable_policy",
        "description": "Disable a remediation policy.",
        "input_schema": {
            "type": "object",
            "properties": {"policy_name": {"type": "string"}},
            "required": ["policy_name"],
        },
    },
    {
        "name": "get_policy_history",
        "description": "Get execution history for remediation policies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "policy_name": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "get_policy_stats",
        "description": "Get aggregate policy statistics.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "approve_policy_execution",
        "description": "Approve a pending policy execution that requires manual approval.",
        "input_schema": {
            "type": "object",
            "properties": {"approval_id": {"type": "string"}},
            "required": ["approval_id"],
        },
    },
    {
        "name": "get_pending_approvals",
        "description": "List all pending policy execution approvals.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_fleet_events",
        "description": "Get recent fleet events (agent state changes, workflow results).",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
]
