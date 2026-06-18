from __future__ import annotations

from datetime import datetime, timedelta, timezone
from random import randint, uniform

from server.models import AlertItem, MachineStatus, QueueStatus, ServerMetrics, StorageStatus


class InMemoryStore:
    def __init__(self, machine_ids: list[str] | None = None) -> None:
        now = datetime.now(timezone.utc)
        self._machine_ids = machine_ids or [f"MC{i:02d}" for i in range(1, 6)]
        self._last_uploads = {machine_id: now for machine_id in self._machine_ids}
        self._queue_sizes = {machine_id: 0 for machine_id in self._machine_ids}

    def register_upload(self, machine_id: str) -> None:
        now = datetime.now(timezone.utc)
        if machine_id not in self._machine_ids:
            self._machine_ids.append(machine_id)
        self._last_uploads[machine_id] = now
        self._queue_sizes[machine_id] = max(0, self._queue_sizes.get(machine_id, 0) - 1)

    def machines(self) -> list[MachineStatus]:
        now = datetime.now(timezone.utc)
        machines: list[MachineStatus] = []
        for index, machine_id in enumerate(self._machine_ids):
            last_upload = self._last_uploads.get(machine_id, now - timedelta(minutes=5))
            age_seconds = (now - last_upload).total_seconds()
            status = "offline" if age_seconds > 120 else ("warning" if age_seconds > 10 or index == 2 else "online")
            queue_size = self._queue_sizes.get(machine_id, 0) + randint(0, 20 if status == "online" else 80)
            machines.append(
                MachineStatus(
                    machine_id=machine_id,
                    status=status,
                    fps=round(uniform(9.6, 10.4), 1),
                    latency_ms=randint(100, 240 if status == "warning" else 160),
                    queue_size=queue_size,
                    last_upload=last_upload,
                )
            )
        return machines

    def server_metrics(self) -> ServerMetrics:
        now = datetime.now(timezone.utc)
        return ServerMetrics(
            cpu_percent=round(uniform(55, 78), 1),
            ram_percent=round(uniform(48, 68), 1),
            disk_percent=round(uniform(70, 89), 1),
            net_in_mbps=round(uniform(250, 340), 1),
            net_out_mbps=round(uniform(210, 300), 1),
            disk_read_mbps=round(uniform(120, 180), 1),
            disk_write_mbps=round(uniform(180, 260), 1),
            updated_at=now,
        )

    def queue_status(self) -> QueueStatus:
        now = datetime.now(timezone.utc)
        return QueueStatus(
            queue_length=randint(900, 1400),
            processing_rate=round(uniform(920, 1020), 1),
            backlog_delta=randint(-40, 260),
            worker_utilization=round(uniform(72, 96), 1),
            updated_at=now,
        )

    def storage_status(self) -> StorageStatus:
        now = datetime.now(timezone.utc)
        total_tb = 100.0
        used_tb = round(uniform(68, 90), 1)
        usage_percent = round(used_tb / total_tb * 100, 1)
        return StorageStatus(
            total_tb=total_tb,
            used_tb=used_tb,
            usage_percent=usage_percent,
            growth_tb_per_day=round(uniform(1.2, 2.1), 2),
            eta_full_days=round(uniform(2.0, 8.0), 1),
            updated_at=now,
        )

    def alerts(self) -> list[AlertItem]:
        now = datetime.now(timezone.utc)
        alerts: list[AlertItem] = []
        for machine in self.machines():
            if machine.status == "offline":
                alerts.append(
                    AlertItem(
                        level="critical",
                        message=f"{machine.machine_id} offline",
                        source=f"machine:{machine.machine_id}",
                        created_at=now,
                    )
                )
        alerts.append(AlertItem(level="warning", message="Queue backlog increasing", source="queue", created_at=now))
        return alerts


store = InMemoryStore()
