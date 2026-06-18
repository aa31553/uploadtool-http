from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from server.config import ServerConfig

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None


@dataclass
class QueueJob:
    job_id: str
    path: Path | None
    payload: dict[str, object]


class QueueBackend(Protocol):
    def enqueue(self, payload: dict[str, object]) -> str: ...
    def claim_next(self) -> QueueJob | None: ...
    def mark_completed(self, job: QueueJob, result: dict[str, object]) -> None: ...
    def mark_failed(self, job: QueueJob, error: str, retry: bool) -> None: ...
    def stats(self) -> dict[str, object]: ...
    def recover_processing_jobs(self) -> int: ...
    def job_status_map(self) -> dict[str, dict[str, object]]: ...


class FileQueue:
    def __init__(self, config: ServerConfig) -> None:
        self._root = Path(config.queue_root)
        self._pending = self._root / "pending"
        self._processing = self._root / "processing"
        self._completed = self._root / "completed"
        self._failed = self._root / "failed"
        for path in [self._pending, self._processing, self._completed, self._failed]:
            path.mkdir(parents=True, exist_ok=True)
        self.recover_processing_jobs()

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
        completed_path = self._completed / f"{job.job_id}.json"
        completed_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if job.path is not None:
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
        target_path = target_dir / f"{job.job_id}.json"
        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if job.path is not None:
            job.path.unlink(missing_ok=True)

    def stats(self) -> dict[str, object]:
        pending_jobs = [json.loads(path.read_text(encoding="utf-8")) for path in self._pending.glob("*.json")]
        processing_jobs = [json.loads(path.read_text(encoding="utf-8")) for path in self._processing.glob("*.json")]
        return _build_stats(
            pending_jobs=pending_jobs,
            processing_jobs=processing_jobs,
            completed_count=len(list(self._completed.glob("*.json"))),
            failed_count=len(list(self._failed.glob("*.json"))),
        )

    def recover_processing_jobs(self) -> int:
        recovered = 0
        for path in self._processing.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["status"] = "pending"
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            target = self._pending / path.name
            target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            path.unlink(missing_ok=True)
            recovered += 1
        return recovered

    def job_status_map(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for folder in [self._pending, self._processing, self._completed, self._failed]:
            for path in folder.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                result[str(payload.get("job_id", path.stem))] = payload
        return result


class RedisQueue:
    def __init__(self, config: ServerConfig) -> None:
        if redis is None:
            raise RuntimeError("redis package is not installed")
        self._client = redis.Redis.from_url(config.redis_url, decode_responses=True)
        self._prefix = "mius:queue"
        self.recover_processing_jobs()

    def enqueue(self, payload: dict[str, object]) -> str:
        job_id = str(payload["job_id"])
        payload = {**payload, "queued_at": datetime.now(timezone.utc).isoformat(), "status": "pending"}
        self._save_payload(job_id, payload)
        self._client.rpush(self._key("pending"), job_id)
        return job_id

    def claim_next(self) -> QueueJob | None:
        job_id = self._client.lpop(self._key("pending"))
        if job_id is None:
            return None
        self._client.rpush(self._key("processing"), job_id)
        payload = self._load_payload(job_id)
        payload["status"] = "processing"
        payload["processing_started_at"] = datetime.now(timezone.utc).isoformat()
        self._save_payload(job_id, payload)
        return QueueJob(job_id=job_id, path=None, payload=payload)

    def mark_completed(self, job: QueueJob, result: dict[str, object]) -> None:
        payload = {**job.payload, **result, "status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}
        self._save_payload(job.job_id, payload)
        self._client.lrem(self._key("processing"), 1, job.job_id)
        self._client.rpush(self._key("completed"), job.job_id)

    def mark_failed(self, job: QueueJob, error: str, retry: bool) -> None:
        attempts = int(job.payload.get("attempts", 0)) + 1
        payload = {**job.payload, "attempts": attempts, "last_error": error, "updated_at": datetime.now(timezone.utc).isoformat()}
        self._save_payload(job.job_id, payload)
        self._client.lrem(self._key("processing"), 1, job.job_id)
        if retry:
            payload["status"] = "pending"
            self._save_payload(job.job_id, payload)
            self._client.rpush(self._key("pending"), job.job_id)
        else:
            payload["status"] = "failed"
            self._save_payload(job.job_id, payload)
            self._client.rpush(self._key("failed"), job.job_id)

    def stats(self) -> dict[str, object]:
        pending_ids = self._client.lrange(self._key("pending"), 0, -1)
        processing_ids = self._client.lrange(self._key("processing"), 0, -1)
        pending_jobs = [self._load_payload(job_id) for job_id in pending_ids]
        processing_jobs = [self._load_payload(job_id) for job_id in processing_ids]
        return _build_stats(
            pending_jobs=pending_jobs,
            processing_jobs=processing_jobs,
            completed_count=self._client.llen(self._key("completed")),
            failed_count=self._client.llen(self._key("failed")),
        )

    def recover_processing_jobs(self) -> int:
        recovered = 0
        processing_ids = self._client.lrange(self._key("processing"), 0, -1)
        for job_id in processing_ids:
            payload = self._load_payload(job_id)
            payload["status"] = "pending"
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_payload(job_id, payload)
            self._client.lrem(self._key("processing"), 1, job_id)
            self._client.rpush(self._key("pending"), job_id)
            recovered += 1
        return recovered

    def job_status_map(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        keys = self._client.keys(f"{self._prefix}:job:*")
        for key in keys:
            job_id = key.rsplit(":", 1)[-1]
            result[job_id] = self._load_payload(job_id)
        return result

    def _key(self, name: str) -> str:
        return f"{self._prefix}:{name}"

    def _job_key(self, job_id: str) -> str:
        return f"{self._prefix}:job:{job_id}"

    def _load_payload(self, job_id: str) -> dict[str, object]:
        raw = self._client.get(self._job_key(job_id))
        return {} if raw is None else json.loads(raw)

    def _save_payload(self, job_id: str, payload: dict[str, object]) -> None:
        self._client.set(self._job_key(job_id), json.dumps(payload))


def create_queue(config: ServerConfig) -> QueueBackend:
    if config.queue_backend == "redis":
        return RedisQueue(config)
    return FileQueue(config)


def _build_stats(pending_jobs: list[dict[str, object]], processing_jobs: list[dict[str, object]], completed_count: int, failed_count: int) -> dict[str, object]:
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
        "completed": int(completed_count),
        "failed": int(failed_count),
        "per_machine": per_machine,
        "oldest_pending_age_sec": oldest_pending_age,
    }
