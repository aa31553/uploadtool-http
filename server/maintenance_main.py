from __future__ import annotations

import os
from pathlib import Path

from server.config import load_server_config
from server.maintenance import MaintenanceManager


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    config_path = Path(os.environ.get("MIUS_SERVER_CONFIG", root / "server-config.json"))
    if not config_path.exists():
        config_path.write_text((root / "server-config.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    config = load_server_config(config_path)
    maintenance = MaintenanceManager(config)
    result = maintenance.run_startup_maintenance()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
