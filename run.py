"""Fleet Orchestrator entry point.

Usage:
    python run.py init                - Initialise database and config
    python run.py web                 - Start web dashboard (port 8089)
    python run.py cli                 - Launch interactive CLI
    python run.py chat                - Start AI chat interface
    python run.py mcp                 - Start MCP server (stdio)
    python run.py mcp-sse             - Start MCP server (SSE on port 9000)
    python run.py autonomous "goal"   - Run an autonomous agentic loop
"""

import asyncio
import logging
import logging.handlers
import os
import sys

from dotenv import load_dotenv

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env from project root before anything else
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def setup_logging() -> None:
    """Configure root logger with console + rotating file output."""
    log_dir = os.path.join(PROJECT_ROOT, "data", "logs")
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)

    # Rotating file handler — 10 MB, 5 backups
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "fleet.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def main():
    setup_logging()
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "init":
        asyncio.run(_init())
    elif command == "web":
        _run_web()
    elif command == "cli":
        _run_cli()
    elif command == "chat":
        asyncio.run(_run_chat())
    elif command == "autonomous":
        if len(sys.argv) < 3:
            print("Usage: python run.py autonomous \"<goal>\"")
            sys.exit(1)
        goal = " ".join(sys.argv[2:])
        asyncio.run(_run_autonomous(goal))
    elif command == "mcp":
        _run_mcp(transport="stdio")
    elif command == "mcp-sse":
        _run_mcp(transport="sse")
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


async def _init():
    """Initialise database and verify config."""
    from core.database import Database
    import yaml

    config_path = os.path.join(PROJECT_ROOT, "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    db_path = config.get("database", {}).get("path", "data/fleet_orchestrator.db")
    db = Database(db_path)
    await db.connect()

    # Register agents from config
    agents = config.get("agents", {})
    for name, agent_conf in agents.items():
        if agent_conf.get("enabled", True):
            await db.upsert_agent(
                name=name,
                display_name=agent_conf.get("display_name", name),
                url=agent_conf.get("url", ""),
            )
            print(f"  Registered: {name} -> {agent_conf.get('url')}")

    await db.close()
    print(f"\nFleet Orchestrator initialised ({len(agents)} agents)")


def _run_web():
    """Start the FastAPI web dashboard."""
    import uvicorn
    import yaml

    config_path = os.path.join(PROJECT_ROOT, "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Uvicorn access log → rotating file
    log_dir = os.path.join(PROJECT_ROOT, "data", "logs")
    os.makedirs(log_dir, exist_ok=True)
    access_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "fleet_access.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    access_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    uv_access = logging.getLogger("uvicorn.access")
    uv_access.addHandler(access_handler)

    port = config.get("app", {}).get("port", 8089)

    # SSL support — detect certs from env vars
    ssl_cert = os.environ.get("VOLTSYS_SSL_CERT")
    ssl_key = os.environ.get("VOLTSYS_SSL_KEY")
    ssl_kwargs = {}
    if ssl_cert and ssl_key and os.path.isfile(ssl_cert) and os.path.isfile(ssl_key):
        ssl_kwargs["ssl_certfile"] = ssl_cert
        ssl_kwargs["ssl_keyfile"] = ssl_key
        logging.getLogger("fleet").info("HTTPS enabled with cert: %s", ssl_cert)

    uvicorn.run(
        "interfaces.web.app:create_app",
        host="0.0.0.0",
        port=port,
        factory=True,
        reload=False,
        **ssl_kwargs,
    )


def _run_cli():
    """Launch the Typer CLI."""
    from interfaces.cli.app import app
    sys.argv = [sys.argv[0]] + sys.argv[2:]  # Strip 'cli' so Typer sees subcommands
    app()


async def _run_chat():
    """Start interactive AI chat."""
    from interfaces.ai_agent.agent import FleetOrchestratorAgent
    agent = FleetOrchestratorAgent()
    await agent.initialize()
    try:
        await agent.chat_loop()
    finally:
        await agent.shutdown()


async def _run_autonomous(goal: str):
    """Run a headless autonomous agentic loop."""
    from interfaces.ai_agent.agent import FleetOrchestratorAgent
    from engines.agentic_loop_engine import AgenticLoopEngine

    # Initialize the same way as chat mode
    agent = FleetOrchestratorAgent()
    await agent.initialize()

    try:
        engine = AgenticLoopEngine(
            fleet_engine=agent.fleet_engine,
            health_engine=agent.health_engine,
            orchestration_engine=agent.orchestration_engine,
            workflow_engine=agent.workflow_engine,
            briefing_engine=agent.briefing_engine,
            alert_engine=agent.alert_engine,
            escalation_mgr=agent.escalation_mgr,
            policy_engine=agent.policy_engine,
            fleet_monitor=agent.fleet_monitor,
            scheduler_engine=agent.scheduler_engine,
            db=agent.db,
            config=agent.config,
        )

        print(f"\nStarting autonomous agentic loop...")
        print(f"Goal: {goal}")
        print("=" * 60)

        session = await engine.run(goal=goal)

        print("\n" + "=" * 60)
        print(f"Status:     {session.status.value}")
        print(f"Iterations: {session.iterations}")
        print(f"Tokens:     {session.total_input_tokens} in / {session.total_output_tokens} out")
        print(f"Tool calls: {len(session.tool_calls)}")
        if session.error:
            print(f"Error:      {session.error}")
        print("-" * 60)
        print(f"Result:\n{session.final_answer}")
    finally:
        await agent.shutdown()


def _run_mcp(transport: str = "stdio"):
    """Start the MCP server."""
    from mcp.server import run_server
    run_server(transport=transport)


if __name__ == "__main__":
    main()
