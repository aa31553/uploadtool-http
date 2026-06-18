from __future__ import annotations

import json
import math
import os
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from server.config import ServerConfig
from server.models import AlertItem, ImageFlowBatch, MachineDetail, MachineStatus, QueueStatus, ServerMetrics, StorageStatus, WorkerState
from server.queue import FileQueue
from worker.state import WorkerStateStore


class RuntimeStore:
    def __init__(self) -> None:
        self._config: ServerConfig | None = None
        self._queue: FileQueue | None = None
        self._worker_state_store: WorkerStateStore | None = None

    def configure(self, config: ServerConfig, queue: FileQueue) -> None:
        self._config = config
        self._queue = queue
        self._worker_state_store = WorkerStateStore(config)

    def machines(self) -> list[MachineStatus]:
        config, queue = self._require_runtime()
        events = self._recent_upload_events(hours=1)
        per_machine_queue = dict(queue.stats()["per_machine"])
        now = datetime.now(timezone.utc)
        machine_statuses: list[MachineStatus] = []

        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for event in events:
            grouped[str(event["machine_id"])].append(event)

        for machine_id in config.machines:
            machine_events = grouped.get(machine_id, [])
            last_upload = max(
                (self._parse_timestamp(str(event["received_at"])) for event in machine_events if event.get("received_at")),
                default=now - timedelta(minutes=10),
            )
            recent_window = now - timedelta(seconds=10)
            recent_events = [event for event in machine_events if self._parse_timestamp(str(event["received_at"])) >= recent_window]
            image_count = sum(int(event.get("image_count", 0)) for event in recent_events)
            fps = round(image_count / 10.0, 1)
            latency_ms = 0
            if machine_events:
                latest = sorted(machine_events, key=lambda item: str(item.get("received_at", "")))[-1]
                src_ts = self._parse_timestamp(str(latest["timestamp"]))
                recv_ts = self._parse_timestamp(str(latest["received_at"]))
                latency_ms = max(0, int((recv_ts - src_ts).total_seconds() * 1000))
            age_seconds = (now - last_upload).total_seconds()
            queue_size = per_machine_queue.get(machine_id, 0)
            status = "online"
            if age_seconds > 120:
                status = "offline"
            elif queue_size > 5 or age_seconds > 10:
                status = "warning"

            machine_statuses.append(
                MachineStatus(
                    machine_id=machine_id,
                    status=status,
                    fps=fps,
                    latency_ms=latency_ms,
                    queue_size=queue_size,
                    last_upload=last_upload,
                )
            )
        return machine_statuses

    def server_metrics(self) -> ServerMetrics:
        config, _queue = self._require_runtime()
        now = datetime.now(timezone.utc)
        load_avg_1, load_avg_5, load_avg_15 = os.getloadavg()
        cpu_percent = round(min(100.0, load_avg_1 / max(os.cpu_count() or 1, 1) * 100.0), 1)
        ram_percent = round(self._memory_usage_percent(), 1)
        disk_usage = shutil.disk_usage(config.storage_root)
        disk_percent = round((disk_usage.used / disk_usage.total) * 100.0, 1)
        upload_bytes = self._bytes_in_recent_uploads(seconds=60)
        processed_bytes = self._directory_size(Path(config.processed_root), seconds=60)
        upload_mbps = round(upload_bytes / 60 / 1024 / 1024, 2)
        processed_mbps = round(processed_bytes / 60 / 1024 / 1024, 2)
        return ServerMetrics(
            cpu_percent=cpu_percent,
            ram_percent=ram_percent,
            disk_percent=disk_percent,
            net_in_mbps=upload_mbps,
            net_out_mbps=processed_mbps,
            disk_read_mbps=processed_mbps,
            disk_write_mbps=upload_mbps,
            load_avg_1=round(load_avg_1, 2),
            load_avg_5=round(load_avg_5, 2),
            load_avg_15=round(load_avg_15, 2),
            updated_at=now,
        )

    def queue_status(self) -> QueueStatus:
        _config, queue = self._require_runtime()
        stats = queue.stats()
        worker = self.worker_state()
        backlog_delta = stats["pending"] - stats["processing"]
        return QueueStatus(
            queue_length=int(stats["pending"]) + int(stats["processing"]),
            processing_rate=worker.processing_rate,
            backlog_delta=backlog_delta,
            worker_utilization=worker.worker_utilization,
            per_machine=dict(stats["per_machine"]),
            updated_at=datetime.now(timezone.utc),
        )

    def storage_status(self) -> StorageStatus:
        config, _queue = self._require_runtime()
        usage = shutil.disk_usage(config.storage_root)
        raw_bytes = self._directory_size(Path(config.storage_root) / "raw")
        processed_bytes = self._directory_size(Path(config.processed_root))
        failed_bytes = self._directory_size(Path(config.failed_root))
        used_tb = usage.used / 1024 / 1024 / 1024 / 1024
        total_tb = usage.total / 1024 / 1024 / 1024 / 1024
        growth_tb_per_day = self._bytes_in_recent_uploads(seconds=86400) / 1024 / 1024 / 1024 / 1024
        remaining_tb = max(total_tb - used_tb, 0.0001)
        eta_days = remaining_tb / max(growth_tb_per_day, 0.0001)
        return StorageStatus(
            total_tb=round(total_tb, 2),
            used_tb=round(used_tb, 2),
            usage_percent=round((usage.used / usage.total) * 100.0, 1),
            raw_used_gb=round(raw_bytes / 1024 / 1024 / 1024, 2),
            processed_used_gb=round(processed_bytes / 1024 / 1024 / 1024, 2),
            failed_used_gb=round(failed_bytes / 1024 / 1024 / 1024, 2),
            growth_tb_per_day=round(growth_tb_per_day, 4),
            eta_full_days=round(eta_days, 1),
            updated_at=datetime.now(timezone.utc),
        )

    def worker_state(self) -> WorkerState:
        _config, _queue = self._require_runtime()
        payload = self._worker_state_store.read() if self._worker_state_store is not None else {}
        heartbeat = payload.get("heartbeat_at")
        updated_at = payload.get("updated_at")
        return WorkerState(
            status=str(payload.get("status", "unknown")),
            heartbeat_at=self._parse_timestamp(heartbeat) if heartbeat else None,
            current_job_id=payload.get("current_job_id"),
            processed_jobs=int(payload.get("processed_jobs", 0)),
            failed_jobs=int(payload.get("failed_jobs", 0)),
            processing_rate=float(payload.get("processing_rate", 0.0)),
            worker_utilization=float(payload.get("worker_utilization", 0.0)),
            last_error=str(payload.get("last_error", "")),
            updated_at=self._parse_timestamp(updated_at) if updated_at else None,
        )

    def alerts(self) -> list[AlertItem]:
        now = datetime.now(timezone.utc)
        alerts: list[AlertItem] = []
        for machine in self.machines():
            if machine.status == "offline":
                alerts.append(AlertItem(level="critical", message=f"{machine.machine_id} offline", source=f"machine:{machine.machine_id}", created_at=now))
            elif machine.queue_size > 5:
                alerts.append(AlertItem(level="warning", message=f"{machine.machine_id} queue backlog {machine.queue_size}", source=f"machine:{machine.machine_id}", created_at=now))

        queue_status = self.queue_status()
        if queue_status.queue_length > 10:
            alerts.append(AlertItem(level="warning", message="Queue backlog increasing", source="queue", created_at=now))

        storage = self.storage_status()
        if storage.usage_percent > 85:
            alerts.append(AlertItem(level="critical", message=f"Disk usage {storage.usage_percent}%", source="storage", created_at=now))

        worker = self.worker_state()
        if worker.heartbeat_at is None or (now - worker.heartbeat_at).total_seconds() > 30:
            alerts.append(AlertItem(level="warning", message="Worker heartbeat stale", source="worker", created_at=now))
        elif worker.last_error:
            alerts.append(AlertItem(level="warning", message=worker.last_error, source="worker", created_at=now))
        return alerts

    def machine_detail(self, machine_id: str) -> MachineDetail | None:
        machine = next((item for item in self.machines() if item.machine_id == machine_id), None)
        if machine is None:
            return None
        recent_batches = self.recent_batches(machine_id=machine_id, limit=12)
        queue_depth = self.queue_status().per_machine.get(machine_id, 0)
        return MachineDetail(
            machine=machine,
            recent_batches=recent_batches,
            queue_depth=queue_depth,
            recent_upload_count=len(recent_batches),
        )

    def recent_batches(self, machine_id: str | None = None, limit: int = 20) -> list[ImageFlowBatch]:
        job_map = self._job_status_map()
        events = self._recent_upload_events(hours=24)
        batches: list[ImageFlowBatch] = []
        for event in reversed(events):
            if machine_id is not None and str(event.get("machine_id")) != machine_id:
                continue
            job_id = str(event.get("job_id", ""))
            job_payload = job_map.get(job_id, {})
            batches.append(
                ImageFlowBatch(
                    job_id=job_id,
                    machine_id=str(event.get("machine_id", "unknown")),
                    batch_filename=event.get("batch_filename"),
                    status=str(job_payload.get("status", "uploaded")),
                    image_count=int(event.get("image_count", 0)),
                    stored_path=str(event.get("stored_path", "")),
                    processed_root=job_payload.get("processed_root"),
                    queued_at=self._parse_timestamp(str(job_payload["queued_at"])) if job_payload.get("queued_at") else None,
                    received_at=self._parse_timestamp(str(event["received_at"])) if event.get("received_at") else None,
                    completed_at=self._parse_timestamp(str(job_payload["completed_at"])) if job_payload.get("completed_at") else None,
                    last_error=str(job_payload.get("last_error")) if job_payload.get("last_error") else None,
                )
            )
            if len(batches) >= limit:
                break
        return batches

    def _require_runtime(self) -> tuple[ServerConfig, FileQueue]:
        if self._config is None or self._queue is None:
            raise RuntimeError("Runtime store is not configured")
        return self._config, self._queue

    def _recent_upload_events(self, hours: int) -> list[dict[str, object]]:
        config, _queue = self._require_runtime()
        path = Path(config.metadata_path)
        if not path.exists():
            return []
        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        events: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            received_at = item.get("received_at")
            if received_at and self._parse_timestamp(str(received_at)) >= threshold:
                events.append(item)
        return events

    def _bytes_in_recent_uploads(self, seconds: int) -> int:
        threshold = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        total = 0
        for event in self._recent_upload_events(hours=max(1, math.ceil(seconds / 3600))):
            received_at = event.get("received_at")
            if not received_at:
                continue
            when = self._parse_timestamp(str(received_at))
            if when >= threshold:
                total += int(event.get("size_bytes", 0))
        return total

    def _memory_usage_percent(self) -> float:
        meminfo_path = Path("/proc/meminfo")
        if not meminfo_path.exists():
            return 0.0
        fields: dict[str, int] = {}
        for line in meminfo_path.read_text(encoding="utf-8").splitlines():
            key, rest = line.split(":", 1)
            fields[key] = int(rest.strip().split()[0])
        total = fields.get("MemTotal", 0)
        available = fields.get("MemAvailable", 0)
        if total == 0:
            return 0.0
        return ((total - available) / total) * 100.0

    def _directory_size(self, path: Path, seconds: int | None = None) -> int:
        if not path.exists():
            return 0
        threshold = None if seconds is None else datetime.now(timezone.utc).timestamp() - seconds
        total = 0
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            if threshold is not None and file_path.stat().st_mtime < threshold:
                continue
            total += file_path.stat().st_size
        return total

    def _parse_timestamp(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _job_status_map(self) -> dict[str, dict[str, object]]:
        config, _queue = self._require_runtime()
        result: dict[str, dict[str, object]] = {}
        for folder_name in ["pending", "processing", "completed", "failed"]:
            directory = Path(config.queue_root) / folder_name
            if not directory.exists():
                continue
            for path in directory.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                job_id = str(payload.get("job_id", path.stem))
                result[job_id] = payload
        return result


store = RuntimeStore()
