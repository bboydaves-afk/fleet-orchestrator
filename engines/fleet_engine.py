"""Fleet Engine — HTTP connection pool to all agents.

Handles authentication, tool discovery, tool execution, and health checking
for every agent in the fleet.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

import httpx

from core.models import (
    AgentConfig, AgentInfo, AgentStatus, CircuitBreaker,
    ToolExecResult, ToolSchema,
)

logger = logging.getLogger("fleet.engine")


class AgentConnection:
    """Per-agent connection state."""

    def __init__(self, name: str, config: AgentConfig):
        self.name = name
        self.config = config
        self.url = config.url.rstrip("/")
        self.display_name = config.display_name
        self.status: AgentStatus = AgentStatus.UNKNOWN
        self.jwt_token: Optional[str] = None
        self.tool_manifest: list[dict] = []
        self.circuit_breaker = CircuitBreaker()

    @property
    def info(self) -> AgentInfo:
        return AgentInfo(
            name=self.name,
            display_name=self.display_name,
            url=self.url,
            status=self.status,
            tool_count=len(self.tool_manifest),
        )


class FleetEngine:
    """Manages HTTP connections and tool execution across the fleet."""

    def __init__(self, config: dict):
        self._config = config
        self._connections: dict[str, AgentConnection] = {}
        self._http: Optional[httpx.AsyncClient] = None
        self._db = None

    async def initialize(self, db=None) -> None:
        """Load agent configs, create connection pool."""
        self._db = db
        # verify=False allows self-signed certs for localhost HTTPS
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            verify=False,
        )

        agents_conf = self._config.get("agents", {})
        for name, raw in agents_conf.items():
            if not raw.get("enabled", True):
                continue
            ac = AgentConfig(**raw)
            self._connections[name] = AgentConnection(name, ac)

        logger.info("Fleet engine initialised with %d agents", len(self._connections))

        # Register agents in DB
        if self._db:
            for conn in self._connections.values():
                await self._db.upsert_agent(
                    conn.name, conn.display_name, conn.url
                )

    async def shutdown(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self, agent_name: str) -> bool:
        """Authenticate with an agent and cache the JWT."""
        conn = self._connections.get(agent_name)
        if not conn:
            return False

        auth = conn.config.auth
        if not auth:
            return True  # No auth required

        # Prefer password from env var, fall back to config
        env_key = f"AGENT_{agent_name.upper()}_PASSWORD"
        password = os.environ.get(env_key) or auth.get("password", "admin")
        username = auth.get("username", "admin")

        try:
            # Try /api/auth/login first
            resp = await self._http.post(
                f"{conn.url}/api/auth/login",
                json={"username": username, "password": password},
            )
            if resp.status_code == 200:
                data = resp.json()
                conn.jwt_token = data.get("token") or data.get("access_token")
                logger.info("Authenticated with %s", agent_name)
                return True

            # Try /auth/login (hacking_agent style)
            resp = await self._http.post(
                f"{conn.url}/auth/login",
                json={"username": username, "password": password},
            )
            if resp.status_code == 200:
                data = resp.json()
                conn.jwt_token = data.get("token") or data.get("access_token")
                logger.info("Authenticated with %s (alt path)", agent_name)
                return True

            logger.warning("Auth failed for %s: %d", agent_name, resp.status_code)
            return False

        except Exception as exc:
            logger.warning("Auth error for %s: %s", agent_name, exc)
            return False

    def _auth_headers(self, agent_name: str) -> dict:
        conn = self._connections.get(agent_name)
        if conn and conn.jwt_token:
            return {"Authorization": f"Bearer {conn.jwt_token}"}
        return {}

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------

    async def discover_tools(self, agent_name: str) -> list[dict]:
        """Fetch tool manifest from an agent."""
        conn = self._connections.get(agent_name)
        if not conn:
            return []

        if not conn.circuit_breaker.should_allow():
            logger.warning("Circuit breaker open for %s", agent_name)
            return conn.tool_manifest

        try:
            resp = await self._http.get(
                f"{conn.url}/api/tools",
                headers=self._auth_headers(agent_name),
            )
            if resp.status_code == 401:
                # Token expired, re-authenticate and retry
                await self.authenticate(agent_name)
                resp = await self._http.get(
                    f"{conn.url}/api/tools",
                    headers=self._auth_headers(agent_name),
                )

            if resp.status_code == 200:
                data = resp.json()
                tools = data.get("tools", [])
                conn.tool_manifest = tools
                conn.circuit_breaker.record_success()

                if self._db:
                    await self._db.cache_tool_manifest(agent_name, tools)
                    await self._db.upsert_agent(
                        conn.name, conn.display_name, conn.url,
                        status="online", tool_count=len(tools),
                    )

                logger.info("Discovered %d tools from %s", len(tools), agent_name)
                return tools
            else:
                conn.circuit_breaker.record_failure()
                logger.warning("Tool discovery failed for %s: %d", agent_name, resp.status_code)
                return conn.tool_manifest

        except Exception as exc:
            conn.circuit_breaker.record_failure()
            logger.warning("Tool discovery error for %s: %s", agent_name, exc)
            return conn.tool_manifest

    async def discover_all_tools(self) -> dict[str, list[dict]]:
        """Discover tools from all agents concurrently."""
        tasks = {
            name: self.discover_tools(name)
            for name in self._connections
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return {
            name: (r if isinstance(r, list) else [])
            for name, r in zip(tasks.keys(), results)
        }

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def execute_tool(self, agent_name: str, tool_name: str,
                           params: dict = None) -> ToolExecResult:
        """Execute a tool on a specific agent."""
        conn = self._connections.get(agent_name)
        if not conn:
            return ToolExecResult(
                agent_name=agent_name, tool_name=tool_name,
                status="error", error=f"Unknown agent: {agent_name}",
            )

        if not conn.circuit_breaker.should_allow():
            return ToolExecResult(
                agent_name=agent_name, tool_name=tool_name,
                status="error", error="Circuit breaker open",
            )

        start = time.monotonic()
        try:
            resp = await self._http.post(
                f"{conn.url}/api/tools/execute",
                json={"tool_name": tool_name, "params": params or {}},
                headers=self._auth_headers(agent_name),
            )

            if resp.status_code == 401:
                await self.authenticate(agent_name)
                resp = await self._http.post(
                    f"{conn.url}/api/tools/execute",
                    json={"tool_name": tool_name, "params": params or {}},
                    headers=self._auth_headers(agent_name),
                )

            duration = int((time.monotonic() - start) * 1000)

            if resp.status_code == 200:
                result_data = resp.json()
                conn.circuit_breaker.record_success()

                if self._db:
                    await self._db.log_execution(
                        agent_name, tool_name, params or {},
                        result_data, "success", duration_ms=duration,
                    )
                    await self._db.audit(
                        "tool_executed", agent_name, tool_name,
                        details={"params": params, "duration_ms": duration},
                    )

                return ToolExecResult(
                    agent_name=agent_name, tool_name=tool_name,
                    status="success", result=result_data, duration_ms=duration,
                )
            else:
                error_msg = resp.text[:500]
                conn.circuit_breaker.record_failure()

                if self._db:
                    await self._db.log_execution(
                        agent_name, tool_name, params or {},
                        {}, "error", error=error_msg, duration_ms=duration,
                    )

                return ToolExecResult(
                    agent_name=agent_name, tool_name=tool_name,
                    status="error", error=error_msg, duration_ms=duration,
                )

        except Exception as exc:
            duration = int((time.monotonic() - start) * 1000)
            conn.circuit_breaker.record_failure()

            if self._db:
                await self._db.log_execution(
                    agent_name, tool_name, params or {},
                    {}, "error", error=str(exc), duration_ms=duration,
                )

            return ToolExecResult(
                agent_name=agent_name, tool_name=tool_name,
                status="error", error=str(exc), duration_ms=duration,
            )

    # ------------------------------------------------------------------
    # Health checking
    # ------------------------------------------------------------------

    async def health_check(self, agent_name: str) -> AgentStatus:
        """Check health of a single agent."""
        conn = self._connections.get(agent_name)
        if not conn:
            return AgentStatus.OFFLINE

        start = time.monotonic()
        try:
            # Try /api/tools as health indicator (authenticated)
            resp = await self._http.get(
                f"{conn.url}/api/tools",
                headers=self._auth_headers(agent_name),
                timeout=10.0,
            )
            duration = int((time.monotonic() - start) * 1000)

            if resp.status_code == 200:
                conn.status = AgentStatus.ONLINE
                conn.circuit_breaker.record_success()
            elif resp.status_code == 401:
                # Auth issue — attempt re-authentication
                if await self.authenticate(agent_name):
                    tools = await self.discover_tools(agent_name)
                    conn.status = AgentStatus.ONLINE
                    conn.circuit_breaker.record_success()
                else:
                    conn.status = AgentStatus.DEGRADED
            else:
                conn.status = AgentStatus.DEGRADED
                conn.circuit_breaker.record_failure()

        except Exception:
            duration = int((time.monotonic() - start) * 1000)
            conn.status = AgentStatus.OFFLINE
            conn.circuit_breaker.record_failure()

        if self._db:
            await self._db.update_agent_status(agent_name, conn.status.value)
            await self._db.log_health(agent_name, conn.status.value, duration)

        return conn.status

    async def health_check_all(self) -> dict[str, AgentStatus]:
        """Check health of all agents concurrently."""
        tasks = {
            name: self.health_check(name)
            for name in self._connections
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return {
            name: (r if isinstance(r, AgentStatus) else AgentStatus.OFFLINE)
            for name, r in zip(tasks.keys(), results)
        }

    # ------------------------------------------------------------------
    # Connect all (auth + discover)
    # ------------------------------------------------------------------

    async def connect_all(self) -> dict[str, bool]:
        """Authenticate and discover tools for all agents."""
        results = {}
        for name in self._connections:
            auth_ok = await self.authenticate(name)
            if auth_ok:
                tools = await self.discover_tools(name)
                results[name] = len(tools) > 0
            else:
                results[name] = False
        return results

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_agents(self) -> list[AgentInfo]:
        return [c.info for c in self._connections.values()]

    def get_agent(self, name: str) -> Optional[AgentInfo]:
        conn = self._connections.get(name)
        return conn.info if conn else None

    def get_all_tools(self) -> list[dict]:
        """Get all tools from all agents, namespaced."""
        all_tools = []
        for conn in self._connections.values():
            for tool in conn.tool_manifest:
                ns_tool = dict(tool)
                ns_tool["_agent"] = conn.name
                ns_tool["_agent_display"] = conn.display_name
                all_tools.append(ns_tool)
        return all_tools

    def get_agent_tools(self, agent_name: str) -> list[dict]:
        conn = self._connections.get(agent_name)
        return list(conn.tool_manifest) if conn else []

    def search_tools(self, query: str) -> list[dict]:
        """Search tools across all agents."""
        q = query.lower()
        results = []
        for conn in self._connections.values():
            for tool in conn.tool_manifest:
                if (q in tool.get("name", "").lower()
                        or q in tool.get("description", "").lower()):
                    t = dict(tool)
                    t["_agent"] = conn.name
                    t["_agent_display"] = conn.display_name
                    results.append(t)
        return results

    @property
    def agent_count(self) -> int:
        return len(self._connections)

    @property
    def total_tool_count(self) -> int:
        return sum(len(c.tool_manifest) for c in self._connections.values())
