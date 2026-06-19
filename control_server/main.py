from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from control_server.config import load_control_config


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    config_path = Path(os.environ.get("MIUS_CONTROL_CONFIG", root / "control-config.json"))
    if not config_path.exists():
        config_path.write_text((root / "control-config.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    config = load_control_config(config_path)
    uvicorn.run("control_server.app:app", host=config.host, port=config.port, reload=False)
    return 0
