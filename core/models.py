"""Pydantic models for the Fleet Orchestrator."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Agent models
# ------------------------------------------------------------------

class AgentStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class AgentConfig(BaseModel):
    """Agent entry from config.yaml."""
    url: str
    display_name: str
    enabled: bool = True
    auth: dict[str, str] = Field(default_factory=dict)


class AgentInfo(BaseModel):
    """Runtime agent state."""
    name: str
    display_name: str
    url: str
    status: AgentStatus = AgentStatus.UNKNOWN
    tool_count: int = 0
    last_health_check: Optional[str] = None
    last_seen: Optional[str] = None


# ------------------------------------------------------------------
# Tool models
# ------------------------------------------------------------------

class ToolSchema(BaseModel):
    """Individual tool definition from an agent."""
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolExecRequest(BaseModel):
    """Request to execute a tool on a specific agent."""
    agent_name: str
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)


class ToolExecResult(BaseModel):
    """Result from tool execution."""
    agent_name: str
    tool_name: str
    status: str = "success"
    result: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: Optional[int] = None


# ------------------------------------------------------------------
# Workflow models
# ------------------------------------------------------------------

class WorkflowStep(BaseModel):
    """Single step in a workflow."""
    name: str
    agent: str
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    on_error: str = "stop"  # stop | continue | skip


class WorkflowDefinition(BaseModel):
    """Complete workflow definition."""
    name: str
    description: str = ""
    steps: list[WorkflowStep]


class WorkflowExecStatus(BaseModel):
    """Workflow execution status."""
    workflow_name: str
    status: str = "pending"
    steps_completed: int = 0
    steps_total: int = 0
    results: dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------
# Directive models (Claude decomposition)
# ------------------------------------------------------------------

class TaskStep(BaseModel):
    """A single step in a decomposed task plan."""
    step_number: int
    agent: str
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    depends_on: list[int] = Field(default_factory=list)


class TaskPlan(BaseModel):
    """Decomposed multi-agent task plan."""
    directive: str
    steps: list[TaskStep]
    estimated_agents: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------
# Circuit breaker
# ------------------------------------------------------------------

class CircuitBreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker(BaseModel):
    """Simple circuit breaker state."""
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    failure_count: int = 0
    failure_threshold: int = 5
    last_failure: Optional[str] = None
    recovery_timeout_sec: int = 60

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure = datetime.utcnow().isoformat()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitBreakerState.CLOSED

    def should_allow(self) -> bool:
        if self.state == CircuitBreakerState.CLOSED:
            return True
        if self.state == CircuitBreakerState.OPEN and self.last_failure:
            from datetime import datetime as dt
            elapsed = (dt.utcnow() - dt.fromisoformat(self.last_failure)).total_seconds()
            if elapsed >= self.recovery_timeout_sec:
                self.state = CircuitBreakerState.HALF_OPEN
                return True
        return self.state == CircuitBreakerState.HALF_OPEN


# ------------------------------------------------------------------
# Scheduler models
# ------------------------------------------------------------------

class ScheduleTrigger(BaseModel):
    """Trigger definition for a scheduled job."""
    type: str = "cron"  # cron | interval
    cron: Optional[str] = None  # "0 8 * * *"
    interval_seconds: Optional[int] = None
    timezone: str = "UTC"


class ScheduledJob(BaseModel):
    """A scheduled job configuration."""
    name: str
    description: str = ""
    trigger: ScheduleTrigger = Field(default_factory=ScheduleTrigger)
    action_type: str = "workflow"  # workflow | briefing | health_report | tool_exec
    action_config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False
    last_run: Optional[str] = None
    next_run: Optional[str] = None


# ------------------------------------------------------------------
# Alert models
# ------------------------------------------------------------------

class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertChannelType(str, Enum):
    SLACK = "slack"
    TEAMS = "teams"
    EMAIL = "email"
    WEBHOOK = "webhook"


class AlertChannelConfig(BaseModel):
    """Notification channel configuration."""
    name: str
    channel_type: AlertChannelType
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class AlertRule(BaseModel):
    """Alert rule definition."""
    name: str
    description: str = ""
    condition: str  # agent_offline, agent_degraded, workflow_failed, health_check_slow
    threshold: Optional[float] = None
    duration_seconds: int = 0
    severity: AlertSeverity = AlertSeverity.WARNING
    channels: list[str] = Field(default_factory=list)
    enabled: bool = True


class Alert(BaseModel):
    """A fired alert instance."""
    id: int = 0
    rule_name: str
    agent_name: Optional[str] = None
    severity: str = "warning"
    message: str = ""
    status: str = "firing"  # firing | resolved
    fired_at: Optional[str] = None
    resolved_at: Optional[str] = None


# ------------------------------------------------------------------
# Policy models
# ------------------------------------------------------------------

class PolicyAction(BaseModel):
    """A single action in a policy action chain."""
    type: str  # workflow | tool_exec | alert | escalate
    workflow_name: Optional[str] = None
    agent_name: Optional[str] = None
    tool_name: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = None
    level: Optional[int] = None
    channels: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------
# Fleet event models
# ------------------------------------------------------------------

class FleetEventType(str, Enum):
    AGENT_ONLINE = "agent_online"
    AGENT_OFFLINE = "agent_offline"
    AGENT_DEGRADED = "agent_degraded"
    AGENT_RECOVERED = "agent_recovered"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_COMPLETED = "workflow_completed"
    HEALTH_CHECK_SLOW = "health_check_slow"


class FleetEvent(BaseModel):
    """An event emitted by the fleet monitoring layer."""
    event_type: FleetEventType
    agent_name: Optional[str] = None
    timestamp: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------
# Escalation models
# ------------------------------------------------------------------

class EscalationLevel(int, Enum):
    AUTO_FIX = 0
    NOTIFY = 1
    PAGE = 2
    ESCALATE = 3
