from __future__ import annotations

import time
from datetime import datetime, timezone

from server.config import ServerConfig
from server.queue import FileQueue
from worker.processor import JobProcessor
from worker.state import WorkerStateStore


class WorkerService:
    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._queue = FileQueue(config)
        self._processor = JobProcessor(config)
        self._state_store = WorkerStateStore(config)
        self._processed_jobs = 0
        self._failed_jobs = 0
        self._last_error = ""

    def run_forever(self) -> None:
        while True:
            loop_started = time.perf_counter()
            job = self._queue.claim_next()
            if job is None:
                self._write_state("idle", None, 0.0, 0.0)
                time.sleep(1)
                continue

            process_started = time.perf_counter()
            try:
                result = self._processor.process(job)
                duration = max(time.perf_counter() - process_started, 0.001)
                processing_rate = float(result["processed_count"]) / duration
                self._queue.mark_completed(job, result)
                self._processed_jobs += 1
                self._last_error = ""
                utilization = min(100.0, ((time.perf_counter() - loop_started) / max(duration, 0.001)) * 100.0)
                self._write_state("processing", job.job_id, processing_rate, utilization)
            except Exception as exc:  # noqa: BLE001
                self._failed_jobs += 1
                self._last_error = str(exc)
                failed_copy = self._processor.handle_failure(job)
                retry = int(job.payload.get("attempts", 0)) < 3
                self._queue.mark_failed(job, f"{exc}; failed_copy={failed_copy}", retry=retry)
                self._write_state("error", job.job_id, 0.0, 100.0)
                time.sleep(1)

    def _write_state(self, status: str, current_job_id: str | None, processing_rate: float, worker_utilization: float) -> None:
        self._state_store.write(
            {
                "status": status,
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "current_job_id": current_job_id,
                "processed_jobs": self._processed_jobs,
                "failed_jobs": self._failed_jobs,
                "processing_rate": round(processing_rate, 2),
                "worker_utilization": round(worker_utilization, 1),
                "last_error": self._last_error,
            }
        )
