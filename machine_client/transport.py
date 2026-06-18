from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from machine_client.config import AppConfig


@dataclass
class ConnectionTestResult:
    ok: bool
    latency_ms: int | None
    message: str


class ServerClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def upload_batch(self, batch_path: Path) -> tuple[bool, int | None, str]:
        targets = [self._config.server.primary]
        if self._config.server.backup and self._config.server.backup not in targets:
            targets.append(self._config.server.backup)

        last_error = "No upload target configured"
        for url in targets:
            try:
                with batch_path.open("rb") as file_handle:
                    with httpx.Client(timeout=self._config.upload.timeout_sec) as client:
                        response = client.post(
                            url,
                            headers={"X-API-Token": self._config.server.token},
                            data={
                                "machine_id": self._config.machine_id,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                            files={"batch_file": (batch_path.name, file_handle, "application/zip")},
                        )
                response.raise_for_status()
                payload = response.json()
                return True, None, json.dumps(payload)
            except Exception as exc:  # noqa: BLE001
                last_error = f"{url}: {exc}"
        return False, None, last_error

    def test_connection(self) -> ConnectionTestResult:
        urls = [self._config.server.primary]
        if self._config.server.backup and self._config.server.backup not in urls:
            urls.append(self._config.server.backup)

        for url in urls:
            base_url = url.rsplit("/upload", 1)[0]
            try:
                with httpx.Client(timeout=self._config.upload.timeout_sec) as client:
                    health = client.get(f"{base_url}/healthz")
                    health.raise_for_status()

                    payload = io.BytesIO()
                    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                        archive.writestr("test.txt", "machine-client-connection-test")
                    payload.seek(0)

                    response = client.post(
                        url,
                        headers={"X-API-Token": self._config.server.token},
                        data={
                            "machine_id": self._config.machine_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        files={"batch_file": ("connection-test.zip", payload, "application/zip")},
                    )
                    response.raise_for_status()
                    latency_ms = int(response.elapsed.total_seconds() * 1000)
                    return ConnectionTestResult(True, latency_ms, f"Connected to {url}")
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return ConnectionTestResult(False, None, last_error)
