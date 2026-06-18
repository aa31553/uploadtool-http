from __future__ import annotations

import json
import threading
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from server.config import ServerConfig
from server.queue import FileQueue


class UploadStorage:
    def __init__(self, config: ServerConfig, queue: FileQueue) -> None:
        self._config = config
        self._queue = queue
        self._lock = threading.Lock()
        Path(self._config.storage_root).mkdir(parents=True, exist_ok=True)
        Path(self._config.temp_root).mkdir(parents=True, exist_ok=True)
        Path(self._config.processed_root).mkdir(parents=True, exist_ok=True)
        Path(self._config.failed_root).mkdir(parents=True, exist_ok=True)
        Path(self._config.metadata_path).parent.mkdir(parents=True, exist_ok=True)

    async def save_upload(self, machine_id: str, timestamp: datetime, batch_file: UploadFile) -> tuple[str, dict[str, object]]:
        date_path = timestamp.strftime("%Y/%m/%d")
        upload_dir = Path(self._config.storage_root) / "raw" / machine_id / date_path
        upload_dir.mkdir(parents=True, exist_ok=True)

        safe_name = batch_file.filename or f"{machine_id}-{timestamp.strftime('%H%M%S')}.zip"
        stored_path = upload_dir / safe_name
        counter = 1
        while stored_path.exists():
            stored_path = upload_dir / f"{stored_path.stem}_{counter}{stored_path.suffix}"
            counter += 1

        contents = await batch_file.read()
        stored_path.write_bytes(contents)
        image_count = self._count_images(contents)
        job_id = f"{machine_id}-{timestamp.strftime('%Y%m%dT%H%M%S%f')}"

        metadata = {
            "job_id": job_id,
            "machine_id": machine_id,
            "timestamp": timestamp.isoformat(),
            "received_at": datetime.now(timezone.utc).isoformat(),
            "batch_filename": batch_file.filename,
            "stored_path": str(stored_path),
            "size_bytes": len(contents),
            "image_count": image_count,
            "queued": True,
        }
        self._append_metadata(metadata)
        self._queue.enqueue(metadata)
        return str(stored_path), metadata

    def readiness(self) -> tuple[bool, str]:
        for path in [Path(self._config.storage_root), Path(self._config.temp_root), Path(self._config.metadata_path).parent]:
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".write-test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except OSError as exc:
                return False, f"{path}: {exc}"
        return True, "ready"

    def _append_metadata(self, metadata: dict[str, object]) -> None:
        with self._lock:
            metadata_path = Path(self._config.metadata_path)
            with metadata_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(metadata) + "\n")

    def _count_images(self, contents: bytes) -> int:
        try:
            with zipfile.ZipFile(BytesIO(contents), "r") as archive:
                return sum(1 for item in archive.infolist() if not item.is_dir())
        except zipfile.BadZipFile:
            return 0
