from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MachineAuth:
    token: str


@dataclass
class ServerConfig:
    host: str
    port: int
    storage_root: str
    temp_root: str
    queue_root: str
    processed_root: str
    failed_root: str
    metadata_path: str
    worker_state_path: str
    machines: dict[str, MachineAuth]

    def machine_token(self, machine_id: str) -> str | None:
        entry = self.machines.get(machine_id)
        return None if entry is None else entry.token


def load_server_config(path: str | Path) -> ServerConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    storage_root = data["storage_root"]
    return ServerConfig(
        host=data["host"],
        port=data["port"],
        storage_root=storage_root,
        temp_root=data["temp_root"],
        queue_root=data.get("queue_root", "runtime/server-queue"),
        processed_root=data.get("processed_root", f"{storage_root}/processed"),
        failed_root=data.get("failed_root", f"{storage_root}/failed"),
        metadata_path=data["metadata_path"],
        worker_state_path=data.get("worker_state_path", "runtime/server-metadata/worker-state.json"),
        machines={machine_id: MachineAuth(**item) for machine_id, item in data["machines"].items()},
    )
