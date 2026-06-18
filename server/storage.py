from __future__ import annotations

import json
import hashlib
import shutil
import threading
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from server.config import ServerConfig
from server.queue import QueueBackend


class UploadStorage:
    def __init__(self, config: ServerConfig, queue: QueueBackend) -> None:
        self._config = config
        self._queue = queue
        self._lock = threading.Lock()
        Path(self._config.storage_root).mkdir(parents=True, exist_ok=True)
        Path(self._config.temp_root).mkdir(parents=True, exist_ok=True)
        Path(self._config.processed_root).mkdir(parents=True, exist_ok=True)
        Path(self._config.failed_root).mkdir(parents=True, exist_ok=True)
        Path(self._config.metadata_path).parent.mkdir(parents=True, exist_ok=True)
        self._idempotency_index_path = Path(self._config.idempotency_index_path)
        self._idempotency_index_path.parent.mkdir(parents=True, exist_ok=True)

    async def save_upload(
        self,
        machine_id: str,
        timestamp: datetime,
        batch_file: UploadFile,
        idempotency_key: str,
        checksum_sha256: str,
    ) -> tuple[str, dict[str, object], bool]:
        duplicate_metadata = self._lookup_idempotency(idempotency_key)
        if duplicate_metadata is not None:
            return str(duplicate_metadata["stored_path"]), duplicate_metadata, True

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
        actual_checksum = hashlib.sha256(contents).hexdigest()
        if checksum_sha256 != actual_checksum:
            raise ValueError("E201 checksum mismatch; client should retry batch upload")

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
            "checksum_sha256": actual_checksum,
            "idempotency_key": idempotency_key,
        }
        self._append_metadata(metadata)
        self._queue.enqueue(metadata)
        self._remember_idempotency(idempotency_key, metadata)
        return str(stored_path), metadata, False

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

    def disk_usage_percent(self) -> float:
        usage = shutil.disk_usage(self._config.storage_root)
        return (usage.used / usage.total) * 100 if usage.total else 0.0

    def max_disk_usage_percent(self) -> int:
        return self._config.max_disk_usage_percent

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

    def _lookup_idempotency(self, idempotency_key: str) -> dict[str, object] | None:
        if not self._idempotency_index_path.exists():
            return None
        try:
            index = json.loads(self._idempotency_index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return index.get(idempotency_key)

    def _remember_idempotency(self, idempotency_key: str, metadata: dict[str, object]) -> None:
        with self._lock:
            index: dict[str, dict[str, object]] = {}
            if self._idempotency_index_path.exists():
                try:
                    index = json.loads(self._idempotency_index_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    index = {}
            index[idempotency_key] = metadata
            self._idempotency_index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
