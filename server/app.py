from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from server.config import load_server_config
from server.maintenance import MaintenanceManager
from server.queue import create_queue
from server.routes import configure_routes, router
from server.storage import UploadStorage


def create_app() -> FastAPI:
    root = Path(__file__).resolve().parent.parent
    config_path = Path(os.environ.get("MIUS_SERVER_CONFIG", root / "server-config.json"))
    example_path = root / "server-config.example.json"
    if not config_path.exists():
        config_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")

    config = load_server_config(config_path)
    queue = create_queue(config)
    storage = UploadStorage(config, queue)
    configure_routes(config, storage, queue)
    maintenance = MaintenanceManager(config)
    maintenance.run_startup_maintenance()

    app = FastAPI(title="Machine Image Uploader Server", version="0.1.0")
    app.include_router(router)
    return app


app = create_app()
