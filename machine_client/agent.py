from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

from machine_client.config import AppConfig
from machine_client.disk_queue import DiskQueue
from machine_client.status import ClientStatus
from machine_client.transport import ConnectionTestResult, ServerClient
from machine_client.validation import validate_config


class AgentService:
    def __init__(self, config: AppConfig, config_path: Path) -> None:
        self._config = config
        self._config_path = Path(config_path)
        self._disk_queue = DiskQueue(config)
        self._server_client = ServerClient(config)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._logs: deque[str] = deque(maxlen=200)
        self._last_latency_ms = 0
        self._success_count = 0
        self._failure_count = 0
        self._last_error = ""
        self._queue_growth = 0.0
        self._message = "STARTING"
        self._test_connection_ok = False
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._log("INFO", "Agent initialized")
        self._worker.start()

    def snapshot(self) -> ClientStatus:
        with self._lock:
            stats = self._disk_queue.stats()
            total = self._success_count + self._failure_count
            success_rate = 100.0 if total == 0 else round(self._success_count / total * 100, 1)
            return ClientStatus(
                machine_id=self._config.machine_id,
                online=self._message == "ONLINE",
                fps=float(self._config.upload.batch_size / max(self._config.upload.interval_sec, 1)),
                upload_success_rate=success_rate,
                latency_ms=self._last_latency_ms,
                buffer_images=stats["buffer_images"],
                buffer_capacity=stats["buffer_capacity"],
                queue_growth_per_sec=self._queue_growth,
                message=self._message if not self._last_error else f"{self._message}: {self._last_error}",
            )

    def log_lines(self) -> list[str]:
        with self._lock:
            return list(self._logs)

    def test_connection(self) -> ConnectionTestResult:
        result = self._server_client.test_connection()
        with self._lock:
            self._test_connection_ok = result.ok
        self._log("INFO" if result.ok else "ERROR", result.message)
        return result

    def test_connection_for_config(self, config: AppConfig) -> ConnectionTestResult:
        errors = validate_config(config)
        if errors:
            return ConnectionTestResult(False, None, "; ".join(errors))
        result = ServerClient(config).test_connection()
        with self._lock:
            self._test_connection_ok = result.ok
        self._log("INFO" if result.ok else "ERROR", result.message)
        return result

    def update_config(self, config: AppConfig, require_connection_test: bool = False) -> list[str]:
        errors = validate_config(config)
        if require_connection_test and not self._test_connection_ok:
            errors.append("Run Test Connection successfully before saving network settings")
        if errors:
            return errors

        with self._lock:
            self._config = config
            self._disk_queue = DiskQueue(config)
            self._server_client = ServerClient(config)
            self._test_connection_ok = False
        from machine_client.config import save_config

        save_config(self._config_path, config)
        self._log("INFO", "Configuration saved")
        return []

    def stop(self) -> None:
        self._stop_event.set()
        self._worker.join(timeout=2)

    def _run_loop(self) -> None:
        previous_buffer = self._disk_queue.stats()["buffer_images"]
        while not self._stop_event.is_set():
            with self._lock:
                disk_queue = self._disk_queue
                server_client = self._server_client
                config = self._config

            staged = disk_queue.stage_new_images()
            if staged:
                self._log("INFO", f"Staged {staged} image(s) from image root")

            created = disk_queue.maybe_build_batch()
            if created is not None:
                self._log("INFO", f"Built batch {created.batch_id} with {created.image_count} image(s)")

            batch = disk_queue.next_ready_batch()
            if batch is not None:
                started = time.perf_counter()
                uploaded, _, detail = server_client.upload_batch(batch.zip_path)
                latency_ms = int((time.perf_counter() - started) * 1000)
                with self._lock:
                    self._last_latency_ms = latency_ms
                if uploaded:
                    disk_queue.mark_uploaded(batch)
                    with self._lock:
                        self._success_count += 1
                        self._message = "ONLINE"
                        self._last_error = ""
                    self._log("INFO", f"Uploaded {batch.batch_id} in {latency_ms} ms")
                else:
                    disk_queue.mark_failed(batch)
                    with self._lock:
                        self._failure_count += 1
                        self._message = "OFFLINE MODE"
                        self._last_error = detail
                    self._log("ERROR", f"Upload failed for {batch.batch_id} attempt {batch.attempts + 1}: {detail}")
            else:
                with self._lock:
                    if self._failure_count == 0:
                        self._message = "IDLE"

            current_buffer = disk_queue.stats()["buffer_images"]
            with self._lock:
                self._queue_growth = float(current_buffer - previous_buffer)
            previous_buffer = current_buffer

            self._cleanup_sent_batches(config)
            time.sleep(max(config.upload.interval_sec, 1))

    def _cleanup_sent_batches(self, config: AppConfig) -> None:
        sent_dir = Path(config.storage.buffer_path) / "sent"
        if not config.storage.auto_cleanup or not sent_dir.exists():
            return

        cutoff = time.time() - config.storage.retention_days * 86400
        for path in sent_dir.glob("*.zip"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)

    def _log(self, level: str, message: str) -> None:
        with self._lock:
            self._logs.appendleft(f"[{level}] {message}")
