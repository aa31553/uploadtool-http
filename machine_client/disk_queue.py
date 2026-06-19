from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from machine_client.config import AppConfig


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SCAN_ROOTS_PER_CYCLE = 4


@dataclass
class BatchRecord:
    batch_id: str
    zip_path: Path
    manifest_path: Path
    image_count: int
    attempts: int
    checksum_sha256: str
    idempotency_key: str


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
        self._source_index_path = self._root / "source-index.json"
        self._directory_index_path = self._root / "directory-index.json"
        self._staged_index_path = self._root / "staged-index.json"
        self._ensure_directories()
        self.recover_inflight()

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

        source_index = self._load_source_index()
        directory_index = self._load_directory_index()
        staged_index = self._load_staged_index()
        now = datetime.now(timezone.utc).timestamp()
        copied = 0
        scan_roots = self._collect_scan_roots(image_root)
        selected_roots, next_cursor = self._select_scan_roots(scan_roots, directory_index)

        for root in selected_roots:
            for path in self._iter_scan_root_files(root):
                if path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                if now - path.stat().st_mtime < min_age_seconds:
                    continue

                source_key = str(path.resolve())
                relative_path = str(path.relative_to(image_root).as_posix())
                source_signature = f"{path.stat().st_mtime_ns}:{path.stat().st_size}"
                indexed = source_index.get(source_key, {})
                last_signature = str(indexed.get("last_signature", ""))
                if last_signature == source_signature:
                    continue

                staged_relpath = self._build_staged_relpath(Path(relative_path), source_signature)
                destination = self._staged_dir / staged_relpath
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                staged_index[staged_relpath] = {
                    "staged_relpath": staged_relpath,
                    "relative_path": relative_path,
                    "source_key": source_key,
                    "source_signature": source_signature,
                    "staged_at": datetime.now(timezone.utc).isoformat(),
                    "scan_unit": root["key"],
                }
                source_index[source_key] = {
                    "last_signature": source_signature,
                    "relative_path": relative_path,
                    "last_staged_relpath": staged_relpath,
                    "last_seen_at": datetime.now(timezone.utc).isoformat(),
                }
                copied += 1

            directory_index["roots"][root["key"]] = {
                "kind": root["kind"],
                "signature": root["signature"],
                "last_scanned_at": datetime.now(timezone.utc).isoformat(),
            }

        directory_index["state"]["next_root_index"] = next_cursor
        self._prune_directory_index(directory_index, scan_roots)
        self._save_source_index(source_index)
        self._save_staged_index(staged_index)
        self._save_directory_index(directory_index)
        return copied

    def maybe_build_batch(self) -> BatchRecord | None:
        staged_index = self._load_staged_index()
        entries = self._ordered_staged_entries(staged_index)
        if not entries:
            return None

        selected = self._select_batch_entries(entries)
        if len(selected) < self._config.upload.batch_size:
            oldest_age = datetime.now(timezone.utc).timestamp() - self._staged_entry_timestamp(selected[0])
            if oldest_age < self._config.upload.interval_sec:
                return None

        batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        zip_path = self._ready_dir / f"{batch_id}.zip"
        manifest_path = self._manifests_dir / f"{batch_id}.json"

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in selected:
                staged_path = self._staged_dir / str(item["staged_relpath"])
                archive.write(staged_path, arcname=str(item["relative_path"]))

        checksum_sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        idempotency_key = f"{self._config.machine_id}:{batch_id}:{checksum_sha256[:16]}"
        path_mode = "relative_tree" if any("/" in str(item["relative_path"]) for item in selected) else "flat"

        manifest = {
            "batch_id": batch_id,
            "machine_id": self._config.machine_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "path_mode": path_mode,
            "images": [
                {
                    "name": Path(str(item["relative_path"])).name,
                    "relative_path": str(item["relative_path"]),
                    "staged_relpath": str(item["staged_relpath"]),
                    "source_key": str(item["source_key"]),
                    "source_signature": str(item["source_signature"]),
                }
                for item in selected
            ],
            "attempts": 0,
            "checksum_sha256": checksum_sha256,
            "idempotency_key": idempotency_key,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return BatchRecord(
            batch_id=batch_id,
            zip_path=zip_path,
            manifest_path=manifest_path,
            image_count=len(selected),
            attempts=0,
            checksum_sha256=checksum_sha256,
            idempotency_key=idempotency_key,
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
            checksum_sha256=str(manifest.get("checksum_sha256", "")),
            idempotency_key=str(manifest.get("idempotency_key", batch_id)),
        )

    def mark_uploaded(self, batch: BatchRecord) -> None:
        manifest = json.loads(batch.manifest_path.read_text(encoding="utf-8"))
        staged_index = self._load_staged_index()
        for image in manifest["images"]:
            staged_relpath = str(image.get("staged_relpath", image if isinstance(image, str) else image.get("name", "")))
            staged_path = self._staged_dir / staged_relpath
            if staged_path.exists():
                staged_path.unlink()
                self._cleanup_empty_staged_dirs(staged_path.parent)
            staged_index.pop(staged_relpath, None)

        sent_path = self._sent_dir / batch.zip_path.name
        batch.zip_path.replace(sent_path)
        batch.manifest_path.unlink(missing_ok=True)
        self._save_staged_index(staged_index)

    def mark_failed(self, batch: BatchRecord) -> None:
        manifest = json.loads(batch.manifest_path.read_text(encoding="utf-8"))
        manifest["attempts"] = int(manifest.get("attempts", 0)) + 1
        batch.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        target_dir = self._failed_dir if manifest["attempts"] >= self._config.upload.retry else self._ready_dir
        target_path = target_dir / batch.zip_path.name
        if batch.zip_path.exists():
            batch.zip_path.replace(target_path)

    def stats(self) -> dict[str, int]:
        staged_images = len([path for path in self._staged_dir.rglob("*") if path.is_file()])
        ready_batches = len(list(self._ready_dir.glob("*.zip")))
        inflight_batches = len(list(self._inflight_dir.glob("*.zip")))
        buffer_capacity = max(1000, self._config.upload.batch_size * 50)
        total, used, _free = shutil.disk_usage(self._root)
        disk_usage_percent = int((used / total) * 100) if total else 0
        return {
            "staged_images": staged_images,
            "ready_batches": ready_batches,
            "inflight_batches": inflight_batches,
            "buffer_images": staged_images,
            "buffer_capacity": buffer_capacity,
            "disk_usage_percent": disk_usage_percent,
        }

    def recover_inflight(self) -> int:
        recovered = 0
        for path in self._inflight_dir.glob("*.zip"):
            target = self._ready_dir / path.name
            path.replace(target)
            recovered += 1
        return recovered

    def _load_source_index(self) -> dict[str, dict[str, object]]:
        if not self._source_index_path.exists():
            return {}
        try:
            data = json.loads(self._source_index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        normalized: dict[str, dict[str, object]] = {}
        for key, value in data.items():
            if isinstance(value, str):
                normalized[str(key)] = {"last_signature": value}
            elif isinstance(value, dict):
                normalized[str(key)] = value
        return normalized

    def _save_source_index(self, source_index: dict[str, dict[str, object]]) -> None:
        self._source_index_path.write_text(json.dumps(source_index, indent=2), encoding="utf-8")

    def _load_directory_index(self) -> dict[str, object]:
        if not self._directory_index_path.exists():
            return {"state": {"next_root_index": 0}, "roots": {}}
        try:
            data = json.loads(self._directory_index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"state": {"next_root_index": 0}, "roots": {}}
        state = data.get("state") if isinstance(data, dict) else None
        roots = data.get("roots") if isinstance(data, dict) else None
        return {
            "state": state if isinstance(state, dict) else {"next_root_index": 0},
            "roots": roots if isinstance(roots, dict) else {},
        }

    def _save_directory_index(self, directory_index: dict[str, object]) -> None:
        self._directory_index_path.write_text(json.dumps(directory_index, indent=2), encoding="utf-8")

    def _load_staged_index(self) -> dict[str, dict[str, object]]:
        if not self._staged_index_path.exists():
            return {}
        try:
            data = json.loads(self._staged_index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        normalized: dict[str, dict[str, object]] = {}
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            staged_relpath = str(value.get("staged_relpath", key))
            staged_path = self._staged_dir / staged_relpath
            if staged_path.exists():
                normalized[staged_relpath] = value
        return normalized

    def _save_staged_index(self, staged_index: dict[str, dict[str, object]]) -> None:
        self._staged_index_path.write_text(json.dumps(staged_index, indent=2), encoding="utf-8")

    def _collect_scan_roots(self, image_root: Path) -> list[dict[str, object]]:
        roots: list[dict[str, object]] = []
        direct_files = [path for path in sorted(image_root.iterdir()) if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
        if direct_files:
            roots.append(
                {
                    "key": "__root_files__",
                    "path": image_root,
                    "kind": "direct_files",
                    "signature": self._scan_root_signature(image_root, direct_files_only=True),
                }
            )

        for top_level in sorted(path for path in image_root.iterdir() if path.is_dir()):
            direct_image_files = [path for path in sorted(top_level.iterdir()) if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
            if direct_image_files:
                roots.append(
                    {
                        "key": f"{top_level.name}/__files__",
                        "path": top_level,
                        "kind": "direct_files",
                        "signature": self._scan_root_signature(top_level, direct_files_only=True),
                    }
                )

            child_dirs = sorted(path for path in top_level.iterdir() if path.is_dir())
            if child_dirs:
                for child in child_dirs:
                    roots.append(
                        {
                            "key": child.relative_to(image_root).as_posix(),
                            "path": child,
                            "kind": "recursive_tree",
                            "signature": self._scan_root_signature(child),
                        }
                    )
            elif not direct_image_files:
                roots.append(
                    {
                        "key": top_level.relative_to(image_root).as_posix(),
                        "path": top_level,
                        "kind": "recursive_tree",
                        "signature": self._scan_root_signature(top_level),
                    }
                )
        return roots

    def _select_scan_roots(self, scan_roots: list[dict[str, object]], directory_index: dict[str, object]) -> tuple[list[dict[str, object]], int]:
        if not scan_roots:
            return [], 0
        scan_limit = min(SCAN_ROOTS_PER_CYCLE, len(scan_roots))
        stored_roots = directory_index.get("roots", {}) if isinstance(directory_index, dict) else {}
        changed = [root for root in scan_roots if stored_roots.get(root["key"], {}).get("signature") != root["signature"]]
        selected: list[dict[str, object]] = changed[:scan_limit]
        selected_keys = {str(root["key"]) for root in selected}

        next_cursor = int(directory_index.get("state", {}).get("next_root_index", 0)) if isinstance(directory_index.get("state", {}), dict) else 0
        if len(selected) < scan_limit:
            start = next_cursor % len(scan_roots)
            cursor = start
            for _ in range(len(scan_roots)):
                root = scan_roots[cursor]
                if str(root["key"]) not in selected_keys:
                    selected.append(root)
                    selected_keys.add(str(root["key"]))
                    if len(selected) >= scan_limit:
                        next_cursor = (cursor + 1) % len(scan_roots)
                        break
                cursor = (cursor + 1) % len(scan_roots)
            else:
                next_cursor = start
        return selected, next_cursor

    def _iter_scan_root_files(self, root: dict[str, object]) -> list[Path]:
        path = Path(str(root["path"]))
        if root["kind"] == "direct_files":
            return [item for item in sorted(path.iterdir()) if item.is_file()]
        return [item for item in sorted(path.rglob("*")) if item.is_file()]

    def _scan_root_signature(self, path: Path, direct_files_only: bool = False) -> str:
        stat = path.stat()
        if direct_files_only:
            file_count = len([item for item in path.iterdir() if item.is_file()])
        else:
            file_count = len([item for item in path.iterdir()])
        return f"{stat.st_mtime_ns}:{file_count}"

    def _build_staged_relpath(self, relative_path: Path, source_signature: str) -> str:
        short_hash = hashlib.sha1(f"{relative_path.as_posix()}:{source_signature}".encode("utf-8")).hexdigest()[:12]
        staged_name = f"{relative_path.stem}__{short_hash}{relative_path.suffix}"
        return (relative_path.parent / staged_name).as_posix()

    def _ordered_staged_entries(self, staged_index: dict[str, dict[str, object]]) -> list[dict[str, object]]:
        items = list(staged_index.values())
        items.sort(key=lambda item: (str(item.get("staged_at", "")), str(item.get("relative_path", "")), str(item.get("staged_relpath", ""))))
        return items

    def _select_batch_entries(self, entries: list[dict[str, object]]) -> list[dict[str, object]]:
        selected: list[dict[str, object]] = []
        used_relative_paths: set[str] = set()
        for entry in entries:
            relative_path = str(entry.get("relative_path", ""))
            if relative_path in used_relative_paths:
                continue
            selected.append(entry)
            used_relative_paths.add(relative_path)
            if len(selected) >= self._config.upload.batch_size:
                break
        return selected

    def _staged_entry_timestamp(self, entry: dict[str, object]) -> float:
        raw = str(entry.get("staged_at", ""))
        if raw:
            parsed = datetime.fromisoformat(raw)
            return parsed.timestamp()
        staged_path = self._staged_dir / str(entry["staged_relpath"])
        return staged_path.stat().st_mtime if staged_path.exists() else datetime.now(timezone.utc).timestamp()

    def _cleanup_empty_staged_dirs(self, directory: Path) -> None:
        current = directory
        while current != self._staged_dir and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _prune_directory_index(self, directory_index: dict[str, object], scan_roots: list[dict[str, object]]) -> None:
        valid_keys = {str(root["key"]) for root in scan_roots}
        roots = directory_index.get("roots", {}) if isinstance(directory_index, dict) else {}
        stale = [key for key in roots if key not in valid_keys]
        for key in stale:
            roots.pop(key, None)
