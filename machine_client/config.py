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


@dataclass
class AppConfig:
    machine_id: str
    server: ServerConfig
    storage: StorageConfig
    upload: UploadConfig

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_config(path: str | Path) -> AppConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return app_config_from_dict(data)


def app_config_from_dict(data: dict[str, object]) -> AppConfig:
    return AppConfig(
        machine_id=data["machine_id"],
        server=ServerConfig(**data["server"]),
        storage=StorageConfig(**data["storage"]),
        upload=UploadConfig(**data["upload"]),
    )


def save_config(path: str | Path, config: AppConfig) -> None:
    Path(path).write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
