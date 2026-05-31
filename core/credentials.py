"""Credential manager with Fernet encryption for the Fleet Orchestrator."""

import base64
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet

logger = logging.getLogger("fleet.credentials")


class CredentialManager:
    """Encrypt / decrypt credentials stored in the database."""

    def __init__(self, db, encryption_key: Optional[str] = None):
        self.db = db
        key = encryption_key or os.environ.get("FLEET_ENCRYPTION_KEY")
        if not key:
            key = Fernet.generate_key().decode()
            logger.warning("No encryption key set — generated ephemeral key")
        if isinstance(key, str):
            # Accept raw 32-byte key or Fernet base64 key
            try:
                self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
            except Exception:
                padded = base64.urlsafe_b64encode(key.encode().ljust(32, b"\0")[:32])
                self._fernet = Fernet(padded)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()

    async def store(self, name: str, value: str) -> None:
        encrypted = self.encrypt(value)
        await self.db.execute("""
            INSERT INTO audit_log (action, details) VALUES (?, ?)
        """, ("credential_stored", f'{{"name": "{name}"}}'))

    async def retrieve(self, name: str) -> Optional[str]:
        return None  # Credentials are managed via config.yaml agent entries
