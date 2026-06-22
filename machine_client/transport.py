from __future__ import annotations

import io
import json
import hashlib
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


@dataclass
class AuthResult:
    ok: bool
    message: str
    token: str | None = None
    employee_id: str = ""
    role: str = ""


class ServerClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def login(self, employee_id: str, password: str) -> AuthResult:
        last_error = "No server configured"
        for base_url in self._control_urls():
            try:
                with httpx.Client(timeout=self._config.upload.timeout_sec) as client:
                    response = client.post(
                        f"{base_url}/api/auth/login",
                        json={
                            "employee_id": employee_id,
                            "password": password,
                            "client_type": "machine-client",
                            "client_id": self._config.machine_id,
                        },
                    )
                response.raise_for_status()
                payload = response.json()
                user = payload.get("user", {})
                return AuthResult(
                    ok=True,
                    message=f"Logged in to {base_url}",
                    token=payload.get("access_token") or payload.get("token"),
                    employee_id=str(user.get("employee_id", employee_id)),
                    role=str(user.get("role", "operator")),
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"{base_url}: {exc}"
        return AuthResult(ok=False, message=last_error)

    def logout(self, token: str) -> None:
        for base_url in self._control_urls():
            try:
                with httpx.Client(timeout=self._config.upload.timeout_sec) as client:
                    client.post(
                        f"{base_url}/api/auth/logout",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                return
            except Exception:  # noqa: BLE001
                continue

    def register_user(self, token: str, employee_id: str, display_name: str, password: str, role: str) -> tuple[bool, str]:
        return self._post_auth_action(
            "/api/auth/register",
            token,
            {"employee_id": employee_id, "display_name": display_name, "password": password, "role": role},
        )

    def change_password(self, token: str, current_password: str, new_password: str) -> tuple[bool, str]:
        return self._post_auth_action(
            "/api/auth/change-password",
            token,
            {"current_password": current_password, "new_password": new_password},
        )

    def reset_password(self, token: str, employee_id: str, new_password: str) -> tuple[bool, str]:
        return self._post_auth_action(
            "/api/auth/reset-password",
            token,
            {"employee_id": employee_id, "new_password": new_password},
        )

    def upload_batch(self, batch_path: Path, checksum_sha256: str, idempotency_key: str) -> tuple[bool, int | None, str]:
        last_error = "No upload target configured"
        for url in self._upload_urls():
            try:
                with batch_path.open("rb") as file_handle:
                    with httpx.Client(timeout=self._config.upload.timeout_sec) as client:
                        response = client.post(
                            url,
                            headers={
                                "X-API-Token": self._config.server.token,
                                "X-Checksum-SHA256": checksum_sha256,
                                "X-Idempotency-Key": idempotency_key,
                            },
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
        for url in self._upload_urls():
            base_url = url.rsplit("/upload", 1)[0]
            try:
                with httpx.Client(timeout=self._config.upload.timeout_sec) as client:
                    health = client.get(f"{base_url}/healthz")
                    health.raise_for_status()

                    payload = io.BytesIO()
                    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                        archive.writestr("test.txt", "machine-client-connection-test")
                    payload.seek(0)
                    checksum_sha256 = hashlib.sha256(payload.getvalue()).hexdigest()

                    response = client.post(
                        url,
                        headers={
                            "X-API-Token": self._config.server.token,
                            "X-Checksum-SHA256": checksum_sha256,
                            "X-Idempotency-Key": f"connection-test:{self._config.machine_id}",
                        },
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

    def _post_auth_action(self, path: str, token: str, payload: dict[str, str]) -> tuple[bool, str]:
        last_error = "No server configured"
        for base_url in self._control_urls():
            try:
                with httpx.Client(timeout=self._config.upload.timeout_sec) as client:
                    response = client.post(
                        f"{base_url}{path}",
                        headers={"Authorization": f"Bearer {token}"},
                        json=payload,
                    )
                response.raise_for_status()
                body = response.json()
                return True, str(body.get("message", "Success"))
            except Exception as exc:  # noqa: BLE001
                last_error = f"{base_url}: {exc}"
        return False, last_error

    def _upload_urls(self) -> list[str]:
        urls = [self._config.server.primary]
        if self._config.server.backup and self._config.server.backup not in urls:
            urls.append(self._config.server.backup)
        return urls

    def _base_urls(self) -> list[str]:
        return [url.rsplit("/upload", 1)[0] for url in self._upload_urls()]

    def _control_urls(self) -> list[str]:
        base_url = self._config.control.base_url.strip()
        if base_url:
            return [base_url.rstrip("/")]
        return self._base_urls()
