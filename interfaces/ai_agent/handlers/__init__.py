"""Aggregated tool handlers for the Fleet Orchestrator AI agent."""

from .fleet_handlers import (
    handle_list_fleet_agents,
    handle_get_agent_details,
    handle_get_agent_health,
    handle_get_fleet_status,
)
from .discovery_handlers import (
    handle_list_agent_tools,
    handle_search_fleet_tools,
    handle_refresh_tool_manifests,
)
from .execution_handlers import (
    handle_execute_agent_tool,
    handle_batch_execute_tools,
    handle_get_execution_log,
)
from .workflow_handlers import (
    handle_decompose_directive,
    handle_execute_task_plan,
    handle_list_workflows,
    handle_execute_workflow,
)
from .briefing_handlers import (
    handle_morning_briefing,
    handle_status_report,
    handle_search_audit_log,
)
from .scheduler_handlers import (
    handle_list_scheduled_jobs,
    handle_get_scheduled_job,
    handle_add_scheduled_job,
    handle_enable_scheduled_job,
    handle_disable_scheduled_job,
    handle_trigger_job_now,
    handle_remove_scheduled_job,
)
from .alert_handlers import (
    handle_list_alert_channels,
    handle_add_alert_channel,
    handle_test_alert_channel,
    handle_list_alert_rules,
    handle_add_alert_rule,
    handle_get_active_alerts,
    handle_get_alert_history,
    handle_resolve_alert,
    handle_send_notification,
)
from .policy_handlers import (
    handle_list_policies,
    handle_get_policy,
    handle_enable_policy,
    handle_disable_policy,
    handle_get_policy_history,
    handle_get_policy_stats,
    handle_approve_policy_execution,
    handle_get_pending_approvals,
    handle_get_fleet_events,
)
from .escalation_handlers import (
    handle_get_active_escalations,
    handle_get_escalation_stats,
    handle_acknowledge_escalation,
    handle_resolve_escalation,
)

TOOL_HANDLERS = {
    # Fleet
    "list_fleet_agents": handle_list_fleet_agents,
    "get_agent_details": handle_get_agent_details,
    "get_agent_health": handle_get_agent_health,
    "get_fleet_status": handle_get_fleet_status,
    # Discovery
    "list_agent_tools": handle_list_agent_tools,
    "search_fleet_tools": handle_search_fleet_tools,
    "refresh_tool_manifests": handle_refresh_tool_manifests,
    # Execution
    "execute_agent_tool": handle_execute_agent_tool,
    "batch_execute_tools": handle_batch_execute_tools,
    "get_execution_log": handle_get_execution_log,
    # Workflow
    "decompose_directive": handle_decompose_directive,
    "execute_task_plan": handle_execute_task_plan,
    "list_workflows": handle_list_workflows,
    "execute_workflow": handle_execute_workflow,
    # Briefing
    "morning_briefing": handle_morning_briefing,
    "status_report": handle_status_report,
    "search_audit_log": handle_search_audit_log,
    # Scheduler
    "list_scheduled_jobs": handle_list_scheduled_jobs,
    "get_scheduled_job": handle_get_scheduled_job,
    "add_scheduled_job": handle_add_scheduled_job,
    "enable_scheduled_job": handle_enable_scheduled_job,
    "disable_scheduled_job": handle_disable_scheduled_job,
    "trigger_job_now": handle_trigger_job_now,
    "remove_scheduled_job": handle_remove_scheduled_job,
    # Alerts
    "list_alert_channels": handle_list_alert_channels,
    "add_alert_channel": handle_add_alert_channel,
    "test_alert_channel": handle_test_alert_channel,
    "list_alert_rules": handle_list_alert_rules,
    "add_alert_rule": handle_add_alert_rule,
    "get_active_alerts": handle_get_active_alerts,
    "get_alert_history": handle_get_alert_history,
    "resolve_alert": handle_resolve_alert,
    "send_notification": handle_send_notification,
    # Policies
    "list_policies": handle_list_policies,
    "get_policy": handle_get_policy,
    "enable_policy": handle_enable_policy,
    "disable_policy": handle_disable_policy,
    "get_policy_history": handle_get_policy_history,
    "get_policy_stats": handle_get_policy_stats,
    "approve_policy_execution": handle_approve_policy_execution,
    "get_pending_approvals": handle_get_pending_approvals,
    "get_fleet_events": handle_get_fleet_events,
    # Escalation
    "get_active_escalations": handle_get_active_escalations,
    "get_escalation_stats": handle_get_escalation_stats,
    "acknowledge_escalation": handle_acknowledge_escalation,
    "resolve_escalation": handle_resolve_escalation,
}
