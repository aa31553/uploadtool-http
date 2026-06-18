from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from server.config import ServerConfig


PBKDF2_ITERATIONS = 200000
SESSION_TTL_HOURS = 8


@dataclass
class AuthSession:
    employee_id: str
    role: str
    token: str
    expires_at: datetime


class UserAuthService:
    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._path = Path(config.user_store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._sessions: dict[str, AuthSession] = {}
        self._ensure_bootstrap_admin()

    def login(self, employee_id: str, password: str) -> AuthSession:
        employee_id = employee_id.strip()
        password = password.strip()
        if not employee_id or not password:
            raise HTTPException(status_code=400, detail="Employee ID and password are required")
        user = self._user_or_401(employee_id)
        if not self._verify_password(password, str(user["password_hash"]), str(user["password_salt"])):
            raise HTTPException(status_code=401, detail="Invalid employee ID or password")
        session = AuthSession(
            employee_id=employee_id,
            role=str(user.get("role", "user")),
            token=secrets.token_urlsafe(32),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS),
        )
        with self._lock:
            self._sessions[session.token] = session
        return session

    def logout(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def require_session(self, token: str | None) -> AuthSession:
        if not token:
            raise HTTPException(status_code=401, detail="Missing authorization token")
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                raise HTTPException(status_code=401, detail="Invalid session token")
            if session.expires_at <= datetime.now(timezone.utc):
                self._sessions.pop(token, None)
                raise HTTPException(status_code=401, detail="Session expired")
            return session

    def register_user(self, actor: AuthSession, employee_id: str, password: str, role: str) -> dict[str, object]:
        self._require_admin(actor)
        employee_id = employee_id.strip()
        password = password.strip()
        role = role.strip().lower() or "user"
        if role not in {"admin", "user"}:
            raise HTTPException(status_code=400, detail="Role must be admin or user")
        self._validate_credentials(employee_id, password)
        with self._lock:
            users = self._load_users_unlocked()
            if employee_id in users:
                raise HTTPException(status_code=409, detail="Employee ID already exists")
            password_hash, password_salt = self._hash_password(password)
            now = datetime.now(timezone.utc).isoformat()
            users[employee_id] = {
                "employee_id": employee_id,
                "role": role,
                "password_hash": password_hash,
                "password_salt": password_salt,
                "created_at": now,
                "updated_at": now,
                "password_changed_at": now,
            }
            self._save_users_unlocked(users)
            return users[employee_id]

    def change_password(self, actor: AuthSession, current_password: str, new_password: str) -> None:
        current_password = current_password.strip()
        new_password = new_password.strip()
        if not current_password:
            raise HTTPException(status_code=400, detail="Current password is required")
        self._validate_password(new_password)
        with self._lock:
            users = self._load_users_unlocked()
            user = self._user_from_map_or_401(users, actor.employee_id)
            if not self._verify_password(current_password, str(user["password_hash"]), str(user["password_salt"])):
                raise HTTPException(status_code=401, detail="Current password is incorrect")
            password_hash, password_salt = self._hash_password(new_password)
            now = datetime.now(timezone.utc).isoformat()
            user["password_hash"] = password_hash
            user["password_salt"] = password_salt
            user["updated_at"] = now
            user["password_changed_at"] = now
            self._save_users_unlocked(users)

    def reset_password(self, actor: AuthSession, employee_id: str, new_password: str) -> None:
        self._require_admin(actor)
        employee_id = employee_id.strip()
        new_password = new_password.strip()
        self._validate_credentials(employee_id, new_password, validate_employee=False)
        with self._lock:
            users = self._load_users_unlocked()
            user = self._user_from_map_or_401(users, employee_id)
            password_hash, password_salt = self._hash_password(new_password)
            now = datetime.now(timezone.utc).isoformat()
            user["password_hash"] = password_hash
            user["password_salt"] = password_salt
            user["updated_at"] = now
            user["password_changed_at"] = now
            self._save_users_unlocked(users)

    def user_summary(self, session: AuthSession) -> dict[str, str]:
        return {"employee_id": session.employee_id, "role": session.role}

    def _ensure_bootstrap_admin(self) -> None:
        with self._lock:
            users = self._load_users_unlocked()
            admin_id = self._config.bootstrap_admin_employee_id.strip()
            if admin_id and admin_id not in users:
                password_hash, password_salt = self._hash_password(self._config.bootstrap_admin_password)
                now = datetime.now(timezone.utc).isoformat()
                users[admin_id] = {
                    "employee_id": admin_id,
                    "role": "admin",
                    "password_hash": password_hash,
                    "password_salt": password_salt,
                    "created_at": now,
                    "updated_at": now,
                    "password_changed_at": now,
                }
                self._save_users_unlocked(users)

    def _load_users_unlocked(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)}

    def _save_users_unlocked(self, users: dict[str, dict[str, object]]) -> None:
        self._path.write_text(json.dumps(users, indent=2), encoding="utf-8")

    def _validate_credentials(self, employee_id: str, password: str, validate_employee: bool = True) -> None:
        if validate_employee and not employee_id:
            raise HTTPException(status_code=400, detail="Employee ID is required")
        if validate_employee and len(employee_id) < 3:
            raise HTTPException(status_code=400, detail="Employee ID must be at least 3 characters")
        self._validate_password(password)

    def _validate_password(self, password: str) -> None:
        if len(password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    def _hash_password(self, password: str) -> tuple[str, str]:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return digest.hex(), salt.hex()

    def _verify_password(self, password: str, password_hash: str, password_salt: str) -> bool:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(password_salt),
            PBKDF2_ITERATIONS,
        )
        return hmac.compare_digest(digest.hex(), password_hash)

    def _user_or_401(self, employee_id: str) -> dict[str, object]:
        with self._lock:
            users = self._load_users_unlocked()
            return self._user_from_map_or_401(users, employee_id)

    def _user_from_map_or_401(self, users: dict[str, dict[str, object]], employee_id: str) -> dict[str, object]:
        user = users.get(employee_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid employee ID or password")
        return user

    def _require_admin(self, actor: AuthSession) -> None:
        if actor.role != "admin":
            raise HTTPException(status_code=403, detail="Admin role required")
