from __future__ import annotations

import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from server.config import ServerConfig
from server.queue import QueueJob

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class JobProcessor:
    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        Path(self._config.processed_root).mkdir(parents=True, exist_ok=True)
        Path(self._config.failed_root).mkdir(parents=True, exist_ok=True)
        Path(self._config.temp_root).mkdir(parents=True, exist_ok=True)

    def process(self, job: QueueJob) -> dict[str, object]:
        machine_id = str(job.payload["machine_id"])
        timestamp = datetime.fromisoformat(str(job.payload["timestamp"]))
        raw_path = Path(str(job.payload["stored_path"]))
        batch_id = str(job.payload["job_id"])

        extract_dir = Path(self._config.temp_root) / "worker" / batch_id
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        output_dir = Path(self._config.processed_root) / machine_id / timestamp.strftime("%Y/%m/%d")
        output_dir.mkdir(parents=True, exist_ok=True)

        processed_files: list[str] = []
        with zipfile.ZipFile(raw_path, "r") as archive:
            archive.extractall(extract_dir)

        extracted_files = sorted(path for path in extract_dir.rglob("*") if path.is_file())
        if not extracted_files:
            raise ValueError("No files found in uploaded batch")

        image_count = 0
        for path in extracted_files:
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            image_count += 1
            destination = output_dir / f"{path.stem}.webp"
            counter = 1
            while destination.exists():
                destination = output_dir / f"{path.stem}_{counter}.webp"
                counter += 1
            if Image is not None:
                with Image.open(path) as image:
                    converted = image.convert("RGB") if image.mode not in {"RGB", "L"} else image
                    converted.save(destination, format="WEBP", quality=75)
            else:
                destination = output_dir / path.name
                shutil.copy2(path, destination)
            processed_files.append(str(destination))

        if image_count == 0:
            raise ValueError("Batch contains no supported image files")

        shutil.rmtree(extract_dir, ignore_errors=True)
        return {
            "processed_count": image_count,
            "processed_files": processed_files,
            "processed_root": str(output_dir),
        }

    def handle_failure(self, job: QueueJob) -> str:
        raw_path = Path(str(job.payload["stored_path"]))
        destination_dir = Path(self._config.failed_root) / str(job.payload["machine_id"])
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / raw_path.name
        if raw_path.exists() and not destination.exists():
            shutil.copy2(raw_path, destination)
        return str(destination)
