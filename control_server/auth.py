from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from control_server.config import ControlServerConfig


PBKDF2_ITERATIONS = 200000


class ControlAuthService:
    def __init__(self, config: ControlServerConfig) -> None:
        self._config = config
        self._users_path = Path(config.users_path)
        self._sessions_path = Path(config.sessions_path)
        self._users_path.parent.mkdir(parents=True, exist_ok=True)
        self._sessions_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ensure_bootstrap_admin()

    def login(self, employee_id: str, password: str, client_type: str, client_id: str) -> dict[str, object]:
        employee_id = employee_id.strip()
        password = password.strip()
        user = self._user_or_401(employee_id)
        if not bool(user.get("enabled", True)):
            raise HTTPException(status_code=403, detail={"code": "AUTH_403", "message": "User is disabled", "recovery": "Contact an administrator"})
        if not self._verify_password(password, str(user["password_hash"]), str(user["password_salt"])):
            raise HTTPException(status_code=401, detail={"code": "AUTH_401", "message": "Invalid employee ID or password", "recovery": "Check credentials and retry"})
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(48)
        now = datetime.now(timezone.utc)
        session = {
            "session_id": secrets.token_hex(16),
            "employee_id": employee_id,
            "client_type": client_type,
            "client_id": client_id,
            "access_token_hash": self._token_hash(access_token),
            "refresh_token_hash": self._token_hash(refresh_token),
            "access_expires_at": (now + timedelta(seconds=self._config.access_token_ttl_sec)).isoformat(),
            "refresh_expires_at": (now + timedelta(seconds=self._config.refresh_token_ttl_sec)).isoformat(),
            "issued_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "revoked_at": None,
            "token_version": int(user.get("token_version", 1)),
        }
        with self._lock:
            sessions = self._load_sessions_unlocked()
            sessions[session["session_id"]] = session
            self._save_sessions_unlocked(sessions)
            users = self._load_users_unlocked()
            users[employee_id]["last_login_at"] = now.isoformat()
            self._save_users_unlocked(users)
        return {"access_token": access_token, "refresh_token": refresh_token, "user": user}

    def refresh(self, refresh_token: str) -> str:
        session_id, session = self._session_by_token(refresh_token, token_kind="refresh")
        if session is None:
            raise HTTPException(status_code=401, detail={"code": "AUTH_401", "message": "Invalid refresh token", "recovery": "Login again"})
        access_token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        with self._lock:
            sessions = self._load_sessions_unlocked()
            record = sessions[session_id]
            record["access_token_hash"] = self._token_hash(access_token)
            record["access_expires_at"] = (now + timedelta(seconds=self._config.access_token_ttl_sec)).isoformat()
            record["last_seen_at"] = now.isoformat()
            self._save_sessions_unlocked(sessions)
        return access_token

    def logout(self, access_token: str | None = None, refresh_token: str | None = None) -> None:
        token = refresh_token or access_token or ""
        token_kind = "refresh" if refresh_token else "access"
        session_id, _session = self._session_by_token(token, token_kind=token_kind, raise_on_missing=False)
        if session_id is None:
            return
        with self._lock:
            sessions = self._load_sessions_unlocked()
            if session_id in sessions:
                sessions[session_id]["revoked_at"] = datetime.now(timezone.utc).isoformat()
                self._save_sessions_unlocked(sessions)

    def require_access(self, access_token: str | None) -> dict[str, object]:
        if not access_token:
            raise HTTPException(status_code=401, detail={"code": "AUTH_401", "message": "Missing access token", "recovery": "Login and retry"})
        _session_id, session = self._session_by_token(access_token, token_kind="access")
        employee_id = str(session["employee_id"])
        user = self._user_or_401(employee_id)
        if not bool(user.get("enabled", True)):
            raise HTTPException(status_code=403, detail={"code": "AUTH_403", "message": "User is disabled", "recovery": "Contact an administrator"})
        if int(session.get("token_version", 0)) != int(user.get("token_version", 1)):
            raise HTTPException(status_code=401, detail={"code": "AUTH_401", "message": "Session revoked", "recovery": "Login again"})
        return user

    def register_user(self, actor: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
        self._require_admin(actor)
        employee_id = str(payload.get("employee_id", "")).strip()
        display_name = str(payload.get("display_name", employee_id)).strip()
        password = str(payload.get("password", "")).strip()
        role = str(payload.get("role", "operator")).strip() or "operator"
        self._validate_new_user(employee_id, display_name, password, role)
        with self._lock:
            users = self._load_users_unlocked()
            if employee_id in users:
                raise HTTPException(status_code=409, detail={"code": "USER_409", "message": "Employee ID already exists", "recovery": "Choose a different employee ID"})
            password_hash, password_salt = self._hash_password(password)
            now = datetime.now(timezone.utc).isoformat()
            users[employee_id] = {
                "employee_id": employee_id,
                "display_name": display_name,
                "role": role,
                "enabled": True,
                "token_version": 1,
                "site_ids": list(payload.get("site_ids", [])),
                "server_ids": list(payload.get("server_ids", [])),
                "machine_ids": list(payload.get("machine_ids", [])),
                "password_hash": password_hash,
                "password_salt": password_salt,
                "created_at": now,
                "updated_at": now,
                "password_changed_at": now,
                "last_login_at": None,
            }
            self._save_users_unlocked(users)
            return users[employee_id]

    def change_password(self, actor: dict[str, object], current_password: str, new_password: str) -> None:
        employee_id = str(actor["employee_id"])
        current_password = current_password.strip()
        new_password = new_password.strip()
        self._validate_password(new_password)
        with self._lock:
            users = self._load_users_unlocked()
            user = users[employee_id]
            if not self._verify_password(current_password, str(user["password_hash"]), str(user["password_salt"])):
                raise HTTPException(status_code=401, detail={"code": "AUTH_401", "message": "Current password is incorrect", "recovery": "Re-enter current password"})
            self._set_password_unlocked(user, new_password)
            self._save_users_unlocked(users)

    def reset_password(self, actor: dict[str, object], employee_id: str, new_password: str) -> None:
        self._require_admin(actor)
        self._validate_password(new_password)
        with self._lock:
            users = self._load_users_unlocked()
            user = users.get(employee_id.strip())
            if user is None:
                raise HTTPException(status_code=404, detail={"code": "USER_404", "message": "User not found", "recovery": "Check employee ID"})
            self._set_password_unlocked(user, new_password)
            self._save_users_unlocked(users)

    def toggle_user(self, actor: dict[str, object], employee_id: str, enabled: bool) -> None:
        self._require_admin(actor)
        with self._lock:
            users = self._load_users_unlocked()
            user = users.get(employee_id.strip())
            if user is None:
                raise HTTPException(status_code=404, detail={"code": "USER_404", "message": "User not found", "recovery": "Check employee ID"})
            user["enabled"] = enabled
            user["token_version"] = int(user.get("token_version", 1)) + 1
            user["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_users_unlocked(users)

    def patch_user(self, actor: dict[str, object], employee_id: str, payload: dict[str, object]) -> dict[str, object]:
        self._require_admin(actor)
        with self._lock:
            users = self._load_users_unlocked()
            user = users.get(employee_id.strip())
            if user is None:
                raise HTTPException(status_code=404, detail={"code": "USER_404", "message": "User not found", "recovery": "Check employee ID"})
            if payload.get("display_name") is not None:
                user["display_name"] = str(payload["display_name"]).strip() or user["display_name"]
            if payload.get("role") is not None:
                role = str(payload["role"]).strip()
                if role not in {"admin", "supervisor", "operator"}:
                    raise HTTPException(status_code=400, detail={"code": "USER_400", "message": "Invalid role", "recovery": "Use admin, supervisor, or operator"})
                user["role"] = role
            if payload.get("enabled") is not None:
                user["enabled"] = bool(payload["enabled"])
                user["token_version"] = int(user.get("token_version", 1)) + 1
            for field in ["site_ids", "server_ids", "machine_ids"]:
                if payload.get(field) is not None:
                    user[field] = [str(item) for item in payload[field]]
            user["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_users_unlocked(users)
            return self._public_user(user)

    def introspect(self, access_token: str) -> dict[str, object]:
        user = self.require_access(access_token)
        return {
            "active": True,
            "employee_id": user["employee_id"],
            "role": user.get("role", "operator"),
            "site_ids": list(user.get("site_ids", [])),
            "server_ids": list(user.get("server_ids", [])),
            "machine_ids": list(user.get("machine_ids", [])),
        }

    def list_users(self) -> list[dict[str, object]]:
        with self._lock:
            users = self._load_users_unlocked()
        return [self._public_user(user) for user in users.values()]

    def get_user(self, employee_id: str) -> dict[str, object]:
        user = self._user_or_401(employee_id)
        return self._public_user(user)

    def _set_password_unlocked(self, user: dict[str, object], new_password: str) -> None:
        password_hash, password_salt = self._hash_password(new_password)
        now = datetime.now(timezone.utc).isoformat()
        user["password_hash"] = password_hash
        user["password_salt"] = password_salt
        user["password_changed_at"] = now
        user["updated_at"] = now
        user["token_version"] = int(user.get("token_version", 1)) + 1

    def _public_user(self, user: dict[str, object]) -> dict[str, object]:
        return {
            "employee_id": user["employee_id"],
            "display_name": user.get("display_name", user["employee_id"]),
            "role": user.get("role", "operator"),
            "enabled": bool(user.get("enabled", True)),
            "site_ids": list(user.get("site_ids", [])),
            "server_ids": list(user.get("server_ids", [])),
            "machine_ids": list(user.get("machine_ids", [])),
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
            "password_changed_at": user.get("password_changed_at"),
            "last_login_at": user.get("last_login_at"),
        }

    def _ensure_bootstrap_admin(self) -> None:
        with self._lock:
            users = self._load_users_unlocked()
            admin_id = self._config.bootstrap_admin_employee_id.strip()
            if admin_id and admin_id not in users:
                password_hash, password_salt = self._hash_password(self._config.bootstrap_admin_password)
                now = datetime.now(timezone.utc).isoformat()
                users[admin_id] = {
                    "employee_id": admin_id,
                    "display_name": "Bootstrap Admin",
                    "role": "admin",
                    "enabled": True,
                    "token_version": 1,
                    "site_ids": [],
                    "server_ids": [],
                    "machine_ids": [],
                    "password_hash": password_hash,
                    "password_salt": password_salt,
                    "created_at": now,
                    "updated_at": now,
                    "password_changed_at": now,
                    "last_login_at": None,
                }
                self._save_users_unlocked(users)

    def _validate_new_user(self, employee_id: str, display_name: str, password: str, role: str) -> None:
        if len(employee_id) < 3:
            raise HTTPException(status_code=400, detail={"code": "USER_400", "message": "Employee ID must be at least 3 characters", "recovery": "Use a longer employee ID"})
        if not display_name:
            raise HTTPException(status_code=400, detail={"code": "USER_400", "message": "Display name is required", "recovery": "Fill in display name"})
        if role not in {"admin", "supervisor", "operator"}:
            raise HTTPException(status_code=400, detail={"code": "USER_400", "message": "Invalid role", "recovery": "Use admin, supervisor, or operator"})
        self._validate_password(password)

    def _validate_password(self, password: str) -> None:
        if len(password.strip()) < 6:
            raise HTTPException(status_code=400, detail={"code": "AUTH_400", "message": "Password must be at least 6 characters", "recovery": "Use a longer password"})

    def _user_or_401(self, employee_id: str) -> dict[str, object]:
        with self._lock:
            users = self._load_users_unlocked()
            user = users.get(employee_id)
        if user is None:
            raise HTTPException(status_code=401, detail={"code": "AUTH_401", "message": "Invalid employee ID or password", "recovery": "Check credentials and retry"})
        return user

    def _session_by_token(self, token: str, token_kind: str, raise_on_missing: bool = True) -> tuple[str | None, dict[str, object] | None]:
        token_hash = self._token_hash(token)
        with self._lock:
            sessions = self._load_sessions_unlocked()
        now = datetime.now(timezone.utc)
        key_name = f"{token_kind}_token_hash"
        expiry_name = f"{token_kind}_expires_at"
        for session_id, session in sessions.items():
            if session.get(key_name) != token_hash:
                continue
            revoked_at = session.get("revoked_at")
            if revoked_at:
                break
            if datetime.fromisoformat(str(session[expiry_name])) <= now:
                break
            return session_id, session
        if raise_on_missing:
            raise HTTPException(status_code=401, detail={"code": "AUTH_401", "message": f"Invalid {token_kind} token", "recovery": "Login again"})
        return None, None

    def _load_users_unlocked(self) -> dict[str, dict[str, object]]:
        if not self._users_path.exists():
            return {}
        try:
            payload = json.loads(self._users_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)}

    def _save_users_unlocked(self, users: dict[str, dict[str, object]]) -> None:
        self._users_path.write_text(json.dumps(users, indent=2), encoding="utf-8")

    def _load_sessions_unlocked(self) -> dict[str, dict[str, object]]:
        if not self._sessions_path.exists():
            return {}
        try:
            payload = json.loads(self._sessions_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)}

    def _save_sessions_unlocked(self, sessions: dict[str, dict[str, object]]) -> None:
        self._sessions_path.write_text(json.dumps(sessions, indent=2), encoding="utf-8")

    def _hash_password(self, password: str) -> tuple[str, str]:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return digest.hex(), salt.hex()

    def _verify_password(self, password: str, password_hash: str, password_salt: str) -> bool:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(password_salt), PBKDF2_ITERATIONS)
        return hmac.compare_digest(digest.hex(), password_hash)

    def _token_hash(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _require_admin(self, actor: dict[str, object]) -> None:
        if actor.get("role") != "admin":
            raise HTTPException(status_code=403, detail={"code": "AUTH_403", "message": "Admin role required", "recovery": "Login with an admin account"})
