from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from machine_client.config import AppConfig


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class BatchRecord:
    batch_id: str
    zip_path: Path
    manifest_path: Path
    image_count: int
    attempts: int


class DiskQueue:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._root = Path(config.storage.buffer_path)
        self._staged_dir = self._root / "staged"
        self._ready_dir = self._root / "ready"
        self._inflight_dir = self._root / "inflight"
        self._sent_dir = self._root / "sent"
        self._failed_dir = self._root / "failed"
        self._manifests_dir = self._root / "manifests"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        for path in [
            self._root,
            self._staged_dir,
            self._ready_dir,
            self._inflight_dir,
            self._sent_dir,
            self._failed_dir,
            self._manifests_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def stage_new_images(self, min_age_seconds: int = 2) -> int:
        image_root = Path(self._config.storage.image_root)
        if not image_root.exists():
            return 0

        now = datetime.now(timezone.utc).timestamp()
        moved = 0
        for path in sorted(image_root.iterdir()):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if now - path.stat().st_mtime < min_age_seconds:
                continue

            destination = self._staged_dir / path.name
            counter = 1
            while destination.exists():
                destination = self._staged_dir / f"{path.stem}_{counter}{path.suffix}"
                counter += 1
            shutil.move(str(path), str(destination))
            moved += 1
        return moved

    def maybe_build_batch(self) -> BatchRecord | None:
        staged_files = sorted(path for path in self._staged_dir.iterdir() if path.is_file())
        if not staged_files:
            return None

        if len(staged_files) < self._config.upload.batch_size:
            oldest_age = datetime.now(timezone.utc).timestamp() - staged_files[0].stat().st_mtime
            if oldest_age < self._config.upload.interval_sec:
                return None

        selected = staged_files[: self._config.upload.batch_size]
        batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        zip_path = self._ready_dir / f"{batch_id}.zip"
        manifest_path = self._manifests_dir / f"{batch_id}.json"

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in selected:
                archive.write(file_path, arcname=file_path.name)

        manifest = {
            "batch_id": batch_id,
            "machine_id": self._config.machine_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "images": [str(path.name) for path in selected],
            "attempts": 0,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return BatchRecord(
            batch_id=batch_id,
            zip_path=zip_path,
            manifest_path=manifest_path,
            image_count=len(selected),
            attempts=0,
        )

    def next_ready_batch(self) -> BatchRecord | None:
        ready_files = sorted(self._ready_dir.glob("*.zip"))
        if not ready_files:
            return None

        zip_path = ready_files[0]
        inflight_path = self._inflight_dir / zip_path.name
        zip_path.replace(inflight_path)

        batch_id = inflight_path.stem
        manifest_path = self._manifests_dir / f"{batch_id}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return BatchRecord(
            batch_id=batch_id,
            zip_path=inflight_path,
            manifest_path=manifest_path,
            image_count=len(manifest["images"]),
            attempts=int(manifest.get("attempts", 0)),
        )

    def mark_uploaded(self, batch: BatchRecord) -> None:
        manifest = json.loads(batch.manifest_path.read_text(encoding="utf-8"))
        for image_name in manifest["images"]:
            staged_path = self._staged_dir / image_name
            if staged_path.exists():
                staged_path.unlink()

        sent_path = self._sent_dir / batch.zip_path.name
        batch.zip_path.replace(sent_path)
        batch.manifest_path.unlink(missing_ok=True)

    def mark_failed(self, batch: BatchRecord) -> None:
        manifest = json.loads(batch.manifest_path.read_text(encoding="utf-8"))
        manifest["attempts"] = int(manifest.get("attempts", 0)) + 1
        batch.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        target_dir = self._failed_dir if manifest["attempts"] >= self._config.upload.retry else self._ready_dir
        target_path = target_dir / batch.zip_path.name
        if batch.zip_path.exists():
            batch.zip_path.replace(target_path)

    def stats(self) -> dict[str, int]:
        staged_images = len(list(self._staged_dir.glob("*")))
        ready_batches = len(list(self._ready_dir.glob("*.zip")))
        inflight_batches = len(list(self._inflight_dir.glob("*.zip")))
        buffer_capacity = max(1000, self._config.upload.batch_size * 50)
        return {
            "staged_images": staged_images,
            "ready_batches": ready_batches,
            "inflight_batches": inflight_batches,
            "buffer_images": staged_images,
            "buffer_capacity": buffer_capacity,
        }
