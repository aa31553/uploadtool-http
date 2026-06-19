from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect

from server.auth import UserAuthService
from server.config import ServerConfig
from server.models import AccountActionResponse, AlertItem, AuthUser, ChangePasswordRequest, ImageFlowBatch, LoginRequest, LoginResponse, MachineDetail, MachineStatus, QueueStatus, RegisterUserRequest, ResetPasswordRequest, ServerMetrics, StorageStatus, UploadAccepted, WorkerState
from server.queue import QueueBackend
from server.store import store
from server.storage import UploadStorage


router = APIRouter()
runtime_config: ServerConfig | None = None
upload_storage: UploadStorage | None = None
runtime_queue: QueueBackend | None = None
runtime_auth: UserAuthService | None = None


def configure_routes(config: ServerConfig, storage: UploadStorage, queue: QueueBackend, auth: UserAuthService) -> None:
    global runtime_config, upload_storage, runtime_queue, runtime_auth
    runtime_config = config
    upload_storage = storage
    runtime_queue = queue
    runtime_auth = auth
    store.configure(config, queue)


def _require_runtime() -> tuple[ServerConfig, UploadStorage, QueueBackend, UserAuthService]:
    if runtime_config is None or upload_storage is None or runtime_queue is None or runtime_auth is None:
        raise RuntimeError("Server routes are not configured")
    return runtime_config, upload_storage, runtime_queue, runtime_auth


def _validate_machine_token(machine_id: str, token: str | None) -> None:
    config, _, _, _ = _require_runtime()
    expected = config.machine_token(machine_id)
    if expected is None:
        raise HTTPException(status_code=403, detail="Unknown machine_id")
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid API token")


def enforce_ip_allowlist(client_host: str | None) -> None:
    config, _, _, _ = _require_runtime()
    allowlist = set(config.ip_allowlist)
    if not allowlist:
        return
    if client_host not in allowlist:
        raise HTTPException(status_code=403, detail={"code": "E401", "message": f"Client IP {client_host or 'unknown'} is not allowed", "recovery": "Add the plant IP to ip_allowlist or route through approved proxy"})


def resolve_client_host(request: Request) -> str | None:
    config, _, _, _ = _require_runtime()
    if config.trust_x_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Authorization header must use Bearer token")
    return authorization[len(prefix) :].strip() or None


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict[str, str]:
    _, storage, _, _ = _require_runtime()
    ready, message = storage.readiness()
    if not ready:
        raise HTTPException(status_code=503, detail={"code": "E301", "message": message, "recovery": "Check storage path permissions and free disk space"})
    if storage.disk_usage_percent() >= storage.max_disk_usage_percent():
        raise HTTPException(status_code=503, detail={"code": "E302", "message": "Server disk usage above configured safety threshold", "recovery": "Clear storage, tighten retention, or expand disk before resuming load"})
    return {"status": message}


@router.post("/upload", response_model=UploadAccepted)
async def upload_batch(
    request: Request,
    machine_id: str = Form(...),
    timestamp: datetime = Form(...),
    batch_file: UploadFile = File(...),
    api_token: str | None = Header(default=None, alias="X-API-Token"),
    checksum_sha256: str | None = Header(default=None, alias="X-Checksum-SHA256"),
    idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> UploadAccepted:
    enforce_ip_allowlist(resolve_client_host(request))
    if not checksum_sha256:
        raise HTTPException(status_code=400, detail={"code": "E202", "message": "Missing checksum header", "recovery": "Client should resend batch with X-Checksum-SHA256"})
    if not idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "E203", "message": "Missing idempotency header", "recovery": "Client should resend batch with X-Idempotency-Key"})
    _validate_machine_token(machine_id, api_token)
    _, storage, _, _ = _require_runtime()
    try:
        stored_path, _metadata, duplicate = await storage.save_upload(machine_id, timestamp, batch_file, idempotency_key, checksum_sha256)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "E201", "message": str(exc), "recovery": "Retry the same batch if network was interrupted; rebuild batch if checksum keeps failing"}) from exc
    return UploadAccepted(
        machine_id=machine_id,
        timestamp=timestamp,
        batch_filename=batch_file.filename,
        accepted=True,
        stored_path=str(stored_path),
        metadata_recorded=True,
        duplicate=duplicate,
        queue_enqueued=not duplicate,
        error_code=None,
    )


@router.post("/api/auth/login", response_model=LoginResponse)
def login(request: Request, payload: LoginRequest) -> LoginResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _, _, _, auth = _require_runtime()
    session = auth.login(payload.employee_id, payload.password)
    return LoginResponse(
        token=session.token,
        expires_at=session.expires_at,
        user=AuthUser(employee_id=session.employee_id, role=session.role),
    )


@router.post("/api/auth/logout", response_model=AccountActionResponse)
def logout(request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> AccountActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _, _, _, auth = _require_runtime()
    token = _bearer_token(authorization)
    if token:
        auth.logout(token)
    return AccountActionResponse(success=True, message="Logged out")


@router.get("/api/auth/me", response_model=AuthUser)
def auth_me(request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> AuthUser:
    enforce_ip_allowlist(resolve_client_host(request))
    _, _, _, auth = _require_runtime()
    session = auth.require_session(_bearer_token(authorization))
    return AuthUser(employee_id=session.employee_id, role=session.role)


@router.post("/api/auth/register", response_model=AccountActionResponse)
def register_user(
    request: Request,
    payload: RegisterUserRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AccountActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _, _, _, auth = _require_runtime()
    actor = auth.require_session(_bearer_token(authorization))
    user = auth.register_user(actor, payload.employee_id, payload.password, payload.role)
    return AccountActionResponse(
        success=True,
        message="User registered",
        user=AuthUser(employee_id=str(user["employee_id"]), role=str(user["role"])),
    )


@router.post("/api/auth/change-password", response_model=AccountActionResponse)
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AccountActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _, _, _, auth = _require_runtime()
    actor = auth.require_session(_bearer_token(authorization))
    auth.change_password(actor, payload.current_password, payload.new_password)
    return AccountActionResponse(success=True, message="Password updated")


@router.post("/api/auth/reset-password", response_model=AccountActionResponse)
def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AccountActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _, _, _, auth = _require_runtime()
    actor = auth.require_session(_bearer_token(authorization))
    auth.reset_password(actor, payload.employee_id, payload.new_password)
    return AccountActionResponse(success=True, message="Password reset")


@router.get("/api/machines", response_model=list[MachineStatus])
def list_machines() -> list[MachineStatus]:
    return store.machines()


@router.get("/api/machines/{machine_id}", response_model=MachineDetail)
def get_machine_detail(machine_id: str) -> MachineDetail:
    detail = store.machine_detail(machine_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Machine not found")
    return detail


@router.get("/api/server/metrics", response_model=ServerMetrics)
def get_server_metrics() -> ServerMetrics:
    return store.server_metrics()


@router.get("/api/queue/status", response_model=QueueStatus)
def get_queue_status() -> QueueStatus:
    return store.queue_status()


@router.get("/api/storage/status", response_model=StorageStatus)
def get_storage_status() -> StorageStatus:
    return store.storage_status()


@router.get("/api/alerts", response_model=list[AlertItem])
def list_alerts() -> list[AlertItem]:
    return store.alerts()


@router.get("/api/image-flow/recent", response_model=list[ImageFlowBatch])
def get_recent_image_flow(machine_id: str | None = None, limit: int = 20) -> list[ImageFlowBatch]:
    return store.recent_batches(machine_id=machine_id, limit=limit)


@router.get("/api/worker/status", response_model=WorkerState)
def get_worker_status() -> WorkerState:
    return store.worker_state()


@router.get("/api/local/server-info")
def get_local_server_info() -> dict[str, object]:
    config, _, _, _ = _require_runtime()
    return {
        "server_id": config.server_id,
        "name": config.server_name,
        "site": config.site,
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/local/snapshot")
def get_local_snapshot() -> dict[str, object]:
    config, _, _, _ = _require_runtime()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "server_info": {
            "server_id": config.server_id,
            "name": config.server_name,
            "site": config.site,
        },
        "machines": [machine.model_dump(mode="json") for machine in store.machines()],
        "server_metrics": store.server_metrics().model_dump(mode="json"),
        "queue": store.queue_status().model_dump(mode="json"),
        "storage": store.storage_status().model_dump(mode="json"),
        "worker": store.worker_state().model_dump(mode="json"),
        "alerts": [alert.model_dump(mode="json") for alert in store.alerts()],
        "image_flow": [item.model_dump(mode="json") for item in store.recent_batches(limit=20)],
    }


@router.websocket("/ws/live")
async def live_updates(websocket: WebSocket) -> None:
    client_host = websocket.client.host if websocket.client else None
    config, _, _, _ = _require_runtime()
    allowlist = set(config.ip_allowlist)
    if allowlist and client_host not in allowlist:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    try:
        while True:
            snapshot = {
                "type": "snapshot",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "machines": [machine.model_dump(mode="json") for machine in store.machines()],
                "server_metrics": store.server_metrics().model_dump(mode="json"),
                "queue": store.queue_status().model_dump(mode="json"),
                "storage": store.storage_status().model_dump(mode="json"),
                "worker": store.worker_state().model_dump(mode="json"),
                "alerts": [alert.model_dump(mode="json") for alert in store.alerts()],
            }
            await websocket.send_json(snapshot)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
