"""Workflow and orchestration tools."""

WORKFLOW_TOOLS = [
    {
        "name": "decompose_directive",
        "description": "Break down a high-level directive into a multi-agent task plan using AI. Example: 'Launch product next week'",
        "input_schema": {
            "type": "object",
            "properties": {
                "directive": {"type": "string", "description": "High-level directive to decompose"},
            },
            "required": ["directive"],
        },
    },
    {
        "name": "execute_task_plan",
        "description": "Execute a previously decomposed task plan (runs steps respecting dependencies).",
        "input_schema": {
            "type": "object",
            "properties": {
                "plan": {"type": "object", "description": "Task plan from decompose_directive"},
            },
            "required": ["plan"],
        },
    },
    {
        "name": "list_workflows",
        "description": "List all available pre-defined workflows.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "execute_workflow",
        "description": "Execute a named pre-defined workflow.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow_name": {"type": "string", "description": "Name of the workflow to execute"},
            },
            "required": ["workflow_name"],
        },
    },
]
