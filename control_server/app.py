from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from control_server.auth import ControlAuthService
from control_server.config import load_control_config
from control_server.routes import configure_routes, router
from control_server.store import ControlPlaneStore


def create_app() -> FastAPI:
    root = Path(__file__).resolve().parent.parent
    config_path = Path(os.environ.get("MIUS_CONTROL_CONFIG", root / "control-config.json"))
    example_path = root / "control-config.example.json"
    if not config_path.exists():
        config_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")

    config = load_control_config(config_path)
    auth = ControlAuthService(config)
    store = ControlPlaneStore(config)
    configure_routes(config, auth, store)

    app = FastAPI(title="Machine Image Control Plane", version="0.1.0")
    app.include_router(router)

    static_root = root / "control_server" / "static"
    if static_root.exists():
        app.mount("/static", StaticFiles(directory=static_root), name="static")
    dashboard_root = static_root / "dashboard"
    if dashboard_root.exists():
        app.mount("/dashboard", StaticFiles(directory=dashboard_root, html=True), name="dashboard")

        @app.get("/", include_in_schema=False)
        def dashboard_home() -> RedirectResponse:
            return RedirectResponse(url="/dashboard/")

    return app


app = create_app()
