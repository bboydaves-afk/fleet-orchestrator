"""Fleet Orchestrator CLI — Typer-based command-line interface."""

import asyncio
import json
import os
import sys

import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

app = typer.Typer(name="fleet", help="Fleet Orchestrator CLI")
console = Console()

# Sub-apps
fleet_app = typer.Typer(help="Fleet agent management")
tools_app = typer.Typer(help="Tool discovery and execution")
workflows_app = typer.Typer(help="Workflow management")
health_app = typer.Typer(help="Health monitoring")
scheduler_app = typer.Typer(help="Autonomous scheduler management")
alerts_app = typer.Typer(help="Alert channels and rules")
policies_app = typer.Typer(help="Auto-remediation policies")
escalations_app = typer.Typer(help="Escalation management")

app.add_typer(fleet_app, name="fleet")
app.add_typer(tools_app, name="tools")
app.add_typer(workflows_app, name="workflows")
app.add_typer(health_app, name="health")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(alerts_app, name="alerts")
app.add_typer(policies_app, name="policies")
app.add_typer(escalations_app, name="escalations")


def _load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


async def _get_fleet():
    from core.database import Database
    from engines.fleet_engine import FleetEngine

    config = _load_config()
    db_path = config.get("database", {}).get("path", "data/fleet_orchestrator.db")
    db = Database(db_path)
    await db.connect()

    fleet = FleetEngine(config)
    await fleet.initialize(db)
    return fleet, db


# ------------------------------------------------------------------
# Fleet commands
# ------------------------------------------------------------------

@fleet_app.command("list")
def fleet_list():
    """List all agents in the fleet."""
    async def _run():
        fleet, db = await _get_fleet()
        agents = fleet.get_agents()

        table = Table(title="Fleet Agents")
        table.add_column("Name", style="cyan")
        table.add_column("Display Name", style="green")
        table.add_column("URL")
        table.add_column("Status")
        table.add_column("Tools", justify="right")

        for a in agents:
            status_style = {"online": "green", "offline": "red", "degraded": "yellow"}.get(
                a.status.value, "dim"
            )
            table.add_row(
                a.name, a.display_name, a.url,
                f"[{status_style}]{a.status.value}[/]",
                str(a.tool_count),
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@fleet_app.command("connect")
def fleet_connect():
    """Authenticate and discover tools from all agents."""
    async def _run():
        fleet, db = await _get_fleet()
        with console.status("Connecting to fleet..."):
            results = await fleet.connect_all()

        for name, ok in results.items():
            icon = "[green]OK[/]" if ok else "[red]FAIL[/]"
            console.print(f"  {name}: {icon}")

        console.print(f"\n[bold]Fleet: {fleet.agent_count} agents, {fleet.total_tool_count} tools[/]")
        await db.close()

    asyncio.run(_run())


@fleet_app.command("status")
def fleet_status():
    """Show fleet health status."""
    async def _run():
        from engines.health_engine import HealthEngine

        fleet, db = await _get_fleet()
        await fleet.connect_all()
        health = HealthEngine(fleet, db)
        status = await health.get_fleet_status()

        summary = status["summary"]
        panel = Panel(
            f"[green]Online: {summary['online']}[/]  "
            f"[yellow]Degraded: {summary['degraded']}[/]  "
            f"[red]Offline: {summary['offline']}[/]  "
            f"Tools: {summary['total_tools']}",
            title="Fleet Status",
        )
        console.print(panel)

        for a in status["agents"]:
            style = {"online": "green", "offline": "red", "degraded": "yellow"}.get(a["status"], "dim")
            console.print(f"  [{style}]{a['status']:>8}[/]  {a['display_name']} ({a['tool_count']} tools)")

        await db.close()

    asyncio.run(_run())


# ------------------------------------------------------------------
# Tools commands
# ------------------------------------------------------------------

@tools_app.command("list")
def tools_list(agent: str = typer.Argument(..., help="Agent name")):
    """List tools for a specific agent."""
    async def _run():
        fleet, db = await _get_fleet()
        await fleet.authenticate(agent)
        tools = await fleet.discover_tools(agent)

        table = Table(title=f"Tools: {agent} ({len(tools)} total)")
        table.add_column("Name", style="cyan")
        table.add_column("Description", max_width=60)

        for t in tools:
            table.add_row(t.get("name", ""), t.get("description", "")[:60])

        console.print(table)
        await db.close()

    asyncio.run(_run())


@tools_app.command("search")
def tools_search(query: str = typer.Argument(..., help="Search query")):
    """Search tools across all agents."""
    async def _run():
        fleet, db = await _get_fleet()
        await fleet.connect_all()
        results = fleet.search_tools(query)

        table = Table(title=f"Search: '{query}' ({len(results)} matches)")
        table.add_column("Agent", style="cyan")
        table.add_column("Tool", style="green")
        table.add_column("Description", max_width=50)

        for t in results:
            table.add_row(
                t.get("_agent", ""), t.get("name", ""),
                t.get("description", "")[:50],
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@tools_app.command("exec")
def tools_exec(
    agent: str = typer.Argument(..., help="Agent name"),
    tool: str = typer.Argument(..., help="Tool name"),
    params: str = typer.Option("{}", "--params", "-p", help="JSON params"),
):
    """Execute a tool on an agent."""
    async def _run():
        fleet, db = await _get_fleet()
        await fleet.authenticate(agent)

        tool_params = json.loads(params)
        with console.status(f"Executing {agent}.{tool}..."):
            result = await fleet.execute_tool(agent, tool, tool_params)

        if result.status == "success":
            console.print(Panel(
                json.dumps(result.result, indent=2, default=str),
                title=f"[green]Success[/] ({result.duration_ms}ms)",
            ))
        else:
            console.print(f"[red]Error:[/] {result.error}")

        await db.close()

    asyncio.run(_run())


# ------------------------------------------------------------------
# Workflow commands
# ------------------------------------------------------------------

@workflows_app.command("list")
def workflows_list():
    """List available workflows."""
    async def _run():
        from engines.workflow_engine import WorkflowEngine

        fleet, db = await _get_fleet()
        wf = WorkflowEngine(fleet, db)
        await wf.initialize()

        workflows = wf.list_workflows()
        if not workflows:
            console.print("[dim]No workflows found in data/workflows/[/]")
            return

        table = Table(title="Workflows")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Steps", justify="right")
        table.add_column("Agents")

        for w in workflows:
            table.add_row(w["name"], w["description"], str(w["steps"]), ", ".join(w["agents"]))

        console.print(table)
        await db.close()

    asyncio.run(_run())


@workflows_app.command("run")
def workflows_run(name: str = typer.Argument(..., help="Workflow name")):
    """Execute a named workflow."""
    async def _run():
        from engines.workflow_engine import WorkflowEngine

        fleet, db = await _get_fleet()
        await fleet.connect_all()
        wf = WorkflowEngine(fleet, db)
        await wf.initialize()

        with console.status(f"Running workflow: {name}..."):
            result = await wf.execute_workflow(name)

        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(Panel(
                json.dumps(result, indent=2, default=str)[:2000],
                title=f"Workflow: {name} — {result.get('status', 'unknown')}",
            ))

        await db.close()

    asyncio.run(_run())


# ------------------------------------------------------------------
# Health commands
# ------------------------------------------------------------------

@health_app.command("check")
def health_check():
    """Run health checks on all agents."""
    async def _run():
        fleet, db = await _get_fleet()

        with console.status("Checking fleet health..."):
            statuses = await fleet.health_check_all()

        for name, status in statuses.items():
            style = {"online": "green", "offline": "red", "degraded": "yellow"}.get(status.value, "dim")
            agent = fleet.get_agent(name)
            display = agent.display_name if agent else name
            console.print(f"  [{style}]{status.value:>8}[/]  {display}")

        await db.close()

    asyncio.run(_run())


# ------------------------------------------------------------------
# Scheduler commands
# ------------------------------------------------------------------

@scheduler_app.command("list")
def scheduler_list():
    """List all scheduled jobs."""
    async def _run():
        from engines.scheduler_engine import SchedulerEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        scheduler = SchedulerEngine(
                fleet_engine=fleet, workflow_engine=None,
                briefing_engine=None, db=db, config=config,
            )
        await scheduler.initialize()

        jobs = scheduler.list_jobs()
        if not jobs:
            console.print("[dim]No scheduled jobs configured.[/]")
            await db.close()
            return

        table = Table(title="Scheduled Jobs")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Schedule")
        table.add_column("Enabled")
        table.add_column("Last Run")
        table.add_column("Next Run")

        for j in jobs:
            enabled_style = "green" if j.get("enabled") else "red"
            table.add_row(
                str(j.get("id", "")),
                j.get("name", ""),
                j.get("schedule", ""),
                f"[{enabled_style}]{j.get('enabled', False)}[/]",
                str(j.get("last_run", "never")),
                str(j.get("next_run", "—")),
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@scheduler_app.command("add")
def scheduler_add(
    name: str = typer.Argument(..., help="Job name"),
    schedule: str = typer.Argument(..., help="Cron expression (e.g. '*/5 * * * *')"),
    action: str = typer.Argument(..., help="Action to execute"),
    params: str = typer.Option("{}", "--params", "-p", help="JSON params for the action"),
):
    """Add a new scheduled job."""
    async def _run():
        from engines.scheduler_engine import SchedulerEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        scheduler = SchedulerEngine(
                fleet_engine=fleet, workflow_engine=None,
                briefing_engine=None, db=db, config=config,
            )
        await scheduler.initialize()

        action_params = json.loads(params)
        result = await scheduler.add_job(name, schedule, action, action_params)

        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(f"[green]Job added:[/] {result.get('id', '')} — {name}")

        await db.close()

    asyncio.run(_run())


@scheduler_app.command("enable")
def scheduler_enable(job_id: str = typer.Argument(..., help="Job ID")):
    """Enable a scheduled job."""
    async def _run():
        from engines.scheduler_engine import SchedulerEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        scheduler = SchedulerEngine(
                fleet_engine=fleet, workflow_engine=None,
                briefing_engine=None, db=db, config=config,
            )
        await scheduler.initialize()

        result = await scheduler.enable_job(job_id)
        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(f"[green]Enabled:[/] job {job_id}")

        await db.close()

    asyncio.run(_run())


@scheduler_app.command("disable")
def scheduler_disable(job_id: str = typer.Argument(..., help="Job ID")):
    """Disable a scheduled job."""
    async def _run():
        from engines.scheduler_engine import SchedulerEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        scheduler = SchedulerEngine(
                fleet_engine=fleet, workflow_engine=None,
                briefing_engine=None, db=db, config=config,
            )
        await scheduler.initialize()

        result = await scheduler.disable_job(job_id)
        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(f"[yellow]Disabled:[/] job {job_id}")

        await db.close()

    asyncio.run(_run())


@scheduler_app.command("trigger")
def scheduler_trigger(job_id: str = typer.Argument(..., help="Job ID")):
    """Manually trigger a scheduled job now."""
    async def _run():
        from engines.scheduler_engine import SchedulerEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        scheduler = SchedulerEngine(
                fleet_engine=fleet, workflow_engine=None,
                briefing_engine=None, db=db, config=config,
            )
        await scheduler.initialize()

        with console.status(f"Triggering job {job_id}..."):
            result = await scheduler.trigger_job(job_id)

        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(Panel(
                json.dumps(result, indent=2, default=str)[:2000],
                title=f"[green]Triggered:[/] job {job_id}",
            ))

        await db.close()

    asyncio.run(_run())


@scheduler_app.command("remove")
def scheduler_remove(job_id: str = typer.Argument(..., help="Job ID")):
    """Remove a scheduled job."""
    async def _run():
        from engines.scheduler_engine import SchedulerEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        scheduler = SchedulerEngine(
                fleet_engine=fleet, workflow_engine=None,
                briefing_engine=None, db=db, config=config,
            )
        await scheduler.initialize()

        result = await scheduler.remove_job(job_id)
        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(f"[red]Removed:[/] job {job_id}")

        await db.close()

    asyncio.run(_run())


# ------------------------------------------------------------------
# Alerts commands
# ------------------------------------------------------------------

@alerts_app.command("channels")
def alerts_channels():
    """List configured alert channels."""
    async def _run():
        fleet, db = await _get_fleet()
        channels = await db.get_alert_channels()

        if not channels:
            console.print("[dim]No alert channels configured.[/]")
            await db.close()
            return

        table = Table(title="Alert Channels")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Type")
        table.add_column("Enabled")
        table.add_column("Target")

        for ch in channels:
            enabled_style = "green" if ch.get("enabled") else "red"
            table.add_row(
                str(ch.get("id", "")),
                ch.get("name", ""),
                ch.get("type", ""),
                f"[{enabled_style}]{ch.get('enabled', False)}[/]",
                ch.get("target", ""),
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@alerts_app.command("rules")
def alerts_rules():
    """List alert rules."""
    async def _run():
        fleet, db = await _get_fleet()
        rules = await db.get_alert_rules()

        if not rules:
            console.print("[dim]No alert rules configured.[/]")
            await db.close()
            return

        table = Table(title="Alert Rules")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Condition")
        table.add_column("Severity")
        table.add_column("Enabled")

        for r in rules:
            severity_style = {"critical": "red", "warning": "yellow", "info": "blue"}.get(
                r.get("severity", ""), "dim"
            )
            enabled_style = "green" if r.get("enabled") else "red"
            table.add_row(
                str(r.get("id", "")),
                r.get("name", ""),
                r.get("condition", ""),
                f"[{severity_style}]{r.get('severity', '')}[/]",
                f"[{enabled_style}]{r.get('enabled', False)}[/]",
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@alerts_app.command("active")
def alerts_active():
    """Show currently active (unresolved) alerts."""
    async def _run():
        fleet, db = await _get_fleet()
        alerts = await db.get_active_alerts()

        if not alerts:
            console.print("[green]No active alerts.[/]")
            await db.close()
            return

        table = Table(title=f"Active Alerts ({len(alerts)})")
        table.add_column("ID", style="cyan")
        table.add_column("Severity")
        table.add_column("Source", style="green")
        table.add_column("Message")
        table.add_column("Triggered At")

        for a in alerts:
            severity_style = {"critical": "red", "warning": "yellow", "info": "blue"}.get(
                a.get("severity", ""), "dim"
            )
            table.add_row(
                str(a.get("id", "")),
                f"[{severity_style}]{a.get('severity', '')}[/]",
                a.get("source", ""),
                a.get("message", "")[:60],
                str(a.get("triggered_at", "")),
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@alerts_app.command("history")
def alerts_history(limit: int = typer.Option(20, "--limit", "-n", help="Max alerts to show")):
    """Show alert history."""
    async def _run():
        fleet, db = await _get_fleet()
        alerts = await db.get_alert_history(limit=limit)

        if not alerts:
            console.print("[dim]No alert history found.[/]")
            await db.close()
            return

        table = Table(title=f"Alert History (last {limit})")
        table.add_column("ID", style="cyan")
        table.add_column("Severity")
        table.add_column("Source")
        table.add_column("Message")
        table.add_column("Status")
        table.add_column("Triggered At")

        for a in alerts:
            severity_style = {"critical": "red", "warning": "yellow", "info": "blue"}.get(
                a.get("severity", ""), "dim"
            )
            status = a.get("status", "unknown")
            status_style = {"resolved": "green", "active": "red", "acknowledged": "yellow"}.get(
                status, "dim"
            )
            table.add_row(
                str(a.get("id", "")),
                f"[{severity_style}]{a.get('severity', '')}[/]",
                a.get("source", ""),
                a.get("message", "")[:50],
                f"[{status_style}]{status}[/]",
                str(a.get("triggered_at", "")),
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@alerts_app.command("resolve")
def alerts_resolve(alert_id: str = typer.Argument(..., help="Alert ID to resolve")):
    """Resolve an active alert."""
    async def _run():
        fleet, db = await _get_fleet()
        result = await db.resolve_alert(alert_id)

        if result:
            console.print(f"[green]Resolved:[/] alert {alert_id}")
        else:
            console.print(f"[red]Error:[/] could not resolve alert {alert_id}")

        await db.close()

    asyncio.run(_run())


# ------------------------------------------------------------------
# Policies commands
# ------------------------------------------------------------------

@policies_app.command("list")
def policies_list():
    """List all auto-remediation policies."""
    async def _run():
        from engines.policy_engine import PolicyEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        policy_engine = PolicyEngine(
                fleet_engine=fleet, workflow_engine=None,
                alert_engine=None, escalation_manager=None,
                db=db, config=config,
            )
        await policy_engine.initialize()

        policies = policy_engine.list_policies()
        if not policies:
            console.print("[dim]No policies configured.[/]")
            await db.close()
            return

        table = Table(title="Auto-Remediation Policies")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Trigger")
        table.add_column("Enabled")
        table.add_column("Cooldown")
        table.add_column("Approval")

        for p in policies:
            enabled_style = "green" if p.get("enabled") else "red"
            approval = "required" if p.get("requires_approval") else "auto"
            approval_style = "yellow" if p.get("requires_approval") else "green"
            table.add_row(
                str(p.get("id", "")),
                p.get("name", ""),
                p.get("trigger", ""),
                f"[{enabled_style}]{p.get('enabled', False)}[/]",
                str(p.get("cooldown", "—")),
                f"[{approval_style}]{approval}[/]",
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@policies_app.command("get")
def policies_get(policy_id: str = typer.Argument(..., help="Policy ID")):
    """Show details for a specific policy."""
    async def _run():
        from engines.policy_engine import PolicyEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        policy_engine = PolicyEngine(
                fleet_engine=fleet, workflow_engine=None,
                alert_engine=None, escalation_manager=None,
                db=db, config=config,
            )
        await policy_engine.initialize()

        policy = policy_engine.get_policy(policy_id)
        if not policy:
            console.print(f"[red]Policy not found:[/] {policy_id}")
            await db.close()
            return

        console.print(Panel(
            json.dumps(policy, indent=2, default=str),
            title=f"Policy: {policy.get('name', policy_id)}",
        ))
        await db.close()

    asyncio.run(_run())


@policies_app.command("enable")
def policies_enable(policy_id: str = typer.Argument(..., help="Policy ID")):
    """Enable an auto-remediation policy."""
    async def _run():
        from engines.policy_engine import PolicyEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        policy_engine = PolicyEngine(
                fleet_engine=fleet, workflow_engine=None,
                alert_engine=None, escalation_manager=None,
                db=db, config=config,
            )
        await policy_engine.initialize()

        result = await policy_engine.enable_policy(policy_id)
        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(f"[green]Enabled:[/] policy {policy_id}")

        await db.close()

    asyncio.run(_run())


@policies_app.command("disable")
def policies_disable(policy_id: str = typer.Argument(..., help="Policy ID")):
    """Disable an auto-remediation policy."""
    async def _run():
        from engines.policy_engine import PolicyEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        policy_engine = PolicyEngine(
                fleet_engine=fleet, workflow_engine=None,
                alert_engine=None, escalation_manager=None,
                db=db, config=config,
            )
        await policy_engine.initialize()

        result = await policy_engine.disable_policy(policy_id)
        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(f"[yellow]Disabled:[/] policy {policy_id}")

        await db.close()

    asyncio.run(_run())


@policies_app.command("history")
def policies_history(
    policy_id: str = typer.Option(None, "--policy", "-p", help="Filter by policy ID"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max entries to show"),
):
    """Show policy execution history."""
    async def _run():
        from engines.policy_engine import PolicyEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        policy_engine = PolicyEngine(
                fleet_engine=fleet, workflow_engine=None,
                alert_engine=None, escalation_manager=None,
                db=db, config=config,
            )
        await policy_engine.initialize()

        history = await policy_engine.get_execution_history(policy_id=policy_id, limit=limit)
        if not history:
            console.print("[dim]No policy execution history found.[/]")
            await db.close()
            return

        table = Table(title=f"Policy Execution History (last {limit})")
        table.add_column("Timestamp", style="cyan")
        table.add_column("Policy")
        table.add_column("Trigger")
        table.add_column("Result")
        table.add_column("Duration")

        for h in history:
            result_style = "green" if h.get("result") == "success" else "red"
            table.add_row(
                str(h.get("timestamp", "")),
                h.get("policy_name", ""),
                h.get("trigger", ""),
                f"[{result_style}]{h.get('result', '')}[/]",
                str(h.get("duration_ms", "—")) + "ms",
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@policies_app.command("stats")
def policies_stats():
    """Show policy execution statistics."""
    async def _run():
        from engines.policy_engine import PolicyEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        policy_engine = PolicyEngine(
                fleet_engine=fleet, workflow_engine=None,
                alert_engine=None, escalation_manager=None,
                db=db, config=config,
            )
        await policy_engine.initialize()

        stats = await policy_engine.get_stats()
        if not stats:
            console.print("[dim]No policy statistics available.[/]")
            await db.close()
            return

        panel_content = (
            f"Total executions:  {stats.get('total_executions', 0)}\n"
            f"[green]Successes:[/]       {stats.get('successes', 0)}\n"
            f"[red]Failures:[/]        {stats.get('failures', 0)}\n"
            f"Active policies:   {stats.get('active_policies', 0)}\n"
            f"Pending approvals: {stats.get('pending_approvals', 0)}"
        )
        console.print(Panel(panel_content, title="Policy Statistics"))
        await db.close()

    asyncio.run(_run())


@policies_app.command("approvals")
def policies_approvals():
    """List policy executions pending approval."""
    async def _run():
        from engines.policy_engine import PolicyEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        policy_engine = PolicyEngine(
                fleet_engine=fleet, workflow_engine=None,
                alert_engine=None, escalation_manager=None,
                db=db, config=config,
            )
        await policy_engine.initialize()

        pending = await policy_engine.get_pending_approvals()
        if not pending:
            console.print("[green]No pending approvals.[/]")
            await db.close()
            return

        table = Table(title=f"Pending Approvals ({len(pending)})")
        table.add_column("ID", style="cyan")
        table.add_column("Policy", style="green")
        table.add_column("Trigger")
        table.add_column("Requested At")
        table.add_column("Details")

        for p in pending:
            table.add_row(
                str(p.get("id", "")),
                p.get("policy_name", ""),
                p.get("trigger", ""),
                str(p.get("requested_at", "")),
                p.get("details", "")[:50],
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@policies_app.command("approve")
def policies_approve(approval_id: str = typer.Argument(..., help="Approval request ID")):
    """Approve a pending policy execution."""
    async def _run():
        from engines.policy_engine import PolicyEngine

        fleet, db = await _get_fleet()
        config = _load_config()
        policy_engine = PolicyEngine(
                fleet_engine=fleet, workflow_engine=None,
                alert_engine=None, escalation_manager=None,
                db=db, config=config,
            )
        await policy_engine.initialize()

        result = await policy_engine.approve_execution(approval_id)
        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(f"[green]Approved:[/] {approval_id} — execution will proceed")

        await db.close()

    asyncio.run(_run())


# ------------------------------------------------------------------
# Escalations commands
# ------------------------------------------------------------------

@escalations_app.command("active")
def escalations_active():
    """Show active escalations."""
    async def _run():
        from engines.escalation_manager import EscalationManager

        fleet, db = await _get_fleet()
        config = _load_config()
        escalation_mgr = EscalationManager(db=db, config=config)

        escalations = await escalation_mgr.get_active_escalations()
        if not escalations:
            console.print("[green]No active escalations.[/]")
            await db.close()
            return

        table = Table(title=f"Active Escalations ({len(escalations)})")
        table.add_column("ID", style="cyan")
        table.add_column("Level")
        table.add_column("Source", style="green")
        table.add_column("Description")
        table.add_column("Escalated At")

        level_styles = {"1": "blue", "2": "yellow", "3": "red", "4": "bold red"}
        for e in escalations:
            level = str(e.get("level", ""))
            style = level_styles.get(level, "dim")
            table.add_row(
                str(e.get("id", "")),
                f"[{style}]L{level}[/]",
                e.get("source", ""),
                e.get("description", "")[:50],
                str(e.get("escalated_at", "")),
            )

        console.print(table)
        await db.close()

    asyncio.run(_run())


@escalations_app.command("stats")
def escalations_stats():
    """Show escalation statistics."""
    async def _run():
        from engines.escalation_manager import EscalationManager

        fleet, db = await _get_fleet()
        config = _load_config()
        escalation_mgr = EscalationManager(db=db, config=config)

        stats = await escalation_mgr.get_stats()
        if not stats:
            console.print("[dim]No escalation statistics available.[/]")
            await db.close()
            return

        panel_content = (
            f"Active escalations: {stats.get('active', 0)}\n"
            f"[blue]Level 1 (auto-fix):[/]  {stats.get('level_1', 0)}\n"
            f"[yellow]Level 2 (notify):[/]   {stats.get('level_2', 0)}\n"
            f"[red]Level 3 (page):[/]      {stats.get('level_3', 0)}\n"
            f"[bold red]Level 4 (escalate):[/] {stats.get('level_4', 0)}\n"
            f"Resolved today:     {stats.get('resolved_today', 0)}\n"
            f"Avg resolution:     {stats.get('avg_resolution_time', '—')}"
        )
        console.print(Panel(panel_content, title="Escalation Statistics"))
        await db.close()

    asyncio.run(_run())


@escalations_app.command("acknowledge")
def escalations_acknowledge(escalation_id: str = typer.Argument(..., help="Escalation ID")):
    """Acknowledge an active escalation."""
    async def _run():
        from engines.escalation_manager import EscalationManager

        fleet, db = await _get_fleet()
        config = _load_config()
        escalation_mgr = EscalationManager(db=db, config=config)

        result = await escalation_mgr.acknowledge(escalation_id)
        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(f"[yellow]Acknowledged:[/] escalation {escalation_id}")

        await db.close()

    asyncio.run(_run())


@escalations_app.command("resolve")
def escalations_resolve(
    escalation_id: str = typer.Argument(..., help="Escalation ID"),
    note: str = typer.Option("", "--note", "-m", help="Resolution note"),
):
    """Resolve an active escalation."""
    async def _run():
        from engines.escalation_manager import EscalationManager

        fleet, db = await _get_fleet()
        config = _load_config()
        escalation_mgr = EscalationManager(db=db, config=config)

        result = await escalation_mgr.resolve(escalation_id, note=note)
        if "error" in result:
            console.print(f"[red]Error:[/] {result['error']}")
        else:
            console.print(f"[green]Resolved:[/] escalation {escalation_id}")

        await db.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
