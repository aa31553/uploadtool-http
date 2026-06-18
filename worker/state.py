from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from server.config import ServerConfig


class WorkerStateStore:
    def __init__(self, config: ServerConfig) -> None:
        self._path = Path(config.worker_state_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, payload: dict[str, object]) -> None:
        data = {**payload, "updated_at": datetime.now(timezone.utc).isoformat()}
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def read(self) -> dict[str, object]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))
