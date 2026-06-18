from __future__ import annotations

import shutil
import time
from pathlib import Path

from server.config import ServerConfig


class MaintenanceManager:
    def __init__(self, config: ServerConfig) -> None:
        self._config = config

    def run_startup_maintenance(self) -> dict[str, int | float | bool]:
        return {
            "raw_removed": self._cleanup_old_files(Path(self._config.storage_root) / "raw", self._config.raw_retention_days * 86400),
            "temp_removed": self._cleanup_old_files(Path(self._config.temp_root), self._config.temp_retention_hours * 3600),
            "disk_usage_percent": round(self.disk_usage_percent(), 1),
            "disk_over_limit": self.disk_usage_percent() >= self._config.max_disk_usage_percent,
        }

    def disk_usage_percent(self) -> float:
        usage = shutil.disk_usage(self._config.storage_root)
        return (usage.used / usage.total) * 100 if usage.total else 0.0

    def _cleanup_old_files(self, root: Path, age_seconds: int) -> int:
        if not root.exists():
            return 0
        cutoff = time.time() - age_seconds
        removed = 0
        for path in root.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed
