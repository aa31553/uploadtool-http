from __future__ import annotations

import os
from pathlib import Path

from machine_client.agent import AgentService
from machine_client.config import load_config, save_config
from machine_client.ui import run_app


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    example_config_path = root / "config.example.json"
    config_path = Path(os.environ.get("MIUS_MACHINE_CONFIG", root / "config.json"))
    if not config_path.exists():
        config = load_config(example_config_path)
        save_config(config_path, config)
    config = load_config(config_path)
    agent = AgentService(config, config_path)
    return run_app(config, agent)
