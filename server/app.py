from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from server.auth import UserAuthService
from server.config import load_server_config
from server.maintenance import MaintenanceManager
from server.queue import create_queue
from server.routes import configure_routes, router
from server.storage import UploadStorage


# Some factory/offline environments inherit incomplete MIME mappings and may
# serve JavaScript as text/plain unless we register these explicitly.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")


def create_app() -> FastAPI:
    root = Path(__file__).resolve().parent.parent
    config_path = Path(os.environ.get("MIUS_SERVER_CONFIG", root / "server-config.json"))
    example_path = root / "server-config.example.json"
    if not config_path.exists():
        config_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")

    config = load_server_config(config_path)
    queue = create_queue(config)
    storage = UploadStorage(config, queue)
    auth = UserAuthService(config)
    configure_routes(config, storage, queue, auth)
    maintenance = MaintenanceManager(config)
    maintenance.run_startup_maintenance()

    app = FastAPI(
        title="Machine Image Uploader Server",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )
    app.include_router(router)

    static_root = root / "server" / "static"
    if static_root.exists():
        app.mount("/static", StaticFiles(directory=static_root), name="static")

    dashboard_root = root / "server" / "static" / "dashboard"
    if dashboard_root.exists():
        app.mount("/dashboard", StaticFiles(directory=dashboard_root, html=True), name="dashboard")

        @app.get("/", include_in_schema=False)
        def dashboard_root() -> RedirectResponse:
            return RedirectResponse(url="/dashboard/")

    @app.get("/docs", include_in_schema=False)
    def local_swagger_ui():
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=f"{app.title} - Swagger UI",
            swagger_js_url="/static/vendor/swagger-ui-bundle.js",
            swagger_css_url="/static/vendor/swagger-ui.css",
            swagger_favicon_url="/static/vendor/favicon.svg",
        )

    @app.get("/redoc", include_in_schema=False)
    def local_redoc():
        return get_redoc_html(
            openapi_url=app.openapi_url,
            title=f"{app.title} - ReDoc",
            redoc_js_url="/static/vendor/redoc.standalone.js",
            redoc_favicon_url="/static/vendor/favicon.svg",
            with_google_fonts=False,
        )

    return app


app = create_app()
