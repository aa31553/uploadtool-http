from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClientStatus:
    machine_id: str
    online: bool
    authenticated: bool
    current_user: str
    current_role: str
    fps: float
    upload_success_rate: float
    latency_ms: int
    buffer_images: int
    buffer_capacity: int
    queue_growth_per_sec: float
    message: str
