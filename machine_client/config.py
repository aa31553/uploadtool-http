from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ServerConfig:
    primary: str
    backup: str
    token: str


@dataclass
class ControlConfig:
    base_url: str


@dataclass
class StorageConfig:
    image_root: str
    buffer_path: str
    max_usage_percent: int
    auto_cleanup: bool
    retention_days: int


@dataclass
class UploadConfig:
    batch_size: int
    interval_sec: int
    retry: int
    compression: str
    timeout_sec: int
    stage_copy_limit_per_cycle: int
    index_existing_on_startup_only: bool


@dataclass
class AppConfig:
    machine_id: str
    server: ServerConfig
    control: ControlConfig
    storage: StorageConfig
    upload: UploadConfig

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_config(path: str | Path) -> AppConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return app_config_from_dict(data)


def app_config_from_dict(data: dict[str, object]) -> AppConfig:
    control_raw = data.get("control") or {"base_url": _derive_control_base_url(data["server"]["primary"])}
    upload_raw = dict(data["upload"])
    upload_raw.setdefault("stage_copy_limit_per_cycle", 100)
    upload_raw.setdefault("index_existing_on_startup_only", False)
    return AppConfig(
        machine_id=data["machine_id"],
        server=ServerConfig(**data["server"]),
        control=ControlConfig(**control_raw),
        storage=StorageConfig(**data["storage"]),
        upload=UploadConfig(**upload_raw),
    )


def save_config(path: str | Path, config: AppConfig) -> None:
    Path(path).write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")


def _derive_control_base_url(upload_url: str) -> str:
    return str(upload_url).rsplit("/upload", 1)[0]
