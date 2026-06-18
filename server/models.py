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
    load_avg_1: float
    load_avg_5: float
    load_avg_15: float
    updated_at: datetime


class QueueStatus(BaseModel):
    queue_length: int
    processing_rate: float
    backlog_delta: int
    worker_utilization: float
    per_machine: dict[str, int]
    updated_at: datetime


class StorageStatus(BaseModel):
    total_tb: float
    used_tb: float
    usage_percent: float
    raw_used_gb: float
    processed_used_gb: float
    failed_used_gb: float
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
    duplicate: bool
    queue_enqueued: bool
    error_code: str | None = None


class WorkerState(BaseModel):
    status: str
    heartbeat_at: datetime | None
    current_job_id: str | None
    processed_jobs: int
    failed_jobs: int
    processing_rate: float
    worker_utilization: float
    last_error: str
    updated_at: datetime | None


class ImageFlowBatch(BaseModel):
    job_id: str
    machine_id: str
    batch_filename: str | None
    status: str
    image_count: int
    stored_path: str
    processed_root: str | None
    queued_at: datetime | None
    received_at: datetime | None
    completed_at: datetime | None
    last_error: str | None


class MachineDetail(BaseModel):
    machine: MachineStatus
    recent_batches: list[ImageFlowBatch]
    queue_depth: int
    recent_upload_count: int


class AuthUser(BaseModel):
    employee_id: str
    role: str


class LoginRequest(BaseModel):
    employee_id: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime
    user: AuthUser


class RegisterUserRequest(BaseModel):
    employee_id: str
    password: str
    role: str = "user"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    employee_id: str
    new_password: str


class AccountActionResponse(BaseModel):
    success: bool
    message: str
    user: AuthUser | None = None
