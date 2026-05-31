"""Alert Engine -- notification channels and alert rule evaluation."""

import json
import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

import httpx

logger = logging.getLogger("fleet.alerts")


# ------------------------------------------------------------------
# Notification channel classes
# ------------------------------------------------------------------

class SlackChannel:
    """Send notifications to Slack via incoming webhook."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.webhook_url = config.get("webhook_url", "")

    async def send(self, message: str, severity: str = "info") -> bool:
        emoji = {"critical": ":red_circle:", "warning": ":warning:",
                 "info": ":information_source:"}.get(severity, ":bell:")
        payload = {"text": f"{emoji} *[{severity.upper()}]* {message}"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.webhook_url, json=payload)
                return resp.status_code == 200
        except Exception as exc:
            logger.error("Slack send failed (%s): %s", self.name, exc)
            return False


class TeamsChannel:
    """Send notifications to Microsoft Teams via webhook."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.webhook_url = config.get("webhook_url", "")

    async def send(self, message: str, severity: str = "info") -> bool:
        color = {"critical": "FF0000", "warning": "FFA500",
                 "info": "0078D4"}.get(severity, "808080")
        payload = {
            "@type": "MessageCard",
            "themeColor": color,
            "summary": f"Fleet Alert: {severity}",
            "sections": [{
                "activityTitle": f"Fleet Orchestrator — {severity.upper()}",
                "text": message,
            }],
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.webhook_url, json=payload)
                return resp.status_code == 200
        except Exception as exc:
            logger.error("Teams send failed (%s): %s", self.name, exc)
            return False


class EmailChannel:
    """Send notifications via SMTP email."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.smtp_host = config.get("smtp_host", "localhost")
        self.smtp_port = config.get("smtp_port", 587)
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.from_addr = config.get("from_addr", "fleet@voltsys.ai")
        self.to_addrs = config.get("to_addrs", [])

    async def send(self, message: str, severity: str = "info") -> bool:
        try:
            msg = MIMEText(message)
            msg["Subject"] = f"[Fleet {severity.upper()}] Alert Notification"
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)

            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg)
            return True
        except Exception as exc:
            logger.error("Email send failed (%s): %s", self.name, exc)
            return False

    def _send_smtp(self, msg: MIMEText) -> None:
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.username:
                server.starttls()
                server.login(self.username, self.password)
            server.sendmail(self.from_addr, self.to_addrs, msg.as_string())


class WebhookChannel:
    """Send notifications to a generic webhook endpoint."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.url = config.get("url", "")
        self.headers = config.get("headers", {})

    async def send(self, message: str, severity: str = "info") -> bool:
        payload = {
            "source": "fleet_orchestrator",
            "severity": severity,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    self.url, json=payload, headers=self.headers)
                return 200 <= resp.status_code < 300
        except Exception as exc:
            logger.error("Webhook send failed (%s): %s", self.name, exc)
            return False


CHANNEL_CLASSES = {
    "slack": SlackChannel,
    "teams": TeamsChannel,
    "email": EmailChannel,
    "webhook": WebhookChannel,
}


# ------------------------------------------------------------------
# Alert Engine
# ------------------------------------------------------------------

class AlertEngine:
    """Manages alert channels, rules, and notification dispatch."""

    def __init__(self, db=None, config: dict = None):
        self._db = db
        self._config = config or {}
        self._channels: dict[str, object] = {}
        self._rules: dict[str, dict] = {}
        self._active_alerts: dict[str, dict] = {}  # "rule:agent" -> alert row

    async def initialize(self) -> None:
        """Load channels and rules from DB."""
        if not self._db:
            return
        # Load channels
        rows = await self._db.get_alert_channels()
        for row in rows:
            if row.get("enabled"):
                cfg = json.loads(row.get("config", "{}"))
                ch_type = row["channel_type"]
                cls = CHANNEL_CLASSES.get(ch_type)
                if cls:
                    self._channels[row["name"]] = cls(row["name"], cfg)

        # Load rules
        rules = await self._db.get_alert_rules()
        for r in rules:
            self._rules[r["name"]] = r

        # Load active alerts
        active = await self._db.get_active_alerts()
        for a in active:
            key = f"{a['rule_name']}:{a.get('agent_name', '')}"
            self._active_alerts[key] = a

        logger.info("AlertEngine initialized: %d channels, %d rules, %d active alerts",
                     len(self._channels), len(self._rules), len(self._active_alerts))

    async def auto_configure_from_config(self, config: dict) -> None:
        """Register notification channels and default alert rules from config.yaml.

        Channel configs use `_env` suffix keys to pull values from environment
        variables. If the env var is not set, the channel is registered but will
        fail silently when sending (logged as warning on startup).
        """
        auto_cfg = config.get("autonomous", {})
        channels_cfg = auto_cfg.get("notification_channels", [])

        for ch in channels_cfg:
            name = ch["name"]
            ch_type = ch["channel_type"]
            if not ch.get("enabled", True):
                continue
            if name in self._channels:
                continue  # already loaded from DB

            # Resolve env-var references in config
            resolved = self._resolve_env_config(ch.get("config", {}))
            try:
                await self.register_channel(name, ch_type, resolved)
                # Check if it actually has a URL/host
                has_endpoint = any(
                    v for k, v in resolved.items()
                    if k in ("webhook_url", "url", "smtp_host") and v
                )
                if not has_endpoint:
                    logger.warning("Channel '%s' registered but no endpoint configured "
                                   "(set the env var to activate)", name)
            except Exception as exc:
                logger.warning("Failed to register channel '%s': %s", name, exc)

        # Add default alert rules if none exist
        if not self._rules:
            default_rules = [
                ("agent-offline-rule", "agent_offline", "critical", ["slack"]),
                ("agent-degraded-rule", "agent_degraded", "warning", ["slack"]),
                ("workflow-failed-rule", "workflow_failed", "warning", ["slack"]),
            ]
            for rule_name, condition, severity, channels in default_rules:
                await self.add_rule(
                    name=rule_name, condition=condition,
                    severity=severity, channels=channels,
                    description=f"Auto-generated: alert on {condition}",
                )
            logger.info("Added %d default alert rules", len(default_rules))

    @staticmethod
    def _resolve_env_config(cfg: dict) -> dict:
        """Resolve config values ending in `_env` to their env var values."""
        resolved = {}
        for key, value in cfg.items():
            if key.endswith("_env") and isinstance(value, str):
                real_key = key[:-4]  # strip "_env"
                resolved[real_key] = os.environ.get(value, "")
            else:
                resolved[key] = value
        return resolved

    async def register_channel(self, name: str, channel_type: str,
                                config: dict) -> None:
        """Register a notification channel."""
        cls = CHANNEL_CLASSES.get(channel_type)
        if not cls:
            raise ValueError(f"Unknown channel type: {channel_type}")
        self._channels[name] = cls(name, config)
        if self._db:
            await self._db.upsert_alert_channel(name, channel_type, config)
        logger.info("Registered alert channel: %s (%s)", name, channel_type)

    async def remove_channel(self, name: str) -> bool:
        """Remove a notification channel."""
        removed = self._channels.pop(name, None) is not None
        if self._db:
            await self._db.delete_alert_channel(name)
        return removed

    def list_channels(self) -> list[dict]:
        """List all registered channels."""
        return [
            {"name": name, "type": ch.__class__.__name__.replace("Channel", "").lower()}
            for name, ch in self._channels.items()
        ]

    async def add_rule(self, name: str, condition: str, severity: str = "warning",
                        channels: list = None, threshold: float = None,
                        duration_seconds: int = 0, description: str = "",
                        enabled: bool = True) -> None:
        """Add an alert rule."""
        rule = {
            "name": name, "description": description, "condition": condition,
            "threshold": threshold, "duration_seconds": duration_seconds,
            "severity": severity, "channels": json.dumps(channels or []),
            "enabled": int(enabled),
        }
        self._rules[name] = rule
        if self._db:
            await self._db.upsert_alert_rule(
                name, condition, severity, channels, threshold,
                duration_seconds, description, enabled)
        logger.info("Added alert rule: %s (condition=%s)", name, condition)

    async def remove_rule(self, name: str) -> bool:
        """Remove an alert rule."""
        removed = self._rules.pop(name, None) is not None
        if self._db:
            await self._db.delete_alert_rule(name)
        return removed

    def list_rules(self) -> list[dict]:
        """List all alert rules."""
        return list(self._rules.values())

    async def evaluate_fleet_event(self, event) -> list[dict]:
        """Evaluate a fleet event against all rules. Fire/resolve alerts as needed."""
        fired = []
        event_type = event.event_type if hasattr(event, "event_type") else event.get("event_type", "")
        agent_name = event.agent_name if hasattr(event, "agent_name") else event.get("agent_name", "")

        # Map event types to conditions
        condition_map = {
            "agent_offline": "agent_offline",
            "agent_degraded": "agent_degraded",
            "workflow_failed": "workflow_failed",
            "agent_recovered": None,  # resolves alerts
            "agent_online": None,
        }

        event_condition = condition_map.get(event_type)

        # Check if this is a recovery event -> resolve active alerts
        if event_type in ("agent_recovered", "agent_online"):
            for rule_name, rule in self._rules.items():
                key = f"{rule_name}:{agent_name}"
                if key in self._active_alerts:
                    await self._resolve_alert(rule_name, agent_name)
            return fired

        # Match rules
        for rule_name, rule in self._rules.items():
            if not rule.get("enabled"):
                continue
            if rule.get("condition") != event_condition:
                continue

            key = f"{rule_name}:{agent_name}"
            if key in self._active_alerts:
                continue  # already firing

            alert = await self.fire_alert(
                rule_name, agent_name, rule.get("severity", "warning"),
                f"Agent '{agent_name}' triggered rule '{rule_name}': {event_condition}")
            fired.append(alert)

        return fired

    async def fire_alert(self, rule_name: str, agent_name: str,
                          severity: str, message: str) -> dict:
        """Fire an alert and send notifications."""
        rule = self._rules.get(rule_name, {})
        channels_raw = rule.get("channels", "[]")
        if isinstance(channels_raw, str):
            channel_names = json.loads(channels_raw)
        else:
            channel_names = channels_raw

        # Send notifications
        await self.send_notification(channel_names, message, severity)

        # Persist
        alert_id = 0
        if self._db:
            alert_id = await self._db.insert_alert(
                rule_name, agent_name, severity, message, channel_names)

        alert = {
            "id": alert_id, "rule_name": rule_name, "agent_name": agent_name,
            "severity": severity, "message": message, "status": "firing",
            "fired_at": datetime.now(timezone.utc).isoformat(),
        }
        key = f"{rule_name}:{agent_name}"
        self._active_alerts[key] = alert

        logger.warning("ALERT FIRED: [%s] %s — %s", severity.upper(), rule_name, message)
        return alert

    async def _resolve_alert(self, rule_name: str, agent_name: str) -> None:
        """Resolve a firing alert."""
        key = f"{rule_name}:{agent_name}"
        alert = self._active_alerts.pop(key, None)
        if alert and self._db and alert.get("id"):
            await self._db.resolve_alert(alert["id"])
        logger.info("Alert resolved: %s for %s", rule_name, agent_name)

    async def resolve_alert_by_id(self, alert_id: int) -> bool:
        """Resolve an alert by its DB ID."""
        # Remove from in-memory
        to_remove = None
        for key, alert in self._active_alerts.items():
            if alert.get("id") == alert_id:
                to_remove = key
                break
        if to_remove:
            self._active_alerts.pop(to_remove, None)
        if self._db:
            await self._db.resolve_alert(alert_id)
        return True

    async def send_notification(self, channel_names: list[str],
                                 message: str, severity: str = "info") -> dict:
        """Send notification to specified channels."""
        results = {}
        for name in channel_names:
            ch = self._channels.get(name)
            if ch:
                ok = await ch.send(message, severity)
                results[name] = "sent" if ok else "failed"
            else:
                results[name] = "channel_not_found"
        return results

    async def test_channel(self, name: str) -> bool:
        """Send a test notification to a specific channel."""
        ch = self._channels.get(name)
        if not ch:
            return False
        return await ch.send(
            "Test notification from Fleet Orchestrator", "info")

    def get_active_alerts(self) -> list[dict]:
        """Get all currently firing alerts."""
        return list(self._active_alerts.values())

    async def get_alert_history(self, limit: int = 50) -> list[dict]:
        """Get alert history from DB."""
        if self._db:
            return await self._db.get_alert_history(limit)
        return []
