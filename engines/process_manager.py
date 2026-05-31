"""Process Manager — restart agents via PowerShell on Windows."""

import asyncio
import logging
import time
from pathlib import Path

logger = logging.getLogger("fleet.process_manager")

# Agent name → port mapping (matches start-voltsys.ps1 registry)
AGENT_PORTS = {
    "sysadmin_agent": 8081,
    "azure_architect_agent": 8082,
    "marketing_agent": 8083,
    "hacking_agent": 8084,
    "content_creator_agent": 8085,
    "youtube_growth_agent": 8086,
    "ftmo_manager": 8087,
    "network_agent": 8088,
    "fleet_orchestrator": 8089,
    "compliance_agent": 8091,
    "vcio_agent": 8092,
    "psa_agent": 8093,
    "endpoint_agent": 8094,
    "onboarding_agent": 8100,
    "m365_agent": 8096,
    "monitoring_agent": 8097,
    "helpdesk_agent": 8098,
    "backup_agent": 8099,
}

BASE_PATH = r"C:\Users\carin\OneDrive\Desktop"
SCRIPT_DIR = r"C:\Users\carin\OneDrive\Desktop\n8n-voltsys"


class ProcessManager:
    """Manages agent process restarts on Windows."""

    def __init__(self, db=None):
        self._db = db
        # Rate limit: track restart timestamps per agent
        self._restart_history: dict[str, list[float]] = {}
        self._max_restarts_per_hour = 3

    def _check_rate_limit(self, agent_name: str) -> bool:
        """Return True if restart is allowed (under rate limit)."""
        now = time.time()
        cutoff = now - 3600  # 1 hour window

        history = self._restart_history.get(agent_name, [])
        # Prune old entries
        history = [t for t in history if t > cutoff]
        self._restart_history[agent_name] = history

        return len(history) < self._max_restarts_per_hour

    def _record_restart(self, agent_name: str):
        """Record a restart timestamp."""
        if agent_name not in self._restart_history:
            self._restart_history[agent_name] = []
        self._restart_history[agent_name].append(time.time())

    async def restart_agent(self, agent_name: str) -> dict:
        """Restart an agent by name. Returns result dict."""
        port = AGENT_PORTS.get(agent_name)
        if not port:
            return {"success": False, "error": f"Unknown agent: {agent_name}"}

        if agent_name == "fleet_orchestrator":
            return {"success": False, "error": "Cannot restart self"}

        if not self._check_rate_limit(agent_name):
            return {
                "success": False,
                "error": f"Rate limit: {agent_name} restarted {self._max_restarts_per_hour} times in the last hour",
            }

        agent_dir = Path(BASE_PATH) / agent_name
        if not (agent_dir / "run.py").exists():
            return {"success": False, "error": f"Agent directory not found: {agent_dir}"}

        script = Path(SCRIPT_DIR) / "restart-agent.ps1"
        if not script.exists():
            return {"success": False, "error": f"Restart script not found: {script}"}

        logger.info("Restarting agent %s (port %d)", agent_name, port)

        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-ExecutionPolicy", "Bypass", "-File",
                str(script),
                "-AgentName", agent_name,
                "-Port", str(port),
                "-BasePath", BASE_PATH,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            output = stdout.decode("utf-8", errors="replace").strip()
            err_output = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0:
                self._record_restart(agent_name)

                # Audit log
                if self._db:
                    try:
                        await self._db.add_audit_entry(
                            action="agent_restart",
                            agent_name=agent_name,
                            details=f"Restarted via ProcessManager (port {port})",
                        )
                    except Exception:
                        pass

                logger.info("Agent %s restarted successfully", agent_name)
                return {
                    "success": True,
                    "agent": agent_name,
                    "port": port,
                    "output": output,
                }
            else:
                logger.error("Restart failed for %s: %s", agent_name, err_output or output)
                return {
                    "success": False,
                    "error": err_output or output or f"Exit code {proc.returncode}",
                }

        except asyncio.TimeoutError:
            logger.error("Restart timed out for %s", agent_name)
            return {"success": False, "error": "Restart script timed out (60s)"}
        except Exception as exc:
            logger.error("Restart error for %s: %s", agent_name, exc)
            return {"success": False, "error": str(exc)}

    def get_restart_history(self, agent_name: str = None) -> dict:
        """Get restart counts for the last hour."""
        now = time.time()
        cutoff = now - 3600

        if agent_name:
            history = self._restart_history.get(agent_name, [])
            recent = [t for t in history if t > cutoff]
            return {agent_name: len(recent)}

        result = {}
        for name, timestamps in self._restart_history.items():
            recent = [t for t in timestamps if t > cutoff]
            if recent:
                result[name] = len(recent)
        return result
