from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from machine_client.config import AppConfig


def validate_config(config: AppConfig) -> list[str]:
    errors: list[str] = []

    if not config.machine_id.strip():
        errors.append("Machine ID is required")

    for label, value in [("Primary server URL", config.server.primary), ("Backup server URL", config.server.backup)]:
        if value and not _is_valid_url(value):
            errors.append(f"{label} is invalid")

    if config.control.base_url and not _is_valid_url(config.control.base_url):
        errors.append("Control server URL is invalid")

    if not config.server.token.strip():
        errors.append("API token is required")

    image_root = Path(config.storage.image_root)
    if not image_root.exists() or not image_root.is_dir():
        errors.append("Image root path must exist")

    buffer_root = Path(config.storage.buffer_path)
    buffer_root.mkdir(parents=True, exist_ok=True)
    if not buffer_root.is_dir():
        errors.append("Buffer path is invalid")

    if config.storage.max_usage_percent > 95:
        errors.append("Max disk usage must be 95 or below")

    if config.upload.batch_size <= 0:
        errors.append("Batch size must be greater than zero")

    if config.upload.interval_sec <= 0:
        errors.append("Interval must be greater than zero")

    if config.upload.timeout_sec <= 0:
        errors.append("Timeout must be greater than zero")

    return errors


def _is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
