"""Database Backup Engine — automated SQLite backup and retention."""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("fleet.backup")


class BackupEngine:
    """Manages database backups with retention policy."""

    def __init__(self, db_path: str, backup_dir: str = None):
        self._db_path = db_path
        self._backup_dir = backup_dir or os.path.join(
            os.path.dirname(db_path), "backups"
        )
        os.makedirs(self._backup_dir, exist_ok=True)

    async def create_backup(self) -> dict:
        """Create a timestamped backup of the fleet database."""
        if not os.path.exists(self._db_path):
            return {"success": False, "error": "Database file not found"}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"fleet_{timestamp}.db"
        backup_path = os.path.join(self._backup_dir, backup_name)

        try:
            shutil.copy2(self._db_path, backup_path)
            size = os.path.getsize(backup_path)
            logger.info("Backup created: %s (%d bytes)", backup_name, size)
            return {
                "success": True,
                "filename": backup_name,
                "size_bytes": size,
                "path": backup_path,
            }
        except Exception as exc:
            logger.error("Backup failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def list_backups(self) -> list[dict]:
        """List all backup files sorted by date (newest first)."""
        backups = []
        for f in sorted(Path(self._backup_dir).glob("fleet_*.db"), reverse=True):
            backups.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return backups

    async def cleanup_old(self, keep: int = 30) -> int:
        """Delete oldest backups beyond the retention count. Returns count deleted."""
        files = sorted(Path(self._backup_dir).glob("fleet_*.db"), reverse=True)
        deleted = 0
        for f in files[keep:]:
            try:
                f.unlink()
                deleted += 1
                logger.info("Deleted old backup: %s", f.name)
            except Exception as exc:
                logger.warning("Failed to delete %s: %s", f.name, exc)
        return deleted

    async def get_backup_stats(self) -> dict:
        """Get backup summary statistics."""
        backups = await self.list_backups()
        total_size = sum(b["size_bytes"] for b in backups)
        return {
            "count": len(backups),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "last_backup": backups[0]["created_at"] if backups else None,
            "backup_dir": self._backup_dir,
        }
