from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

from server.config import ServerConfig
from server.models import AlertItem, ImageFlowBatch, MachineDetail, MachineStatus, QueueStatus, ServerMetrics, StorageStatus, UploadAccepted, WorkerState
from server.queue import FileQueue
from server.store import store
from server.storage import UploadStorage


router = APIRouter()
runtime_config: ServerConfig | None = None
upload_storage: UploadStorage | None = None
runtime_queue: FileQueue | None = None


def configure_routes(config: ServerConfig, storage: UploadStorage, queue: FileQueue) -> None:
    global runtime_config, upload_storage, runtime_queue
    runtime_config = config
    upload_storage = storage
    runtime_queue = queue
    store.configure(config, queue)


def _require_runtime() -> tuple[ServerConfig, UploadStorage, FileQueue]:
    if runtime_config is None or upload_storage is None or runtime_queue is None:
        raise RuntimeError("Server routes are not configured")
    return runtime_config, upload_storage, runtime_queue


def _validate_machine_token(machine_id: str, token: str | None) -> None:
    config, _, _ = _require_runtime()
    expected = config.machine_token(machine_id)
    if expected is None:
        raise HTTPException(status_code=403, detail="Unknown machine_id")
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid API token")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict[str, str]:
    _, storage, _ = _require_runtime()
    ready, message = storage.readiness()
    if not ready:
        raise HTTPException(status_code=503, detail=message)
    return {"status": message}


@router.post("/upload", response_model=UploadAccepted)
async def upload_batch(
    machine_id: str = Form(...),
    timestamp: datetime = Form(...),
    batch_file: UploadFile = File(...),
    api_token: str | None = Header(default=None, alias="X-API-Token"),
) -> UploadAccepted:
    _validate_machine_token(machine_id, api_token)
    _, storage, _ = _require_runtime()
    stored_path, _metadata = await storage.save_upload(machine_id, timestamp, batch_file)
    return UploadAccepted(
        machine_id=machine_id,
        timestamp=timestamp,
        batch_filename=batch_file.filename,
        accepted=True,
        stored_path=str(stored_path),
        metadata_recorded=True,
    )


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


@router.websocket("/ws/live")
async def live_updates(websocket: WebSocket) -> None:
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
