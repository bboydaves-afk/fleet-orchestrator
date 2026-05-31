"""Async SQLite database for the Fleet Orchestrator."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger("fleet.database")


class Database:
    """Async SQLite wrapper with auto-schema migration."""

    def __init__(self, db_path: str = "data/fleet_orchestrator.db"):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()
        logger.info("Database connected: %s", self.db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database closed")

    async def _create_tables(self) -> None:
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                name TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                url TEXT NOT NULL,
                status TEXT DEFAULT 'unknown',
                tool_count INTEGER DEFAULT 0,
                last_health_check TEXT,
                last_seen TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS tool_manifests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL REFERENCES agents(name),
                tool_name TEXT NOT NULL,
                description TEXT DEFAULT '',
                input_schema TEXT DEFAULT '{}',
                cached_at TEXT DEFAULT (datetime('now')),
                UNIQUE(agent_name, tool_name)
            );

            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                params TEXT DEFAULT '{}',
                result TEXT DEFAULT '{}',
                status TEXT DEFAULT 'pending',
                error TEXT,
                started_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT,
                duration_ms INTEGER
            );

            CREATE TABLE IF NOT EXISTS workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                definition TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS workflow_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_name TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                steps_completed INTEGER DEFAULT 0,
                steps_total INTEGER DEFAULT 0,
                result TEXT DEFAULT '{}',
                started_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS directives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                directive TEXT NOT NULL,
                task_plan TEXT DEFAULT '{}',
                status TEXT DEFAULT 'pending',
                result TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS health_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                status TEXT NOT NULL,
                response_ms INTEGER,
                details TEXT DEFAULT '{}',
                checked_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                agent_name TEXT,
                tool_name TEXT,
                user TEXT DEFAULT 'system',
                details TEXT DEFAULT '{}',
                timestamp TEXT DEFAULT (datetime('now'))
            );

            -- Scheduled jobs
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                trigger_type TEXT NOT NULL DEFAULT 'cron',
                trigger_config TEXT DEFAULT '{}',
                action_type TEXT NOT NULL,
                action_config TEXT DEFAULT '{}',
                enabled INTEGER DEFAULT 0,
                last_run TEXT,
                next_run TEXT,
                last_result TEXT DEFAULT '',
                run_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Alert channels
            CREATE TABLE IF NOT EXISTS alert_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                channel_type TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                config TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Alert rules
            CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                condition TEXT NOT NULL,
                threshold REAL,
                duration_seconds INTEGER DEFAULT 0,
                severity TEXT DEFAULT 'warning',
                channels TEXT DEFAULT '[]',
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Active/historical alerts
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name TEXT NOT NULL,
                agent_name TEXT,
                severity TEXT DEFAULT 'warning',
                message TEXT DEFAULT '',
                status TEXT DEFAULT 'firing',
                fired_at TEXT DEFAULT (datetime('now')),
                resolved_at TEXT,
                notified_channels TEXT DEFAULT '[]'
            );

            -- Fleet events
            CREATE TABLE IF NOT EXISTS fleet_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                agent_name TEXT,
                details TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Remediation policies (state tracking)
            CREATE TABLE IF NOT EXISTS remediation_policies (
                name TEXT PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                trigger_count INTEGER DEFAULT 0,
                last_triggered TEXT,
                last_result TEXT DEFAULT ''
            );

            -- Policy executions
            CREATE TABLE IF NOT EXISTS policy_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                policy_name TEXT NOT NULL,
                target_agent TEXT,
                trigger_type TEXT,
                trigger_data TEXT DEFAULT '{}',
                status TEXT DEFAULT 'pending',
                started_at TEXT DEFAULT (datetime('now')),
                finished_at TEXT,
                duration_seconds REAL,
                result TEXT DEFAULT '{}',
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                approval_id TEXT,
                approved_by TEXT,
                approved_at TEXT
            );

            -- Escalation tracking
            CREATE TABLE IF NOT EXISTS escalations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_key TEXT NOT NULL,
                severity TEXT DEFAULT 'warning',
                current_level INTEGER DEFAULT 0,
                attempt_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                auto_fix_attempted INTEGER DEFAULT 0,
                auto_fix_result TEXT,
                acknowledged INTEGER DEFAULT 0,
                first_seen TEXT DEFAULT (datetime('now')),
                last_attempt TEXT,
                resolved_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_executions_agent ON executions(agent_name);
            CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);
            CREATE INDEX IF NOT EXISTS idx_health_agent ON health_snapshots(agent_name);
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_tool_manifests_agent ON tool_manifests(agent_name);
            CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
            CREATE INDEX IF NOT EXISTS idx_alerts_rule ON alerts(rule_name);
            CREATE INDEX IF NOT EXISTS idx_fleet_events_type ON fleet_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_fleet_events_agent ON fleet_events(agent_name);
            CREATE INDEX IF NOT EXISTS idx_policy_exec_policy ON policy_executions(policy_name);
            CREATE INDEX IF NOT EXISTS idx_policy_exec_status ON policy_executions(status);
            CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status);
            CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled ON scheduled_jobs(enabled);

            -- Agentic loop sessions
            CREATE TABLE IF NOT EXISTS agentic_sessions (
                session_id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                status TEXT DEFAULT 'running',
                iterations INTEGER DEFAULT 0,
                max_iterations INTEGER DEFAULT 25,
                tool_calls TEXT DEFAULT '[]',
                final_answer TEXT,
                error TEXT,
                started_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT,
                total_input_tokens INTEGER DEFAULT 0,
                total_output_tokens INTEGER DEFAULT 0,
                model TEXT DEFAULT '',
                callback_url TEXT,
                metadata TEXT DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_agentic_status ON agentic_sessions(status);
            CREATE INDEX IF NOT EXISTS idx_agentic_started ON agentic_sessions(started_at);

            -- Institutional memory: learned patterns from successful sessions
            CREATE TABLE IF NOT EXISTS learned_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                trigger_keywords TEXT NOT NULL,
                successful_approach TEXT NOT NULL,
                context TEXT DEFAULT '{}',
                source_session_id TEXT,
                times_used INTEGER DEFAULT 0,
                last_used TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_patterns_type ON learned_patterns(pattern_type);

            -- Institutional memory: organization knowledge facts
            CREATE TABLE IF NOT EXISTS org_knowledge (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                learned_from TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)
        await self._conn.commit()

        # Seed org_knowledge with defaults (INSERT OR IGNORE = only first time)
        seeds = [
            ("email_domain", "voltsys.ai", "seed"),
            ("email_format", "firstname.lastname", "seed"),
            ("default_license_sku", "ENTERPRISEPACK", "seed"),
            ("default_license_name", "Office 365 E3", "seed"),
            ("org_name", "VoltSys AI", "seed"),
            ("password_policy", "Welcome2026! with force change on first sign-in", "seed"),
            ("default_group_type", "security (security_enabled=true, mail_enabled=false)", "seed"),
        ]
        for key, value, src in seeds:
            await self._conn.execute(
                "INSERT OR IGNORE INTO org_knowledge (key, value, learned_from) VALUES (?, ?, ?)",
                (key, value, src),
            )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    async def execute(self, sql: str, params: tuple = ()) -> None:
        await self._conn.execute(sql, params)
        await self._conn.commit()

    async def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        cursor = await self._conn.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Agent operations
    # ------------------------------------------------------------------

    async def upsert_agent(self, name: str, display_name: str, url: str,
                           status: str = "unknown", tool_count: int = 0) -> None:
        await self._conn.execute("""
            INSERT INTO agents (name, display_name, url, status, tool_count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                display_name=excluded.display_name,
                url=excluded.url,
                status=excluded.status,
                tool_count=excluded.tool_count
        """, (name, display_name, url, status, tool_count))
        await self._conn.commit()

    async def update_agent_status(self, name: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE agents SET status=?, last_health_check=?, last_seen=? WHERE name=?",
            (status, now, now if status == "online" else None, name),
        )
        await self._conn.commit()

    async def get_agents(self) -> list[dict]:
        return await self.fetch_all("SELECT * FROM agents ORDER BY name")

    async def get_agent(self, name: str) -> Optional[dict]:
        return await self.fetch_one("SELECT * FROM agents WHERE name=?", (name,))

    # ------------------------------------------------------------------
    # Tool manifest operations
    # ------------------------------------------------------------------

    async def cache_tool_manifest(self, agent_name: str, tools: list[dict]) -> None:
        await self._conn.execute(
            "DELETE FROM tool_manifests WHERE agent_name=?", (agent_name,)
        )
        for t in tools:
            await self._conn.execute("""
                INSERT INTO tool_manifests (agent_name, tool_name, description, input_schema)
                VALUES (?, ?, ?, ?)
            """, (
                agent_name,
                t.get("name", ""),
                t.get("description", ""),
                json.dumps(t.get("input_schema", {})),
            ))
        await self._conn.commit()

    async def get_tool_manifest(self, agent_name: str) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM tool_manifests WHERE agent_name=? ORDER BY tool_name",
            (agent_name,),
        )

    async def search_tools(self, query: str) -> list[dict]:
        q = f"%{query}%"
        return await self.fetch_all(
            "SELECT * FROM tool_manifests WHERE tool_name LIKE ? OR description LIKE ? ORDER BY agent_name, tool_name",
            (q, q),
        )

    # ------------------------------------------------------------------
    # Execution log
    # ------------------------------------------------------------------

    async def log_execution(self, agent_name: str, tool_name: str, params: dict,
                            result: dict, status: str, error: str = None,
                            duration_ms: int = None) -> int:
        cursor = await self._conn.execute("""
            INSERT INTO executions (agent_name, tool_name, params, result, status, error,
                                    completed_at, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?)
        """, (
            agent_name, tool_name, json.dumps(params), json.dumps(result),
            status, error, duration_ms,
        ))
        await self._conn.commit()
        return cursor.lastrowid

    async def get_recent_executions(self, limit: int = 50) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM executions ORDER BY started_at DESC LIMIT ?", (limit,)
        )

    # ------------------------------------------------------------------
    # Health snapshots
    # ------------------------------------------------------------------

    async def log_health(self, agent_name: str, status: str,
                         response_ms: int = None, details: dict = None) -> None:
        await self._conn.execute("""
            INSERT INTO health_snapshots (agent_name, status, response_ms, details)
            VALUES (?, ?, ?, ?)
        """, (agent_name, status, response_ms, json.dumps(details or {})))
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    async def audit(self, action: str, agent_name: str = None,
                    tool_name: str = None, user: str = "system",
                    details: dict = None) -> None:
        await self._conn.execute("""
            INSERT INTO audit_log (action, agent_name, tool_name, user, details)
            VALUES (?, ?, ?, ?, ?)
        """, (action, agent_name, tool_name, user, json.dumps(details or {})))
        await self._conn.commit()

    async def get_audit_log(self, limit: int = 100) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        )

    # ------------------------------------------------------------------
    # Scheduled jobs
    # ------------------------------------------------------------------

    async def upsert_scheduled_job(self, name: str, description: str,
                                    trigger_type: str, trigger_config: dict,
                                    action_type: str, action_config: dict,
                                    enabled: bool = False) -> None:
        await self._conn.execute("""
            INSERT INTO scheduled_jobs (name, description, trigger_type, trigger_config,
                                        action_type, action_config, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description=excluded.description,
                trigger_type=excluded.trigger_type,
                trigger_config=excluded.trigger_config,
                action_type=excluded.action_type,
                action_config=excluded.action_config,
                enabled=excluded.enabled
        """, (name, description, trigger_type, json.dumps(trigger_config),
              action_type, json.dumps(action_config), int(enabled)))
        await self._conn.commit()

    async def get_scheduled_jobs(self) -> list[dict]:
        return await self.fetch_all("SELECT * FROM scheduled_jobs ORDER BY name")

    async def get_scheduled_job(self, name: str) -> Optional[dict]:
        return await self.fetch_one(
            "SELECT * FROM scheduled_jobs WHERE name=?", (name,))

    async def update_job_run(self, name: str, result: str,
                              next_run: str = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute("""
            UPDATE scheduled_jobs
            SET last_run=?, last_result=?, next_run=?, run_count=run_count+1
            WHERE name=?
        """, (now, result, next_run, name))
        await self._conn.commit()

    async def set_job_enabled(self, name: str, enabled: bool) -> None:
        await self._conn.execute(
            "UPDATE scheduled_jobs SET enabled=? WHERE name=?",
            (int(enabled), name))
        await self._conn.commit()

    async def delete_scheduled_job(self, name: str) -> None:
        await self._conn.execute(
            "DELETE FROM scheduled_jobs WHERE name=?", (name,))
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Alert channels
    # ------------------------------------------------------------------

    async def upsert_alert_channel(self, name: str, channel_type: str,
                                    config: dict, enabled: bool = True) -> None:
        await self._conn.execute("""
            INSERT INTO alert_channels (name, channel_type, config, enabled)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                channel_type=excluded.channel_type,
                config=excluded.config,
                enabled=excluded.enabled
        """, (name, channel_type, json.dumps(config), int(enabled)))
        await self._conn.commit()

    async def get_alert_channels(self) -> list[dict]:
        return await self.fetch_all("SELECT * FROM alert_channels ORDER BY name")

    async def delete_alert_channel(self, name: str) -> None:
        await self._conn.execute(
            "DELETE FROM alert_channels WHERE name=?", (name,))
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Alert rules
    # ------------------------------------------------------------------

    async def upsert_alert_rule(self, name: str, condition: str,
                                 severity: str = "warning",
                                 channels: list = None,
                                 threshold: float = None,
                                 duration_seconds: int = 0,
                                 description: str = "",
                                 enabled: bool = True) -> None:
        await self._conn.execute("""
            INSERT INTO alert_rules (name, description, condition, threshold,
                                      duration_seconds, severity, channels, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description=excluded.description,
                condition=excluded.condition,
                threshold=excluded.threshold,
                duration_seconds=excluded.duration_seconds,
                severity=excluded.severity,
                channels=excluded.channels,
                enabled=excluded.enabled
        """, (name, description, condition, threshold, duration_seconds,
              severity, json.dumps(channels or []), int(enabled)))
        await self._conn.commit()

    async def get_alert_rules(self) -> list[dict]:
        return await self.fetch_all("SELECT * FROM alert_rules ORDER BY name")

    async def delete_alert_rule(self, name: str) -> None:
        await self._conn.execute(
            "DELETE FROM alert_rules WHERE name=?", (name,))
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    async def insert_alert(self, rule_name: str, agent_name: str,
                            severity: str, message: str,
                            notified_channels: list = None) -> int:
        cursor = await self._conn.execute("""
            INSERT INTO alerts (rule_name, agent_name, severity, message, notified_channels)
            VALUES (?, ?, ?, ?, ?)
        """, (rule_name, agent_name, severity, message,
              json.dumps(notified_channels or [])))
        await self._conn.commit()
        return cursor.lastrowid

    async def resolve_alert(self, alert_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE alerts SET status='resolved', resolved_at=? WHERE id=?",
            (now, alert_id))
        await self._conn.commit()

    async def get_active_alerts(self) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM alerts WHERE status='firing' ORDER BY fired_at DESC")

    async def get_alert_history(self, limit: int = 50) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM alerts ORDER BY fired_at DESC LIMIT ?", (limit,))

    async def find_active_alert(self, rule_name: str,
                                 agent_name: str) -> Optional[dict]:
        return await self.fetch_one(
            "SELECT * FROM alerts WHERE rule_name=? AND agent_name=? AND status='firing'",
            (rule_name, agent_name))

    # ------------------------------------------------------------------
    # Fleet events
    # ------------------------------------------------------------------

    async def insert_fleet_event(self, event_type: str,
                                  agent_name: str = None,
                                  details: dict = None) -> int:
        cursor = await self._conn.execute("""
            INSERT INTO fleet_events (event_type, agent_name, details)
            VALUES (?, ?, ?)
        """, (event_type, agent_name, json.dumps(details or {})))
        await self._conn.commit()
        return cursor.lastrowid

    async def get_fleet_events(self, event_type: str = None,
                                limit: int = 50) -> list[dict]:
        if event_type:
            return await self.fetch_all(
                "SELECT * FROM fleet_events WHERE event_type=? ORDER BY created_at DESC LIMIT ?",
                (event_type, limit))
        return await self.fetch_all(
            "SELECT * FROM fleet_events ORDER BY created_at DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------
    # Remediation policies (state)
    # ------------------------------------------------------------------

    async def upsert_policy_state(self, name: str, enabled: bool = False) -> None:
        await self._conn.execute("""
            INSERT INTO remediation_policies (name, enabled)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled
        """, (name, int(enabled)))
        await self._conn.commit()

    async def set_policy_enabled(self, name: str, enabled: bool) -> None:
        await self._conn.execute(
            "UPDATE remediation_policies SET enabled=? WHERE name=?",
            (int(enabled), name))
        await self._conn.commit()

    async def update_policy_triggered(self, name: str, result: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute("""
            UPDATE remediation_policies
            SET trigger_count=trigger_count+1, last_triggered=?, last_result=?
            WHERE name=?
        """, (now, result, name))
        await self._conn.commit()

    async def get_policy_states(self) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM remediation_policies ORDER BY name")

    async def get_policy_state(self, name: str) -> Optional[dict]:
        return await self.fetch_one(
            "SELECT * FROM remediation_policies WHERE name=?", (name,))

    # ------------------------------------------------------------------
    # Policy executions
    # ------------------------------------------------------------------

    async def insert_policy_execution(self, policy_name: str,
                                       target_agent: str = None,
                                       trigger_type: str = "",
                                       trigger_data: dict = None,
                                       approval_id: str = None) -> int:
        cursor = await self._conn.execute("""
            INSERT INTO policy_executions
                (policy_name, target_agent, trigger_type, trigger_data, approval_id)
            VALUES (?, ?, ?, ?, ?)
        """, (policy_name, target_agent, trigger_type,
              json.dumps(trigger_data or {}), approval_id))
        await self._conn.commit()
        return cursor.lastrowid

    async def update_policy_execution(self, exec_id: int, status: str,
                                       result: dict = None, error: str = None,
                                       duration: float = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute("""
            UPDATE policy_executions
            SET status=?, result=?, error_message=?, duration_seconds=?, finished_at=?
            WHERE id=?
        """, (status, json.dumps(result or {}), error, duration, now, exec_id))
        await self._conn.commit()

    async def approve_policy_execution(self, approval_id: str,
                                        approved_by: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute("""
            UPDATE policy_executions
            SET status='approved', approved_by=?, approved_at=?
            WHERE approval_id=? AND status='pending_approval'
        """, (approved_by, now, approval_id))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_pending_approvals(self) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM policy_executions WHERE status='pending_approval' ORDER BY started_at DESC")

    async def get_policy_executions(self, policy_name: str = None,
                                     limit: int = 50) -> list[dict]:
        if policy_name:
            return await self.fetch_all(
                "SELECT * FROM policy_executions WHERE policy_name=? ORDER BY started_at DESC LIMIT ?",
                (policy_name, limit))
        return await self.fetch_all(
            "SELECT * FROM policy_executions ORDER BY started_at DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------
    # Escalations
    # ------------------------------------------------------------------

    async def upsert_escalation(self, issue_key: str, severity: str,
                                 current_level: int, attempt_count: int,
                                 auto_fix_attempted: bool = False,
                                 auto_fix_result: str = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute("""
            INSERT INTO escalations (issue_key, severity, current_level, attempt_count,
                                      auto_fix_attempted, auto_fix_result, last_attempt)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(issue_key) DO UPDATE SET
                severity=excluded.severity,
                current_level=excluded.current_level,
                attempt_count=excluded.attempt_count,
                auto_fix_attempted=excluded.auto_fix_attempted,
                auto_fix_result=excluded.auto_fix_result,
                last_attempt=excluded.last_attempt
        """, (issue_key, severity, current_level, attempt_count,
              int(auto_fix_attempted), auto_fix_result, now))
        await self._conn.commit()

    async def resolve_escalation(self, issue_key: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            "UPDATE escalations SET status='resolved', resolved_at=? WHERE issue_key=? AND status='active'",
            (now, issue_key))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def acknowledge_escalation(self, issue_key: str) -> bool:
        cursor = await self._conn.execute(
            "UPDATE escalations SET acknowledged=1 WHERE issue_key=? AND status='active'",
            (issue_key,))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_active_escalations(self) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM escalations WHERE status='active' ORDER BY first_seen DESC")

    # ------------------------------------------------------------------
    # Agentic loop sessions
    # ------------------------------------------------------------------

    async def insert_agentic_session(self, session: dict) -> None:
        await self._conn.execute("""
            INSERT INTO agentic_sessions
                (session_id, goal, status, iterations, max_iterations,
                 tool_calls, final_answer, error, started_at, completed_at,
                 total_input_tokens, total_output_tokens, model,
                 callback_url, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session["session_id"], session["goal"], session["status"],
            session["iterations"], session["max_iterations"],
            json.dumps(session.get("tool_calls", [])),
            session.get("final_answer"), session.get("error"),
            session["started_at"], session.get("completed_at"),
            session.get("total_input_tokens", 0),
            session.get("total_output_tokens", 0),
            session.get("model", ""),
            session.get("callback_url"),
            json.dumps(session.get("metadata", {})),
        ))
        await self._conn.commit()

    async def update_agentic_session(self, session_id: str, **kwargs) -> None:
        await self._conn.execute("""
            UPDATE agentic_sessions
            SET iterations=?, tool_calls=?,
                total_input_tokens=?, total_output_tokens=?
            WHERE session_id=?
        """, (
            kwargs.get("iterations", 0),
            json.dumps(kwargs.get("tool_calls", [])),
            kwargs.get("input_tokens", 0),
            kwargs.get("output_tokens", 0),
            session_id,
        ))
        await self._conn.commit()

    async def finalize_agentic_session(self, session: dict) -> None:
        await self._conn.execute("""
            UPDATE agentic_sessions
            SET status=?, iterations=?, tool_calls=?,
                final_answer=?, error=?, completed_at=?,
                total_input_tokens=?, total_output_tokens=?
            WHERE session_id=?
        """, (
            session["status"], session["iterations"],
            json.dumps(session.get("tool_calls", [])),
            session.get("final_answer"), session.get("error"),
            session.get("completed_at"),
            session.get("total_input_tokens", 0),
            session.get("total_output_tokens", 0),
            session["session_id"],
        ))
        await self._conn.commit()

    async def get_agentic_session(self, session_id: str) -> Optional[dict]:
        return await self.fetch_one(
            "SELECT * FROM agentic_sessions WHERE session_id=?",
            (session_id,))

    async def get_agentic_sessions(self, status: str = None,
                                    limit: int = 50) -> list[dict]:
        if status:
            return await self.fetch_all(
                "SELECT * FROM agentic_sessions WHERE status=? ORDER BY started_at DESC LIMIT ?",
                (status, limit))
        return await self.fetch_all(
            "SELECT * FROM agentic_sessions ORDER BY started_at DESC LIMIT ?",
            (limit,))

    async def get_escalation_stats(self) -> dict:
        active = await self.fetch_all(
            "SELECT current_level, COUNT(*) as cnt FROM escalations WHERE status='active' GROUP BY current_level")
        total = await self.fetch_one(
            "SELECT COUNT(*) as total FROM escalations WHERE status='active'")
        return {
            "total_active": total["total"] if total else 0,
            "by_level": {str(r["current_level"]): r["cnt"] for r in active},
        }

    # ------------------------------------------------------------------
    # Institutional memory — learned patterns
    # ------------------------------------------------------------------

    async def insert_learned_pattern(self, pattern: dict) -> int:
        cursor = await self._conn.execute("""
            INSERT INTO learned_patterns
            (pattern_type, trigger_keywords, successful_approach, context, source_session_id)
            VALUES (?, ?, ?, ?, ?)
        """, (
            pattern["pattern_type"],
            pattern["trigger_keywords"],
            pattern["successful_approach"],
            json.dumps(pattern.get("context", {})),
            pattern.get("source_session_id", ""),
        ))
        await self._conn.commit()
        return cursor.lastrowid

    async def get_learned_patterns(self, pattern_type: str = None,
                                    limit: int = 20) -> list[dict]:
        if pattern_type:
            return await self.fetch_all(
                "SELECT * FROM learned_patterns WHERE pattern_type=? ORDER BY times_used DESC, created_at DESC LIMIT ?",
                (pattern_type, limit))
        return await self.fetch_all(
            "SELECT * FROM learned_patterns ORDER BY times_used DESC, created_at DESC LIMIT ?",
            (limit,))

    async def search_learned_patterns(self, keywords: str,
                                       limit: int = 5) -> list[dict]:
        """Search patterns by matching any keyword against trigger_keywords."""
        words = [w.strip().lower() for w in keywords.split() if len(w.strip()) > 2]
        if not words:
            return []
        # Build OR conditions for each keyword
        conditions = " OR ".join(["LOWER(trigger_keywords) LIKE ?"] * len(words))
        params = [f"%{w}%" for w in words]
        params.append(limit)
        return await self.fetch_all(
            f"SELECT * FROM learned_patterns WHERE {conditions} ORDER BY times_used DESC LIMIT ?",
            tuple(params))

    async def increment_pattern_usage(self, pattern_id: int) -> None:
        await self._conn.execute(
            "UPDATE learned_patterns SET times_used = times_used + 1, last_used = datetime('now') WHERE id=?",
            (pattern_id,))
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Institutional memory — org knowledge
    # ------------------------------------------------------------------

    async def get_all_org_knowledge(self) -> list[dict]:
        return await self.fetch_all("SELECT * FROM org_knowledge ORDER BY key")

    async def get_org_knowledge(self, key: str) -> Optional[str]:
        row = await self.fetch_one(
            "SELECT value FROM org_knowledge WHERE key=?", (key,))
        return row["value"] if row else None

    async def set_org_knowledge(self, key: str, value: str,
                                 learned_from: str = "auto") -> None:
        await self._conn.execute("""
            INSERT INTO org_knowledge (key, value, learned_from, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                learned_from=excluded.learned_from,
                updated_at=datetime('now')
        """, (key, value, learned_from))
        await self._conn.commit()
