from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import HTTPException

from control_server.config import ControlServerConfig


class ControlPlaneStore:
    def __init__(self, config: ControlServerConfig) -> None:
        self._config = config
        self._servers_path = Path(config.servers_path)
        self._snapshots_path = Path(config.snapshots_path)
        self._audit_log_path = Path(config.audit_log_path)
        self._servers_path.parent.mkdir(parents=True, exist_ok=True)
        self._snapshots_path.parent.mkdir(parents=True, exist_ok=True)
        self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._poller = threading.Thread(target=self._poll_loop, daemon=True)
        self._poller.start()

    def list_servers(self) -> list[dict[str, object]]:
        with self._lock:
            servers = self._load_servers_unlocked()
            snapshots = self._load_snapshots_unlocked()
        items: list[dict[str, object]] = []
        for server in servers.values():
            snapshot = snapshots.get(str(server["server_id"]), {})
            items.append(self._server_summary(server, snapshot))
        return sorted(items, key=lambda item: item["server_id"])

    def get_server(self, server_id: str) -> dict[str, object]:
        with self._lock:
            servers = self._load_servers_unlocked()
            snapshots = self._load_snapshots_unlocked()
        server = servers.get(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"code": "SRV_404", "message": "Server not found", "recovery": "Check server_id"})
        snapshot = snapshots.get(server_id, {})
        return {**self._server_summary(server, snapshot), "snapshot": snapshot}

    def register_server(self, payload: dict[str, object]) -> None:
        server_id = str(payload.get("server_id", "")).strip()
        if not server_id:
            raise HTTPException(status_code=400, detail={"code": "SRV_400", "message": "server_id is required", "recovery": "Provide a server_id"})
        with self._lock:
            servers = self._load_servers_unlocked()
            if server_id in servers:
                raise HTTPException(status_code=409, detail={"code": "SRV_409", "message": "Server already exists", "recovery": "Use a different server_id or update existing server"})
            now = datetime.now(timezone.utc).isoformat()
            servers[server_id] = {
                "server_id": server_id,
                "name": str(payload.get("name", server_id)),
                "base_url": str(payload.get("base_url", "")).rstrip("/"),
                "site": str(payload.get("site", "default")),
                "enabled": True,
                "auth_mode": str(payload.get("auth_mode", "none")),
                "shared_secret": str(payload.get("shared_secret", "")),
                "poll_interval_sec": int(payload.get("poll_interval_sec") or self._config.poll_default_interval_sec),
                "timeout_sec": int(payload.get("timeout_sec") or self._config.request_timeout_sec),
                "labels": dict(payload.get("labels", {})),
                "last_seen_at": None,
                "last_error": None,
                "next_poll_at": 0.0,
                "created_at": now,
                "updated_at": now,
            }
            self._save_servers_unlocked(servers)

    def patch_server(self, server_id: str, payload: dict[str, object]) -> None:
        with self._lock:
            servers = self._load_servers_unlocked()
            server = servers.get(server_id)
            if server is None:
                raise HTTPException(status_code=404, detail={"code": "SRV_404", "message": "Server not found", "recovery": "Check server_id"})
            for key in ["name", "base_url", "site", "enabled", "poll_interval_sec", "timeout_sec", "labels"]:
                value = payload.get(key)
                if value is None:
                    continue
                server[key] = value.rstrip("/") if key == "base_url" and isinstance(value, str) else value
            server["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_servers_unlocked(servers)

    def refresh_server(self, server_id: str) -> None:
        with self._lock:
            servers = self._load_servers_unlocked()
            server = servers.get(server_id)
            if server is None:
                raise HTTPException(status_code=404, detail={"code": "SRV_404", "message": "Server not found", "recovery": "Check server_id"})
            server["next_poll_at"] = 0.0
            self._save_servers_unlocked(servers)

    def fleet_overview(self) -> dict[str, object]:
        with self._lock:
            servers = self.list_servers()
            snapshots = self._load_snapshots_unlocked()
        machines: list[dict[str, object]] = []
        alerts: list[dict[str, object]] = []
        total_queue_length = 0
        total_processing_rate = 0.0
        backlog_delta = 0
        total_used_tb = 0.0
        total_capacity_tb = 0.0
        for snapshot in snapshots.values():
            machines.extend(snapshot.get("machines", []))
            alerts.extend(snapshot.get("alerts", []))
            queue = snapshot.get("queue", {})
            storage = snapshot.get("storage", {})
            total_queue_length += int(queue.get("queue_length", 0))
            total_processing_rate += float(queue.get("processing_rate", 0.0))
            backlog_delta += int(queue.get("backlog_delta", 0))
            total_used_tb += float(storage.get("used_tb", 0.0))
            total_capacity_tb += float(storage.get("total_tb", 0.0))
        server_statuses = [str(item.get("status", "offline")) for item in servers]
        machine_statuses = [str(item.get("status", "offline")) for item in machines]
        critical_alerts = sum(1 for item in alerts if item.get("level") == "critical")
        warning_alerts = sum(1 for item in alerts if item.get("level") == "warning")
        usage_percent = round((total_used_tb / total_capacity_tb) * 100.0, 1) if total_capacity_tb else 0.0
        fleet_status = "normal"
        if critical_alerts:
            fleet_status = "critical"
        elif warning_alerts or "warning" in server_statuses or "offline" in machine_statuses:
            fleet_status = "warning"
        elif "degraded" in server_statuses or "offline" in server_statuses:
            fleet_status = "degraded"
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fleet_status": fleet_status,
            "server_counts": {
                "total": len(server_statuses),
                "online": server_statuses.count("online"),
                "warning": server_statuses.count("warning"),
                "degraded": server_statuses.count("degraded"),
                "offline": server_statuses.count("offline"),
            },
            "machine_counts": {
                "total": len(machine_statuses),
                "online": machine_statuses.count("online"),
                "warning": machine_statuses.count("warning"),
                "offline": machine_statuses.count("offline"),
            },
            "queue": {
                "total_queue_length": total_queue_length,
                "total_processing_rate": round(total_processing_rate, 2),
                "backlog_delta": backlog_delta,
            },
            "storage": {
                "total_used_tb": round(total_used_tb, 2),
                "total_capacity_tb": round(total_capacity_tb, 2),
                "usage_percent": usage_percent,
            },
            "alerts": {
                "active_total": len(alerts),
                "critical": critical_alerts,
                "warning": warning_alerts,
            },
        }

    def fleet_servers(self) -> list[dict[str, object]]:
        return self.list_servers()

    def fleet_machines(self, server_id: str | None = None) -> list[dict[str, object]]:
        with self._lock:
            snapshots = self._load_snapshots_unlocked()
        items: list[dict[str, object]] = []
        for current_server_id, snapshot in snapshots.items():
            if server_id is not None and current_server_id != server_id:
                continue
            for machine in snapshot.get("machines", []):
                items.append(machine)
        return sorted(items, key=lambda item: (item.get("status", "offline"), item.get("machine_id", "")))

    def fleet_machine_detail(self, machine_id: str) -> dict[str, object]:
        with self._lock:
            snapshots = self._load_snapshots_unlocked()
        for server_id, snapshot in snapshots.items():
            for machine in snapshot.get("machines", []):
                if machine.get("machine_id") == machine_id:
                    recent_batches = [item for item in snapshot.get("image_flow", []) if item.get("machine_id") == machine_id][:12]
                    recent_alerts = [item for item in snapshot.get("alerts", []) if item.get("machine_id") == machine_id or item.get("source_id") == machine_id][:12]
                    return {
                        "machine": machine,
                        "server_id": server_id,
                        "recent_batches": recent_batches,
                        "recent_alerts": recent_alerts,
                    }
        raise HTTPException(status_code=404, detail={"code": "FLEET_404", "message": "Machine not found", "recovery": "Check machine_id"})

    def fleet_alerts(self) -> list[dict[str, object]]:
        with self._lock:
            snapshots = self._load_snapshots_unlocked()
        alerts: list[dict[str, object]] = []
        for snapshot in snapshots.values():
            alerts.extend(snapshot.get("alerts", []))
        return sorted(alerts, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def fleet_image_flow(self) -> list[dict[str, object]]:
        with self._lock:
            snapshots = self._load_snapshots_unlocked()
        items: list[dict[str, object]] = []
        for snapshot in snapshots.values():
            items.extend(snapshot.get("image_flow", []))
        return sorted(items, key=lambda item: str(item.get("received_at", "")), reverse=True)

    def fleet_snapshot_message(self) -> dict[str, object]:
        return {
            "type": "fleet_snapshot",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overview": self.fleet_overview(),
            "servers": self.fleet_servers(),
            "machines": self.fleet_machines(),
            "alerts": self.fleet_alerts()[:20],
        }

    def write_audit(self, actor_employee_id: str, actor_role: str, action: str, target_type: str, target_id: str, result: str, details: dict[str, object] | None = None) -> None:
        entry = {
            "audit_id": f"aud-{int(time.time() * 1000)}",
            "actor_employee_id": actor_employee_id,
            "actor_role": actor_role,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "result": result,
            "details": details or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            with self._audit_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")

    def audit_logs(self) -> list[dict[str, object]]:
        if not self._audit_log_path.exists():
            return []
        return [json.loads(line) for line in self._audit_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def inject_snapshot_for_testing(self, server_id: str, snapshot: dict[str, object]) -> None:
        with self._lock:
            snapshots = self._load_snapshots_unlocked()
            snapshots[server_id] = snapshot
            self._save_snapshots_unlocked(snapshots)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    servers = list(self._load_servers_unlocked().values())
                now_ts = time.time()
                for server in servers:
                    if not bool(server.get("enabled", True)):
                        continue
                    if float(server.get("next_poll_at", 0.0)) > now_ts:
                        continue
                    self._poll_server(str(server["server_id"]))
            except Exception:
                pass
            time.sleep(1)

    def _poll_server(self, server_id: str) -> None:
        with self._lock:
            servers = self._load_servers_unlocked()
            server = servers.get(server_id)
        if server is None:
            return
        try:
            snapshot = self._fetch_server_snapshot(server)
            snapshot["server_id"] = server_id
            with self._lock:
                snapshots = self._load_snapshots_unlocked()
                snapshots[server_id] = snapshot
                self._save_snapshots_unlocked(snapshots)
                servers = self._load_servers_unlocked()
                current = servers[server_id]
                current["last_seen_at"] = datetime.now(timezone.utc).isoformat()
                current["last_error"] = None
                current["next_poll_at"] = time.time() + max(int(current.get("poll_interval_sec", self._config.poll_default_interval_sec)), 1)
                self._save_servers_unlocked(servers)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                servers = self._load_servers_unlocked()
                if server_id in servers:
                    servers[server_id]["last_error"] = str(exc)
                    servers[server_id]["next_poll_at"] = time.time() + max(int(servers[server_id].get("poll_interval_sec", self._config.poll_default_interval_sec)), 1)
                    self._save_servers_unlocked(servers)

    def _fetch_server_snapshot(self, server: dict[str, object]) -> dict[str, object]:
        base_url = str(server.get("base_url", "")).rstrip("/")
        timeout = int(server.get("timeout_sec", self._config.request_timeout_sec))
        with httpx.Client(timeout=timeout) as client:
            local_snapshot = self._try_local_snapshot(client, base_url)
            if local_snapshot is not None:
                return self._normalize_snapshot(server, local_snapshot)
            health = client.get(f"{base_url}/healthz")
            ready = client.get(f"{base_url}/readyz")
            health.raise_for_status()
            ready.raise_for_status()
            machines = client.get(f"{base_url}/api/machines").json()
            server_metrics = client.get(f"{base_url}/api/server/metrics").json()
            queue = client.get(f"{base_url}/api/queue/status").json()
            storage = client.get(f"{base_url}/api/storage/status").json()
            worker = client.get(f"{base_url}/api/worker/status").json()
            alerts = client.get(f"{base_url}/api/alerts").json()
            image_flow = client.get(f"{base_url}/api/image-flow/recent?limit=20").json()
        return self._normalize_snapshot(
            server,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "machines": machines,
                "server_metrics": server_metrics,
                "queue": queue,
                "storage": storage,
                "worker": worker,
                "alerts": alerts,
                "image_flow": image_flow,
            },
            health_ok=bool(health.json().get("status") == "ok" and ready.json().get("status")),
        )

    def _try_local_snapshot(self, client: httpx.Client, base_url: str) -> dict[str, object] | None:
        try:
            response = client.get(f"{base_url}/api/local/snapshot")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception:  # noqa: BLE001
            return None

    def _normalize_snapshot(self, server: dict[str, object], payload: dict[str, object], health_ok: bool = True) -> dict[str, object]:
        queue = dict(payload.get("queue") or {})
        storage = dict(payload.get("storage") or {})
        worker = dict(payload.get("worker") or {})
        alerts = list(payload.get("alerts") or [])
        machines = []
        for machine in list(payload.get("machines") or []):
            item = dict(machine)
            item["server_id"] = server["server_id"]
            item["site"] = server.get("site", "default")
            item["updated_at"] = payload.get("timestamp") or datetime.now(timezone.utc).isoformat()
            machines.append(item)
        status = "online"
        if not health_ok:
            status = "degraded"
        if float(storage.get("usage_percent", 0.0)) >= 90 or int(queue.get("queue_length", 0)) > 10 or any(item.get("level") == "critical" for item in alerts):
            status = "warning"
        if worker.get("heartbeat_at") is None:
            status = "degraded"
        return {
            "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "status": status,
            "health_ok": health_ok,
            "server_metrics": payload.get("server_metrics") or {},
            "queue": queue,
            "storage": storage,
            "worker": worker,
            "alerts": alerts,
            "machines": machines,
            "machine_count": len(machines),
            "alert_count": len(alerts),
            "image_flow": list(payload.get("image_flow") or []),
        }

    def _server_summary(self, server: dict[str, object], snapshot: dict[str, object]) -> dict[str, object]:
        return {
            "server_id": server["server_id"],
            "name": server.get("name", server["server_id"]),
            "base_url": server.get("base_url", ""),
            "site": server.get("site", "default"),
            "enabled": bool(server.get("enabled", True)),
            "status": snapshot.get("status", "offline"),
            "machine_count": int(snapshot.get("machine_count", 0)),
            "alert_count": int(snapshot.get("alert_count", 0)),
            "last_seen_at": server.get("last_seen_at"),
            "last_error": server.get("last_error"),
        }

    def _load_servers_unlocked(self) -> dict[str, dict[str, object]]:
        if not self._servers_path.exists():
            return {}
        try:
            payload = json.loads(self._servers_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)}

    def _save_servers_unlocked(self, servers: dict[str, dict[str, object]]) -> None:
        self._servers_path.write_text(json.dumps(servers, indent=2), encoding="utf-8")

    def _load_snapshots_unlocked(self) -> dict[str, dict[str, object]]:
        if not self._snapshots_path.exists():
            return {}
        try:
            payload = json.loads(self._snapshots_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)}

    def _save_snapshots_unlocked(self, snapshots: dict[str, dict[str, object]]) -> None:
        self._snapshots_path.write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
