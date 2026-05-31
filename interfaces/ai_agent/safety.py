"""Safety layer for fleet orchestrator tools.

Flags dangerous tools that require user confirmation before execution.
"""

# Tools that modify state on remote agents or autonomous systems
DANGEROUS_TOOLS = {
    "execute_agent_tool",
    "batch_execute_tools",
    "execute_task_plan",
    "execute_workflow",
    # Scheduler — can trigger workflows/tool executions automatically
    "add_scheduled_job",
    "enable_scheduled_job",
    "trigger_job_now",
    "remove_scheduled_job",
    # Policies — can trigger autonomous remediation
    "enable_policy",
    "approve_policy_execution",
    # Alerts — can send external notifications
    "add_alert_channel",
    "add_alert_rule",
    "send_notification",
}

# Tools that should show a warning
WARNING_TOOLS = {
    "decompose_directive",
    # These change autonomous behavior but are less destructive
    "disable_policy",
    "disable_scheduled_job",
    "resolve_alert",
    "resolve_escalation",
    "acknowledge_escalation",
}


def is_dangerous(tool_name: str) -> bool:
    return tool_name in DANGEROUS_TOOLS


def is_warning(tool_name: str) -> bool:
    return tool_name in WARNING_TOOLS
