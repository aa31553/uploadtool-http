from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ControlServerConfig:
    host: str
    port: int
    state_root: str
    users_path: str
    sessions_path: str
    servers_path: str
    snapshots_path: str
    audit_log_path: str
    bootstrap_admin_employee_id: str
    bootstrap_admin_password: str
    access_token_ttl_sec: int
    refresh_token_ttl_sec: int
    poll_default_interval_sec: int
    request_timeout_sec: int
    ip_allowlist: list[str]
    trust_x_forwarded_for: bool


def load_control_config(path: str | Path) -> ControlServerConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ControlServerConfig(
        host=os.environ.get("MIUS_CONTROL_HOST", data.get("host", "0.0.0.0")),
        port=int(os.environ.get("MIUS_CONTROL_PORT", data.get("port", 8100))),
        state_root=os.environ.get("MIUS_CONTROL_STATE_ROOT", data.get("state_root", "runtime/control-plane")),
        users_path=os.environ.get("MIUS_CONTROL_USERS_PATH", data.get("users_path", "runtime/control-plane/users.json")),
        sessions_path=os.environ.get("MIUS_CONTROL_SESSIONS_PATH", data.get("sessions_path", "runtime/control-plane/sessions.json")),
        servers_path=os.environ.get("MIUS_CONTROL_SERVERS_PATH", data.get("servers_path", "runtime/control-plane/servers.json")),
        snapshots_path=os.environ.get("MIUS_CONTROL_SNAPSHOTS_PATH", data.get("snapshots_path", "runtime/control-plane/snapshots.json")),
        audit_log_path=os.environ.get("MIUS_CONTROL_AUDIT_LOG_PATH", data.get("audit_log_path", "runtime/control-plane/audit-log.jsonl")),
        bootstrap_admin_employee_id=os.environ.get("MIUS_CONTROL_BOOTSTRAP_ADMIN_ID", data.get("bootstrap_admin_employee_id", "admin")),
        bootstrap_admin_password=os.environ.get("MIUS_CONTROL_BOOTSTRAP_ADMIN_PASSWORD", data.get("bootstrap_admin_password", "change-me-now")),
        access_token_ttl_sec=int(os.environ.get("MIUS_CONTROL_ACCESS_TTL_SEC", data.get("access_token_ttl_sec", 900))),
        refresh_token_ttl_sec=int(os.environ.get("MIUS_CONTROL_REFRESH_TTL_SEC", data.get("refresh_token_ttl_sec", 28800))),
        poll_default_interval_sec=int(os.environ.get("MIUS_CONTROL_POLL_INTERVAL_SEC", data.get("poll_default_interval_sec", 5))),
        request_timeout_sec=int(os.environ.get("MIUS_CONTROL_REQUEST_TIMEOUT_SEC", data.get("request_timeout_sec", 3))),
        ip_allowlist=_load_ip_allowlist(data),
        trust_x_forwarded_for=_env_bool("MIUS_CONTROL_TRUST_X_FORWARDED_FOR", data.get("trust_x_forwarded_for", False)),
    )


def _load_ip_allowlist(data: dict[str, object]) -> list[str]:
    raw = os.environ.get("MIUS_CONTROL_IP_ALLOWLIST")
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    configured = data.get("ip_allowlist", [])
    return [str(item).strip() for item in configured if str(item).strip()]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
