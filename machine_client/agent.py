from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path
from queue import Empty, Queue

from machine_client.config import AppConfig
from machine_client.disk_queue import DiskQueue, ScanCandidate
from machine_client.status import ClientStatus
from machine_client.transport import AuthResult, ConnectionTestResult, ServerClient
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
        self._auth_token = ""
        self._auth_employee_id = ""
        self._auth_role = ""
        self._last_disk_usage_percent = 0
        self._last_buffer_count = self._disk_queue.stats()["buffer_images"]
        self._copy_queue: Queue[ScanCandidate] = Queue()
        self._scan_worker = threading.Thread(target=self._scan_loop, daemon=True)
        self._copy_worker = threading.Thread(target=self._copy_loop, daemon=True)
        self._batch_worker = threading.Thread(target=self._batch_loop, daemon=True)
        self._log("INFO", "Agent initialized")
        self._scan_worker.start()
        self._copy_worker.start()
        self._batch_worker.start()

    def snapshot(self) -> ClientStatus:
        with self._lock:
            stats = self._disk_queue.stats()
            total = self._success_count + self._failure_count
            success_rate = 100.0 if total == 0 else round(self._success_count / total * 100, 1)
            return ClientStatus(
                machine_id=self._config.machine_id,
                online=self._message == "ONLINE",
                authenticated=bool(self._auth_token),
                current_user=self._auth_employee_id,
                current_role=self._auth_role,
                fps=float(self._config.upload.batch_size / max(self._config.upload.interval_sec, 1)),
                upload_success_rate=success_rate,
                latency_ms=self._last_latency_ms,
                buffer_images=stats["buffer_images"],
                buffer_capacity=stats["buffer_capacity"],
                queue_growth_per_sec=self._queue_growth,
                message=self._status_message(),
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

    def login_user(self, employee_id: str, password: str) -> AuthResult:
        result = self._server_client.login(employee_id, password)
        with self._lock:
            if result.ok and result.token:
                self._auth_token = result.token
                self._auth_employee_id = result.employee_id
                self._auth_role = result.role
        self._log("INFO" if result.ok else "ERROR", result.message)
        return result

    def logout_user(self) -> None:
        with self._lock:
            token = self._auth_token
            employee_id = self._auth_employee_id
            self._auth_token = ""
            self._auth_employee_id = ""
            self._auth_role = ""
        if token:
            self._server_client.logout(token)
            self._log("INFO", f"Logged out {employee_id}")

    def register_user(self, employee_id: str, display_name: str, password: str, role: str) -> tuple[bool, str]:
        with self._lock:
            token = self._auth_token
        if not token:
            return False, "Login required"
        ok, message = self._server_client.register_user(token, employee_id, display_name, password, role)
        self._log("INFO" if ok else "ERROR", message)
        return ok, message

    def change_password(self, current_password: str, new_password: str) -> tuple[bool, str]:
        with self._lock:
            token = self._auth_token
        if not token:
            return False, "Login required"
        ok, message = self._server_client.change_password(token, current_password, new_password)
        self._log("INFO" if ok else "ERROR", message)
        return ok, message

    def reset_password(self, employee_id: str, new_password: str) -> tuple[bool, str]:
        with self._lock:
            token = self._auth_token
        if not token:
            return False, "Login required"
        ok, message = self._server_client.reset_password(token, employee_id, new_password)
        self._log("INFO" if ok else "ERROR", message)
        return ok, message

    def is_authenticated(self) -> bool:
        with self._lock:
            return bool(self._auth_token)

    def is_admin(self) -> bool:
        with self._lock:
            return self._auth_role == "admin"

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
        if not self.is_authenticated():
            errors.append("Login is required before changing settings")
        if errors:
            return errors

        with self._lock:
            self._config = config
            self._disk_queue = DiskQueue(config)
            self._server_client = ServerClient(config)
            self._copy_queue = Queue()
            self._test_connection_ok = False
            self._last_buffer_count = self._disk_queue.stats()["buffer_images"]
        from machine_client.config import save_config

        save_config(self._config_path, config)
        self._log("INFO", "Configuration saved")
        return []

    def stop(self) -> None:
        self._stop_event.set()
        self._scan_worker.join(timeout=2)
        self._copy_worker.join(timeout=2)
        self._batch_worker.join(timeout=2)

    def _scan_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    disk_queue = self._disk_queue
                    config = self._config
                    copy_queue = self._copy_queue

                if not self._scan_allowed(config, disk_queue):
                    time.sleep(1)
                    continue

                candidates, indexed_only = disk_queue.scan_for_candidates(max_candidates=config.upload.stage_copy_limit_per_cycle)
                for candidate in candidates:
                    copy_queue.put(candidate)
                if indexed_only:
                    self._log("INFO", f"Indexed {indexed_only} existing image(s) without backfill")
                if candidates:
                    self._log("INFO", f"Queued {len(candidates)} image(s) for staging")
                self._update_queue_growth(disk_queue)
            except Exception as exc:  # noqa: BLE001
                self._log("ERROR", f"Scan loop error: {exc}")
            time.sleep(1)

    def _copy_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                disk_queue = self._disk_queue
                config = self._config
                copy_queue = self._copy_queue

            try:
                candidate = copy_queue.get(timeout=0.5)
            except Empty:
                continue

            if not self._scan_allowed(config, disk_queue):
                copy_queue.put(candidate)
                time.sleep(1)
                continue

            try:
                if disk_queue.stage_candidate(candidate):
                    self._log("INFO", f"Staged {candidate.relative_path}")
                self._update_queue_growth(disk_queue)
            except Exception as exc:  # noqa: BLE001
                self._log("ERROR", f"Copy loop error for {candidate.relative_path}: {exc}")

    def _batch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    disk_queue = self._disk_queue
                    server_client = self._server_client
                    config = self._config

                created = disk_queue.maybe_build_batch()
                if created is not None:
                    self._log("INFO", f"Built batch {created.batch_id} with {created.image_count} image(s)")

                batch = disk_queue.next_ready_batch()
                if batch is not None:
                    started = time.perf_counter()
                    uploaded, _, detail = server_client.upload_batch(
                        batch.zip_path,
                        batch.checksum_sha256,
                        batch.idempotency_key,
                    )
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
                        if self._failure_count == 0 and self._disk_queue.stats()["buffer_images"] == 0:
                            self._message = "IDLE"

                self._update_queue_growth(disk_queue)
                self._cleanup_sent_batches(config)
            except Exception as exc:  # noqa: BLE001
                self._log("ERROR", f"Batch loop error: {exc}")
            time.sleep(max(config.upload.interval_sec, 1))

    def _scan_allowed(self, config: AppConfig, disk_queue: DiskQueue) -> bool:
        stats = disk_queue.stats()
        disk_usage = stats["disk_usage_percent"]
        with self._lock:
            self._last_disk_usage_percent = disk_usage
        if disk_usage >= 90:
            with self._lock:
                self._message = "CRITICAL BUFFER PRESSURE"
                self._last_error = "E101 buffer disk above 90%; clear space or adjust cleanup"
            return False
        if disk_usage >= config.storage.max_usage_percent:
            with self._lock:
                self._message = "BUFFER WARNING"
                self._last_error = f"E102 buffer disk above {config.storage.max_usage_percent}%"
            return False
        with self._lock:
            if self._message in {"CRITICAL BUFFER PRESSURE", "BUFFER WARNING"}:
                self._message = "IDLE"
                self._last_error = ""
        return True

    def _update_queue_growth(self, disk_queue: DiskQueue) -> None:
        current_buffer = disk_queue.stats()["buffer_images"]
        with self._lock:
            self._queue_growth = float(current_buffer - self._last_buffer_count)
            self._last_buffer_count = current_buffer

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

    def _status_message(self) -> str:
        base = self._message
        if self._last_disk_usage_percent >= 90:
            base = f"{base} ({self._last_disk_usage_percent}% disk)"
        elif self._last_disk_usage_percent >= self._config.storage.max_usage_percent:
            base = f"{base} ({self._last_disk_usage_percent}% disk)"
        return base if not self._last_error else f"{base}: {self._last_error}"
