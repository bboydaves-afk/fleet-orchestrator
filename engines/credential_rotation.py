"""Credential Rotation Engine — rotate agent passwords with zero downtime."""

import logging
import os
import re
import secrets
import shutil
import string
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("fleet.credential_rotation")

BASE_PATH = Path(r"C:\Users\carin\OneDrive\Desktop")
FLEET_ENV = BASE_PATH / "fleet_orchestrator" / ".env"
PASSWORD_LENGTH = 24
PASSWORD_CHARS = string.ascii_letters + string.digits + "-_"


def _generate_password() -> str:
    """Generate a cryptographically secure password."""
    return "".join(secrets.choice(PASSWORD_CHARS) for _ in range(PASSWORD_LENGTH))


def _update_env_file(env_path: Path, key: str, new_value: str) -> bool:
    """Update a key=value pair in a .env file. Returns True if successful."""
    if not env_path.exists():
        return False

    content = env_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)

    if pattern.search(content):
        new_content = pattern.sub(f"{key}={new_value}", content)
    else:
        new_content = content.rstrip() + f"\n{key}={new_value}\n"

    # Backup before writing
    backup = env_path.with_suffix(".env.bak")
    shutil.copy2(env_path, backup)

    env_path.write_text(new_content, encoding="utf-8")
    return True


class CredentialRotation:
    """Manages password rotation for fleet agents."""

    def __init__(self, fleet_engine, db=None):
        self._fleet = fleet_engine
        self._db = db

    async def rotate_password(self, agent_name: str) -> dict:
        """Rotate a single agent's password.

        Steps:
        1. Generate new password
        2. Update Fleet .env file (AGENT_{NAME}_PASSWORD=...)
        3. Update the running process env var
        4. Re-authenticate with the agent using new password
        5. Verify connection works
        """
        env_key = f"AGENT_{agent_name.upper()}_PASSWORD"
        old_password = os.environ.get(env_key)

        if not old_password:
            return {"success": False, "agent": agent_name,
                    "error": f"No existing password found for {env_key}"}

        new_password = _generate_password()

        # Step 1: Update Fleet .env file
        if not _update_env_file(FLEET_ENV, env_key, new_password):
            return {"success": False, "agent": agent_name,
                    "error": "Failed to update Fleet .env file"}

        # Step 2: Update running process env
        os.environ[env_key] = new_password

        # Step 3: Also update the agent's own .env if it exists
        agent_env = BASE_PATH / agent_name / ".env"
        if agent_env.exists():
            _update_env_file(agent_env, env_key, new_password)
            # Also update the generic PASSWORD key some agents use
            _update_env_file(agent_env, "ADMIN_PASSWORD", new_password)

        # Step 4: Re-authenticate with the agent
        try:
            auth_ok = await self._fleet.authenticate(agent_name)
            if not auth_ok:
                # Rollback — restore old password
                logger.error("Re-auth failed for %s, rolling back", agent_name)
                os.environ[env_key] = old_password
                _update_env_file(FLEET_ENV, env_key, old_password)
                return {"success": False, "agent": agent_name,
                        "error": "Re-authentication failed after rotation, rolled back"}
        except Exception as exc:
            # Rollback
            logger.error("Re-auth exception for %s: %s, rolling back", agent_name, exc)
            os.environ[env_key] = old_password
            _update_env_file(FLEET_ENV, env_key, old_password)
            return {"success": False, "agent": agent_name,
                    "error": f"Re-auth error: {exc}, rolled back"}

        # Step 5: Audit log
        if self._db:
            try:
                await self._db.add_audit_entry(
                    action="password_rotated",
                    agent_name=agent_name,
                    details=f"Password rotated for {env_key}",
                )
            except Exception:
                pass

        logger.info("Password rotated for %s", agent_name)
        return {
            "success": True,
            "agent": agent_name,
            "rotated_at": datetime.utcnow().isoformat(),
            "note": "Agent must be restarted to pick up new password from .env",
        }

    async def rotate_all(self) -> dict:
        """Rotate passwords for all connected agents."""
        results = {}
        agents = self._fleet.get_agents()

        for agent in agents:
            name = agent.name
            result = await self.rotate_password(name)
            results[name] = result

        success_count = sum(1 for r in results.values() if r.get("success"))
        return {
            "results": results,
            "total": len(results),
            "success": success_count,
            "failed": len(results) - success_count,
        }

    def get_password_ages(self) -> dict:
        """Report the .env file's last modified time as a proxy for password age."""
        if not FLEET_ENV.exists():
            return {"error": ".env not found"}

        mtime = datetime.fromtimestamp(FLEET_ENV.stat().st_mtime)
        return {
            "env_file": str(FLEET_ENV),
            "last_modified": mtime.isoformat(),
            "age_days": (datetime.now() - mtime).days,
        }
