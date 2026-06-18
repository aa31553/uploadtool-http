from __future__ import annotations

from pathlib import Path

from server.config import load_server_config
from worker.service import WorkerService


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    config_path = root / "server-config.json"
    if not config_path.exists():
        config_path.write_text((root / "server-config.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    config = load_server_config(config_path)
    service = WorkerService(config)
    service.run_forever()
    return 0
