"""Fleet Orchestrator AI Agent — Claude tool-use chat loop."""

import json
import logging
import os
import sys

import yaml

logger = logging.getLogger("fleet.agent")


class FleetOrchestratorAgent:
    """Interactive AI agent for managing the fleet via Claude tool-use."""

    def __init__(self):
        self.config = {}
        self.db = None
        self.fleet_engine = None
        self.health_engine = None
        self.orchestration_engine = None
        self.workflow_engine = None
        self.briefing_engine = None
        self.alert_engine = None
        self.escalation_mgr = None
        self.policy_engine = None
        self.fleet_monitor = None
        self.scheduler_engine = None

    async def initialize(self) -> None:
        """Set up all engines and connect to agents."""
        from core.database import Database
        from core.credentials import CredentialManager
        from engines.fleet_engine import FleetEngine
        from engines.health_engine import HealthEngine
        from engines.orchestration_engine import OrchestrationEngine
        from engines.workflow_engine import WorkflowEngine
        from engines.briefing_engine import BriefingEngine
        from engines.alert_engine import AlertEngine
        from engines.escalation_manager import EscalationManager
        from engines.fleet_monitoring_engine import FleetMonitoringEngine
        from engines.policy_engine import PolicyEngine
        from engines.scheduler_engine import SchedulerEngine

        # Load config
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml")
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        # Database
        db_path = self.config.get("database", {}).get("path", "data/fleet_orchestrator.db")
        self.db = Database(db_path)
        await self.db.connect()

        # Fleet engine
        self.fleet_engine = FleetEngine(self.config)
        await self.fleet_engine.initialize(self.db)

        # Connect to all agents
        print("Connecting to fleet agents...")
        results = await self.fleet_engine.connect_all()
        for name, ok in results.items():
            status = "connected" if ok else "failed"
            print(f"  {name}: {status}")

        # Core engines
        self.health_engine = HealthEngine(self.fleet_engine, self.db)
        self.orchestration_engine = OrchestrationEngine(self.fleet_engine, self.db, self.config)
        self.workflow_engine = WorkflowEngine(self.fleet_engine, self.db)
        await self.workflow_engine.initialize()
        self.briefing_engine = BriefingEngine(
            self.fleet_engine, self.health_engine, self.db, self.config
        )

        # Autonomous operations layer
        auto_config = self.config.get("autonomous", {})

        self.alert_engine = AlertEngine(self.db)
        await self.alert_engine.initialize()
        await self.alert_engine.auto_configure_from_config(self.config)

        self.escalation_mgr = EscalationManager(db=self.db, config=self.config)

        self.policy_engine = PolicyEngine(
            fleet_engine=self.fleet_engine,
            workflow_engine=self.workflow_engine,
            alert_engine=self.alert_engine,
            escalation_manager=self.escalation_mgr,
            db=self.db,
            config=self.config,
        )
        await self.policy_engine.start()

        if auto_config.get("auto_enable_safe_policies", False):
            await self.policy_engine.auto_enable_safe_policies()

        self.fleet_monitor = FleetMonitoringEngine(self.fleet_engine, self.health_engine, self.db)
        self.fleet_monitor.register_policy_callback(self.policy_engine.on_fleet_event)
        self.fleet_monitor.register_alert_callback(self.alert_engine.evaluate_fleet_event)

        self.scheduler_engine = SchedulerEngine(
            workflow_engine=self.workflow_engine,
            briefing_engine=self.briefing_engine,
            fleet_engine=self.fleet_engine,
            db=self.db,
            config=self.config,
        )
        await self.scheduler_engine.initialize()
        await self.scheduler_engine.start()

        print(f"\nFleet Orchestrator ready: {self.fleet_engine.agent_count} agents, "
              f"{self.fleet_engine.total_tool_count} tools")
        print(f"Autonomous: {len(self.policy_engine._policies)} policies, "
              f"{len(self.alert_engine._channels)} channels, "
              f"{len(self.scheduler_engine.list_jobs())} scheduled jobs\n")

    async def shutdown(self) -> None:
        if self.scheduler_engine:
            await self.scheduler_engine.stop()
        if self.fleet_monitor:
            await self.fleet_monitor.stop_monitoring()
        if self.policy_engine:
            await self.policy_engine.stop()
        await self.fleet_engine.shutdown()
        await self.db.close()

    async def chat_loop(self) -> None:
        """Interactive chat loop with Claude."""
        import anthropic
        from .tools import TOOLS
        from .handlers import TOOL_HANDLERS
        from .safety import is_dangerous

        client = anthropic.Anthropic()
        model = self.config.get("ai_agent", {}).get("model", "claude-sonnet-4-5-20250929")
        max_tokens = self.config.get("ai_agent", {}).get("max_tokens", 4096)
        system_prompt = self.config.get("ai_agent", {}).get("system_prompt", "")

        # Build context
        ctx = {
            "fleet_engine": self.fleet_engine,
            "health_engine": self.health_engine,
            "orchestration_engine": self.orchestration_engine,
            "workflow_engine": self.workflow_engine,
            "briefing_engine": self.briefing_engine,
            "alert_engine": self.alert_engine,
            "escalation_mgr": self.escalation_mgr,
            "policy_engine": self.policy_engine,
            "fleet_monitor": self.fleet_monitor,
            "scheduler_engine": self.scheduler_engine,
        }

        tools_for_claude = [
            {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
            for t in TOOLS
        ]

        messages = []
        print("Fleet Orchestrator Chat (type 'quit' to exit)")
        print("=" * 50)

        while True:
            try:
                user_input = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if user_input.lower() in ("quit", "exit", "q"):
                break
            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            # Claude tool-use loop
            while True:
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    tools=tools_for_claude,
                    messages=messages,
                )

                # Process response
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                if response.stop_reason != "tool_use":
                    # Print text response
                    for block in assistant_content:
                        if hasattr(block, "text"):
                            print(f"\nAssistant: {block.text}")
                    break

                # Handle tool calls
                tool_results = []
                for block in assistant_content:
                    if block.type != "tool_use":
                        continue

                    tool_name = block.name
                    tool_input = block.input

                    # Safety check
                    if is_dangerous(tool_name):
                        print(f"\n[CONFIRM] Execute dangerous tool '{tool_name}'? (y/n): ", end="")
                        confirm = input().strip().lower()
                        if confirm != "y":
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"error": "User declined execution"}),
                            })
                            continue

                    handler = TOOL_HANDLERS.get(tool_name)
                    if handler:
                        try:
                            result = await handler(
                                tool_input, self.db, None, self.config, **ctx
                            )
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result, default=str),
                            })
                        except Exception as exc:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"error": str(exc)}),
                                "is_error": True,
                            })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({"error": f"Unknown tool: {tool_name}"}),
                            "is_error": True,
                        })

                messages.append({"role": "user", "content": tool_results})
