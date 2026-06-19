from __future__ import annotations

import asyncio

from fastapi import APIRouter, Header, HTTPException, Request, WebSocket, WebSocketDisconnect

from control_server.auth import ControlAuthService
from control_server.config import ControlServerConfig
from control_server.models import ActionResponse, LoginRequest, LoginResponse, RefreshRequest, RefreshResponse, RegisterUserRequest, ServerPatchRequest, ServerRegistrationRequest, ToggleUserRequest
from control_server.store import ControlPlaneStore


router = APIRouter()
runtime_config: ControlServerConfig | None = None
runtime_auth: ControlAuthService | None = None
runtime_store: ControlPlaneStore | None = None


def configure_routes(config: ControlServerConfig, auth: ControlAuthService, store: ControlPlaneStore) -> None:
    global runtime_config, runtime_auth, runtime_store
    runtime_config = config
    runtime_auth = auth
    runtime_store = store


def _require_runtime() -> tuple[ControlServerConfig, ControlAuthService, ControlPlaneStore]:
    if runtime_config is None or runtime_auth is None or runtime_store is None:
        raise RuntimeError("Control server routes are not configured")
    return runtime_config, runtime_auth, runtime_store


def resolve_client_host(request: Request) -> str | None:
    config, _, _ = _require_runtime()
    if config.trust_x_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def enforce_ip_allowlist(client_host: str | None) -> None:
    config, _, _ = _require_runtime()
    allowlist = set(config.ip_allowlist)
    if not allowlist:
        return
    if client_host not in allowlist:
        raise HTTPException(status_code=403, detail={"code": "AUTH_403", "message": f"Client IP {client_host or 'unknown'} is not allowed", "recovery": "Add IP to control server allowlist"})


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail={"code": "AUTH_401", "message": "Authorization header must use Bearer token", "recovery": "Retry with Bearer token"})
    return authorization[len(prefix) :].strip()


def require_user(authorization: str | None) -> dict[str, object]:
    _, auth, _ = _require_runtime()
    return auth.require_access(bearer_token(authorization))


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@router.post("/api/auth/login", response_model=LoginResponse)
def login(request: Request, payload: LoginRequest) -> LoginResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _config, auth, store = _require_runtime()
    result = auth.login(payload.employee_id, payload.password, payload.client_type, payload.client_id)
    user = auth.get_user(payload.employee_id)
    store.write_audit(user["employee_id"], user["role"], "auth.login", "session", payload.client_type, "success")
    return LoginResponse(
        access_token=str(result["access_token"]),
        refresh_token=str(result["refresh_token"]),
        expires_in_sec=runtime_config.access_token_ttl_sec if runtime_config is not None else 900,
        user=user,
    )


@router.post("/api/auth/refresh", response_model=RefreshResponse)
def refresh(request: Request, payload: RefreshRequest) -> RefreshResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    config, auth, _store = _require_runtime()
    access_token = auth.refresh(payload.refresh_token)
    return RefreshResponse(access_token=access_token, expires_in_sec=config.access_token_ttl_sec)


@router.post("/api/auth/logout", response_model=ActionResponse)
def logout(request: Request, payload: dict[str, object] | None = None, authorization: str | None = Header(default=None, alias="Authorization")) -> ActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _config, auth, store = _require_runtime()
    user = auth.require_access(bearer_token(authorization)) if authorization else {"employee_id": "unknown", "role": "unknown"}
    refresh_token = str((payload or {}).get("refresh_token", ""))
    auth.logout(access_token=bearer_token(authorization), refresh_token=refresh_token or None)
    store.write_audit(str(user.get("employee_id", "unknown")), str(user.get("role", "unknown")), "auth.logout", "session", str(user.get("employee_id", "unknown")), "success")
    return ActionResponse(success=True, message="Logged out")


@router.get("/api/auth/me")
def me(request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    _config, auth, _store = _require_runtime()
    actor = require_user(authorization)
    return auth.get_user(str(actor["employee_id"]))


@router.post("/api/auth/introspect")
def introspect(request: Request, payload: dict[str, str]) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    _config, auth, _store = _require_runtime()
    return auth.introspect(str(payload.get("token", "")))


@router.post("/api/auth/register")
def register_user(request: Request, payload: RegisterUserRequest, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    _config, auth, store = _require_runtime()
    actor = require_user(authorization)
    user = auth.register_user(actor, payload.model_dump())
    store.write_audit(str(actor["employee_id"]), str(actor["role"]), "user.register", "user", str(user["employee_id"]), "success")
    return {"success": True, "message": "User registered", "user": auth.get_user(str(user["employee_id"]))}


@router.post("/api/auth/change-password", response_model=ActionResponse)
def change_password(request: Request, payload: dict[str, str], authorization: str | None = Header(default=None, alias="Authorization")) -> ActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _config, auth, store = _require_runtime()
    actor = require_user(authorization)
    auth.change_password(actor, str(payload.get("current_password", "")), str(payload.get("new_password", "")))
    store.write_audit(str(actor["employee_id"]), str(actor["role"]), "user.change_password", "user", str(actor["employee_id"]), "success")
    return ActionResponse(success=True, message="Password updated")


@router.post("/api/auth/reset-password", response_model=ActionResponse)
def reset_password(request: Request, payload: ResetPasswordRequest, authorization: str | None = Header(default=None, alias="Authorization")) -> ActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _config, auth, store = _require_runtime()
    actor = require_user(authorization)
    auth.reset_password(actor, payload.employee_id, payload.new_password)
    store.write_audit(str(actor["employee_id"]), str(actor["role"]), "user.reset_password", "user", payload.employee_id, "success")
    return ActionResponse(success=True, message="Password reset")


@router.post("/api/auth/disable-user", response_model=ActionResponse)
def disable_user(request: Request, payload: dict[str, str], authorization: str | None = Header(default=None, alias="Authorization")) -> ActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _config, auth, store = _require_runtime()
    actor = require_user(authorization)
    employee_id = str(payload.get("employee_id", ""))
    auth.toggle_user(actor, employee_id, enabled=False)
    store.write_audit(str(actor["employee_id"]), str(actor["role"]), "user.disable", "user", employee_id, "success")
    return ActionResponse(success=True, message="User disabled")


@router.post("/api/auth/enable-user", response_model=ActionResponse)
def enable_user(request: Request, payload: ToggleUserRequest, authorization: str | None = Header(default=None, alias="Authorization")) -> ActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    _config, auth, store = _require_runtime()
    actor = require_user(authorization)
    auth.toggle_user(actor, payload.employee_id, enabled=True)
    store.write_audit(str(actor["employee_id"]), str(actor["role"]), "user.enable", "user", payload.employee_id, "success")
    return ActionResponse(success=True, message="User enabled")


@router.get("/api/users")
def list_users(request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, auth, _store = _require_runtime()
    items = auth.list_users()
    return {"items": items, "total": len(items)}


@router.get("/api/users/{employee_id}")
def get_user(employee_id: str, request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, auth, _store = _require_runtime()
    return auth.get_user(employee_id)


@router.patch("/api/users/{employee_id}")
def patch_user(employee_id: str, request: Request, payload: dict[str, object], authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    actor = require_user(authorization)
    _config, auth, store = _require_runtime()
    user = auth.patch_user(actor, employee_id, payload)
    store.write_audit(str(actor["employee_id"]), str(actor["role"]), "user.patch", "user", employee_id, "success")
    return {"success": True, "message": "User updated", "user": user}


@router.get("/api/servers")
def list_servers(request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    items = store.list_servers()
    return {"items": items, "total": len(items)}


@router.post("/api/servers", response_model=ActionResponse)
def register_server(request: Request, payload: ServerRegistrationRequest, authorization: str | None = Header(default=None, alias="Authorization")) -> ActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    if actor.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"code": "AUTH_403", "message": "Admin role required", "recovery": "Login with an admin account"})
    store.register_server(payload.model_dump())
    store.write_audit(str(actor["employee_id"]), str(actor["role"]), "server.register", "server", payload.server_id, "success")
    return ActionResponse(success=True, message="Server registered")


@router.get("/api/servers/{server_id}")
def get_server(server_id: str, request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    return store.get_server(server_id)


@router.patch("/api/servers/{server_id}", response_model=ActionResponse)
def patch_server(server_id: str, request: Request, payload: ServerPatchRequest, authorization: str | None = Header(default=None, alias="Authorization")) -> ActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    if actor.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"code": "AUTH_403", "message": "Admin role required", "recovery": "Login with an admin account"})
    store.patch_server(server_id, payload.model_dump(exclude_none=True))
    store.write_audit(str(actor["employee_id"]), str(actor["role"]), "server.patch", "server", server_id, "success")
    return ActionResponse(success=True, message="Server updated")


@router.post("/api/servers/{server_id}/refresh", response_model=ActionResponse)
def refresh_server(server_id: str, request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> ActionResponse:
    enforce_ip_allowlist(resolve_client_host(request))
    actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    store.refresh_server(server_id)
    store.write_audit(str(actor["employee_id"]), str(actor["role"]), "server.refresh", "server", server_id, "success")
    return ActionResponse(success=True, message="Refresh scheduled")


@router.get("/api/fleet/overview")
def fleet_overview(request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    return store.fleet_overview()


@router.get("/api/fleet/servers")
def fleet_servers(request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> list[dict[str, object]]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    return store.fleet_servers()


@router.get("/api/fleet/servers/{server_id}")
def fleet_server_detail(server_id: str, request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    return store.get_server(server_id)


@router.get("/api/fleet/machines")
def fleet_machines(request: Request, server_id: str | None = None, authorization: str | None = Header(default=None, alias="Authorization")) -> list[dict[str, object]]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    return store.fleet_machines(server_id=server_id)


@router.get("/api/fleet/machines/{machine_id}")
def fleet_machine_detail(machine_id: str, request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    return store.fleet_machine_detail(machine_id)


@router.get("/api/fleet/alerts")
def fleet_alerts(request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> list[dict[str, object]]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    return store.fleet_alerts()


@router.get("/api/fleet/image-flow/recent")
def fleet_image_flow(request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> list[dict[str, object]]:
    enforce_ip_allowlist(resolve_client_host(request))
    _actor = require_user(authorization)
    _config, _auth, store = _require_runtime()
    return store.fleet_image_flow()[:50]


@router.get("/api/audit-logs")
def audit_logs(request: Request, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    enforce_ip_allowlist(resolve_client_host(request))
    actor = require_user(authorization)
    if actor.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"code": "AUTH_403", "message": "Admin role required", "recovery": "Login with an admin account"})
    _config, _auth, store = _require_runtime()
    items = store.audit_logs()
    return {"items": items, "total": len(items)}


@router.websocket("/ws/fleet/live")
async def fleet_live(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            _config, _auth, store = _require_runtime()
            await websocket.send_json(store.fleet_snapshot_message())
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
