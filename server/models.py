from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MachineStatus(BaseModel):
    machine_id: str
    status: str
    fps: float
    latency_ms: int
    queue_size: int
    last_upload: datetime


class ServerMetrics(BaseModel):
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    net_in_mbps: float
    net_out_mbps: float
    disk_read_mbps: float
    disk_write_mbps: float
    updated_at: datetime


class QueueStatus(BaseModel):
    queue_length: int
    processing_rate: float
    backlog_delta: int
    worker_utilization: float
    updated_at: datetime


class StorageStatus(BaseModel):
    total_tb: float
    used_tb: float
    usage_percent: float
    growth_tb_per_day: float
    eta_full_days: float
    updated_at: datetime


class AlertItem(BaseModel):
    level: str
    message: str
    source: str
    created_at: datetime


class UploadAccepted(BaseModel):
    machine_id: str
    timestamp: datetime
    batch_filename: str
    accepted: bool
    stored_path: str
    metadata_recorded: bool
