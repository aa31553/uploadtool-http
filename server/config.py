from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MachineAuth:
    token: str


@dataclass
class ServerConfig:
    server_id: str
    server_name: str
    site: str
    host: str
    port: int
    queue_backend: str
    redis_url: str
    storage_root: str
    temp_root: str
    queue_root: str
    processed_root: str
    failed_root: str
    metadata_path: str
    worker_state_path: str
    idempotency_index_path: str
    user_store_path: str
    bootstrap_admin_employee_id: str
    bootstrap_admin_password: str
    raw_retention_days: int
    temp_retention_hours: int
    max_disk_usage_percent: int
    ip_allowlist: list[str]
    trust_x_forwarded_for: bool
    machines: dict[str, MachineAuth]

    def machine_token(self, machine_id: str) -> str | None:
        entry = self.machines.get(machine_id)
        return None if entry is None else entry.token


def load_server_config(path: str | Path) -> ServerConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    storage_root = data["storage_root"]
    machine_tokens_json = os.environ.get("MIUS_MACHINE_TOKENS_JSON")
    machines_raw = json.loads(machine_tokens_json) if machine_tokens_json else data["machines"]
    return ServerConfig(
        server_id=os.environ.get("MIUS_SERVER_ID", data.get("server_id", "srv-local")),
        server_name=os.environ.get("MIUS_SERVER_NAME", data.get("server_name", "Local Ingestion Server")),
        site=os.environ.get("MIUS_SERVER_SITE", data.get("site", "default")),
        host=os.environ.get("MIUS_SERVER_HOST", data["host"]),
        port=int(os.environ.get("MIUS_SERVER_PORT", data["port"])),
        queue_backend=os.environ.get("MIUS_QUEUE_BACKEND", data.get("queue_backend", "file")),
        redis_url=os.environ.get("MIUS_REDIS_URL", data.get("redis_url", "redis://127.0.0.1:6379/0")),
        storage_root=os.environ.get("MIUS_STORAGE_ROOT", storage_root),
        temp_root=os.environ.get("MIUS_TEMP_ROOT", data["temp_root"]),
        queue_root=os.environ.get("MIUS_QUEUE_ROOT", data.get("queue_root", "runtime/server-queue")),
        processed_root=os.environ.get("MIUS_PROCESSED_ROOT", data.get("processed_root", f"{storage_root}/processed")),
        failed_root=os.environ.get("MIUS_FAILED_ROOT", data.get("failed_root", f"{storage_root}/failed")),
        metadata_path=os.environ.get("MIUS_METADATA_PATH", data["metadata_path"]),
        worker_state_path=os.environ.get("MIUS_WORKER_STATE_PATH", data.get("worker_state_path", "runtime/server-metadata/worker-state.json")),
        idempotency_index_path=os.environ.get("MIUS_IDEMPOTENCY_INDEX_PATH", data.get("idempotency_index_path", "runtime/server-metadata/idempotency-index.json")),
        user_store_path=os.environ.get("MIUS_USER_STORE_PATH", data.get("user_store_path", "runtime/server-metadata/users.json")),
        bootstrap_admin_employee_id=os.environ.get("MIUS_BOOTSTRAP_ADMIN_ID", data.get("bootstrap_admin_employee_id", "admin")),
        bootstrap_admin_password=os.environ.get("MIUS_BOOTSTRAP_ADMIN_PASSWORD", data.get("bootstrap_admin_password", "change-me-now")),
        raw_retention_days=int(os.environ.get("MIUS_RAW_RETENTION_DAYS", data.get("raw_retention_days", 7))),
        temp_retention_hours=int(os.environ.get("MIUS_TEMP_RETENTION_HOURS", data.get("temp_retention_hours", 24))),
        max_disk_usage_percent=int(os.environ.get("MIUS_MAX_DISK_USAGE_PERCENT", data.get("max_disk_usage_percent", 90))),
        ip_allowlist=_load_ip_allowlist(data),
        trust_x_forwarded_for=_env_bool("MIUS_TRUST_X_FORWARDED_FOR", data.get("trust_x_forwarded_for", False)),
        machines={machine_id: MachineAuth(**item) for machine_id, item in machines_raw.items()},
    )


def _load_ip_allowlist(data: dict[str, object]) -> list[str]:
    raw = os.environ.get("MIUS_IP_ALLOWLIST")
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    configured = data.get("ip_allowlist", [])
    return [str(item).strip() for item in configured if str(item).strip()]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
