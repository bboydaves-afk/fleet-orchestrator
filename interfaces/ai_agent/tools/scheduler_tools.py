"""AI tools for scheduled job management."""

SCHEDULER_TOOLS = [
    {
        "name": "list_scheduled_jobs",
        "description": "List all scheduled jobs with their triggers and next run times.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_scheduled_job",
        "description": "Get details of a specific scheduled job.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string", "description": "Name of the scheduled job"},
            },
            "required": ["job_name"],
        },
    },
    {
        "name": "add_scheduled_job",
        "description": "Add a new scheduled job (cron or interval trigger).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique job name"},
                "description": {"type": "string", "description": "Job description"},
                "trigger_type": {"type": "string", "enum": ["cron", "interval"], "description": "Trigger type"},
                "cron": {"type": "string", "description": "Cron expression e.g. '0 8 * * 1-5'"},
                "interval_seconds": {"type": "integer", "description": "Interval in seconds"},
                "action_type": {"type": "string", "enum": ["workflow", "briefing", "health_report", "tool_exec"]},
                "action_config": {"type": "object", "description": "Action config e.g. {workflow_name: ...}"},
                "enabled": {"type": "boolean", "default": False},
            },
            "required": ["name", "trigger_type", "action_type"],
        },
    },
    {
        "name": "enable_scheduled_job",
        "description": "Enable a scheduled job so it runs on its trigger schedule.",
        "input_schema": {
            "type": "object",
            "properties": {"job_name": {"type": "string"}},
            "required": ["job_name"],
        },
    },
    {
        "name": "disable_scheduled_job",
        "description": "Disable a scheduled job (stops running).",
        "input_schema": {
            "type": "object",
            "properties": {"job_name": {"type": "string"}},
            "required": ["job_name"],
        },
    },
    {
        "name": "trigger_job_now",
        "description": "Manually trigger a scheduled job to run immediately.",
        "input_schema": {
            "type": "object",
            "properties": {"job_name": {"type": "string"}},
            "required": ["job_name"],
        },
    },
    {
        "name": "remove_scheduled_job",
        "description": "Remove a scheduled job permanently.",
        "input_schema": {
            "type": "object",
            "properties": {"job_name": {"type": "string"}},
            "required": ["job_name"],
        },
    },
]
