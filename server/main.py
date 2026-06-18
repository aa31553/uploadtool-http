from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from server.config import load_server_config


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    config_path = Path(os.environ.get("MIUS_SERVER_CONFIG", root / "server-config.json"))
    if not config_path.exists():
        config_path.write_text((root / "server-config.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    config = load_server_config(config_path)
    uvicorn.run("server.app:app", host=config.host, port=config.port, reload=False)
    return 0
