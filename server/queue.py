from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from server.config import ServerConfig


@dataclass
class QueueJob:
    job_id: str
    path: Path
    payload: dict[str, object]


class FileQueue:
    def __init__(self, config: ServerConfig) -> None:
        self._root = Path(config.queue_root)
        self._pending = self._root / "pending"
        self._processing = self._root / "processing"
        self._completed = self._root / "completed"
        self._failed = self._root / "failed"
        for path in [self._pending, self._processing, self._completed, self._failed]:
            path.mkdir(parents=True, exist_ok=True)

    def enqueue(self, payload: dict[str, object]) -> str:
        job_id = str(payload["job_id"])
        job_path = self._pending / f"{job_id}.json"
        payload = {**payload, "queued_at": datetime.now(timezone.utc).isoformat(), "status": "pending"}
        job_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return job_id

    def claim_next(self) -> QueueJob | None:
        pending_jobs = sorted(self._pending.glob("*.json"))
        if not pending_jobs:
            return None
        job_path = pending_jobs[0]
        processing_path = self._processing / job_path.name
        job_path.replace(processing_path)
        payload = json.loads(processing_path.read_text(encoding="utf-8"))
        payload["status"] = "processing"
        payload["processing_started_at"] = datetime.now(timezone.utc).isoformat()
        processing_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return QueueJob(job_id=processing_path.stem, path=processing_path, payload=payload)

    def mark_completed(self, job: QueueJob, result: dict[str, object]) -> None:
        payload = {**job.payload, **result, "status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}
        completed_path = self._completed / job.path.name
        completed_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        job.path.unlink(missing_ok=True)

    def mark_failed(self, job: QueueJob, error: str, retry: bool) -> None:
        attempts = int(job.payload.get("attempts", 0)) + 1
        payload = {
            **job.payload,
            "attempts": attempts,
            "last_error": error,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        target_dir = self._pending if retry else self._failed
        payload["status"] = "pending" if retry else "failed"
        target_path = target_dir / job.path.name
        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        job.path.unlink(missing_ok=True)

    def stats(self) -> dict[str, object]:
        pending_jobs = [json.loads(path.read_text(encoding="utf-8")) for path in self._pending.glob("*.json")]
        processing_jobs = [json.loads(path.read_text(encoding="utf-8")) for path in self._processing.glob("*.json")]
        per_machine: dict[str, int] = {}
        for payload in pending_jobs + processing_jobs:
            machine_id = str(payload.get("machine_id", "unknown"))
            per_machine[machine_id] = per_machine.get(machine_id, 0) + 1

        oldest_pending_age = 0.0
        if pending_jobs:
            queued_times = [datetime.fromisoformat(str(job["queued_at"])) for job in pending_jobs if job.get("queued_at")]
            if queued_times:
                oldest_pending_age = max((datetime.now(timezone.utc) - queued_at).total_seconds() for queued_at in queued_times)

        return {
            "pending": len(pending_jobs),
            "processing": len(processing_jobs),
            "completed": len(list(self._completed.glob("*.json"))),
            "failed": len(list(self._failed.glob("*.json"))),
            "per_machine": per_machine,
            "oldest_pending_age_sec": oldest_pending_age,
        }
