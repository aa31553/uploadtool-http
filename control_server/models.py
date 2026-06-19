from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuthUser(BaseModel):
    employee_id: str
    display_name: str
    role: str
    enabled: bool
    site_ids: list[str] = []
    server_ids: list[str] = []
    machine_ids: list[str] = []


class LoginRequest(BaseModel):
    employee_id: str
    password: str
    client_type: str = "dashboard"
    client_id: str = ""


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_sec: int
    user: AuthUser


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_sec: int


class LogoutRequest(BaseModel):
    refresh_token: str = ""


class RegisterUserRequest(BaseModel):
    employee_id: str
    display_name: str
    password: str
    role: str = "operator"
    site_ids: list[str] = []
    server_ids: list[str] = []
    machine_ids: list[str] = []


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    employee_id: str
    new_password: str


class ToggleUserRequest(BaseModel):
    employee_id: str


class ActionResponse(BaseModel):
    success: bool
    message: str


class ServerRegistrationRequest(BaseModel):
    server_id: str
    name: str
    base_url: str
    site: str
    auth_mode: str = "none"
    shared_secret: str = ""
    poll_interval_sec: int | None = None
    timeout_sec: int | None = None
    labels: dict[str, str] = {}


class ServerPatchRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    site: str | None = None
    enabled: bool | None = None
    poll_interval_sec: int | None = None
    timeout_sec: int | None = None
    labels: dict[str, str] | None = None


class ServerSummary(BaseModel):
    server_id: str
    name: str
    base_url: str
    site: str
    enabled: bool
    status: str
    machine_count: int
    alert_count: int
    last_seen_at: datetime | None
    last_error: str | None
