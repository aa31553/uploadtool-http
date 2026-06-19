from __future__ import annotations

import shutil
import zipfile
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
        raw_path = Path(str(job.payload["stored_path"]))
        batch_id = str(job.payload["job_id"])

        extract_dir = Path(self._config.temp_root) / "worker" / batch_id
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        output_dir = Path(self._config.processed_root) / machine_id
        output_dir.mkdir(parents=True, exist_ok=True)

        processed_files: list[str] = []
        with zipfile.ZipFile(raw_path, "r") as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if not members:
                raise ValueError("No files found in uploaded batch")

            image_count = 0
            for member in members:
                relative_member = self._normalized_archive_path(member.filename)
                extract_path = extract_dir / relative_member
                extract_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source_handle, extract_path.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle)

                if extract_path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue

                image_count += 1
                destination_dir = output_dir / relative_member.parent
                destination_dir.mkdir(parents=True, exist_ok=True)
                if Image is not None:
                    destination = self._unique_destination(destination_dir / f"{extract_path.stem}.webp")
                    with Image.open(extract_path) as image:
                        converted = image.convert("RGB") if image.mode not in {"RGB", "L"} else image
                        converted.save(destination, format="WEBP", quality=75)
                else:
                    destination = self._unique_destination(destination_dir / extract_path.name)
                    shutil.copy2(extract_path, destination)
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

    def _normalized_archive_path(self, member_name: str) -> Path:
        raw_parts = [part for part in member_name.replace("\\", "/").split("/") if part not in {"", "."}]
        if not raw_parts:
            raise ValueError("Batch contains empty archive member path")
        if any(part == ".." for part in raw_parts):
            raise ValueError(f"Unsafe archive member path: {member_name}")
        normalized = Path(*raw_parts)
        if normalized.is_absolute():
            raise ValueError(f"Unsafe archive member path: {member_name}")
        return normalized

    def _unique_destination(self, destination: Path) -> Path:
        candidate = destination
        counter = 1
        while candidate.exists():
            candidate = destination.with_name(f"{destination.stem}_{counter}{destination.suffix}")
            counter += 1
        return candidate
