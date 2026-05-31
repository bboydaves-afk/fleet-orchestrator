"""Aggregated tool definitions for the Fleet Orchestrator AI agent."""

from .fleet_tools import FLEET_TOOLS
from .discovery_tools import DISCOVERY_TOOLS
from .execution_tools import EXECUTION_TOOLS
from .workflow_tools import WORKFLOW_TOOLS
from .briefing_tools import BRIEFING_TOOLS
from .scheduler_tools import SCHEDULER_TOOLS
from .alert_tools import ALERT_TOOLS
from .policy_tools import POLICY_TOOLS
from .escalation_tools import ESCALATION_TOOLS

TOOLS = (
    *FLEET_TOOLS,
    *DISCOVERY_TOOLS,
    *EXECUTION_TOOLS,
    *WORKFLOW_TOOLS,
    *BRIEFING_TOOLS,
    *SCHEDULER_TOOLS,
    *ALERT_TOOLS,
    *POLICY_TOOLS,
    *ESCALATION_TOOLS,
)
