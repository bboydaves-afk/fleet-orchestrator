"""Tool Bridge — HTTP proxy from MCP server to agent REST APIs.

Lightweight version of FleetEngine for the MCP server process.
Handles JWT caching and token refresh on 401.
"""

import json
import logging
import os
from typing import Any, Optional

import httpx
import yaml

logger = logging.getLogger("fleet.mcp.bridge")


class ToolBridge:
    """Proxies tool calls from MCP to agent HTTP APIs."""

    def __init__(self, config: dict = None):
        self._config = config or {}
        self._http: Optional[httpx.AsyncClient] = None
        self._tokens: dict[str, str] = {}  # agent_name -> JWT
        self._agent_urls: dict[str, str] = {}  # agent_name -> base URL
        self._agent_auth: dict[str, dict] = {}  # agent_name -> {username, password}
        self._tool_cache: dict[str, list[dict]] = {}  # agent_name -> tools

    async def initialize(self) -> None:
        """Load config and create HTTP client."""
        if not self._config:
            config_path = os.path.join(
                os.path.dirname(__file__), "..", "config.yaml"
            )
            with open(config_path, "r") as f:
                self._config = yaml.safe_load(f)

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

        agents = self._config.get("agents", {})
        for name, conf in agents.items():
            if not conf.get("enabled", True):
                continue
            self._agent_urls[name] = conf.get("url", "").rstrip("/")
            self._agent_auth[name] = conf.get("auth", {})

        logger.info("Tool bridge initialised: %d agents", len(self._agent_urls))

    async def shutdown(self) -> None:
        if self._http:
            await self._http.aclose()

    async def _authenticate(self, agent_name: str) -> bool:
        """Authenticate with an agent."""
        url = self._agent_urls.get(agent_name)
        auth = self._agent_auth.get(agent_name, {})
        if not url or not auth:
            return False

        try:
            # Try /api/auth/login
            resp = await self._http.post(
                f"{url}/api/auth/login",
                json={"username": auth.get("username", "admin"),
                      "password": auth.get("password", "admin")},
            )
            if resp.status_code == 200:
                data = resp.json()
                self._tokens[agent_name] = data.get("token") or data.get("access_token", "")
                return True

            # Try /auth/login
            resp = await self._http.post(
                f"{url}/auth/login",
                json={"username": auth.get("username", "admin"),
                      "password": auth.get("password", "admin")},
            )
            if resp.status_code == 200:
                data = resp.json()
                self._tokens[agent_name] = data.get("token") or data.get("access_token", "")
                return True

            return False
        except Exception as exc:
            logger.warning("Auth failed for %s: %s", agent_name, exc)
            return False

    def _headers(self, agent_name: str) -> dict:
        token = self._tokens.get(agent_name)
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def discover_tools(self, agent_name: str) -> list[dict]:
        """Get tools from an agent."""
        url = self._agent_urls.get(agent_name)
        if not url:
            return []

        try:
            resp = await self._http.get(
                f"{url}/api/tools",
                headers=self._headers(agent_name),
            )
            if resp.status_code == 401:
                await self._authenticate(agent_name)
                resp = await self._http.get(
                    f"{url}/api/tools",
                    headers=self._headers(agent_name),
                )

            if resp.status_code == 200:
                tools = resp.json().get("tools", [])
                self._tool_cache[agent_name] = tools
                return tools
        except Exception as exc:
            logger.warning("Tool discovery failed for %s: %s", agent_name, exc)
        return self._tool_cache.get(agent_name, [])

    async def discover_all(self) -> dict[str, list[dict]]:
        """Discover tools from all agents."""
        results = {}
        for name in self._agent_urls:
            await self._authenticate(name)
            results[name] = await self.discover_tools(name)
        return results

    async def execute(self, agent_name: str, tool_name: str,
                      params: dict = None) -> dict:
        """Execute a tool on an agent."""
        url = self._agent_urls.get(agent_name)
        if not url:
            return {"error": f"Unknown agent: {agent_name}"}

        try:
            resp = await self._http.post(
                f"{url}/api/tools/execute",
                json={"tool_name": tool_name, "params": params or {}},
                headers=self._headers(agent_name),
            )
            if resp.status_code == 401:
                await self._authenticate(agent_name)
                resp = await self._http.post(
                    f"{url}/api/tools/execute",
                    json={"tool_name": tool_name, "params": params or {}},
                    headers=self._headers(agent_name),
                )

            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as exc:
            return {"error": str(exc)}

    async def search_tools(self, query: str) -> list[dict]:
        """Search tools across all agents."""
        q = query.lower()
        results = []
        for agent_name, tools in self._tool_cache.items():
            for t in tools:
                if (q in t.get("name", "").lower()
                        or q in t.get("description", "").lower()):
                    results.append({
                        "agent": agent_name,
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                    })
        return results

    def list_agents(self) -> list[dict]:
        """List all configured agents."""
        return [
            {
                "name": name,
                "url": url,
                "authenticated": name in self._tokens,
                "tool_count": len(self._tool_cache.get(name, [])),
            }
            for name, url in self._agent_urls.items()
        ]
