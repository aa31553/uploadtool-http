from __future__ import annotations

import hashlib
import io
import json
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timezone

from PIL import Image


API_BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else "replace-me"
MACHINE_ID = sys.argv[3] if len(sys.argv) > 3 else "MC01"


def build_png_bytes() -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", (8, 8), color=(255, 64, 64))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def get_json(path: str) -> dict | list:
    with urllib.request.urlopen(f"{API_BASE}{path}") as response:
        return json.loads(response.read().decode("utf-8"))


def post_upload() -> dict:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sample.png", build_png_bytes())
    content = payload.getvalue()
    checksum = hashlib.sha256(content).hexdigest()
    boundary = "----MIUSBOUNDARY"
    timestamp = datetime.now(timezone.utc).isoformat()
    body = build_multipart(boundary, MACHINE_ID, timestamp, content)
    request = urllib.request.Request(
        f"{API_BASE}/upload",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-API-Token": TOKEN,
            "X-Checksum-SHA256": checksum,
            "X-Idempotency-Key": f"smoke:{MACHINE_ID}:{checksum[:16]}",
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def build_multipart(boundary: str, machine_id: str, timestamp: str, zip_bytes: bytes) -> bytes:
    lines = []
    lines.append(f"--{boundary}\r\n".encode())
    lines.append(b'Content-Disposition: form-data; name="machine_id"\r\n\r\n')
    lines.append(machine_id.encode() + b"\r\n")
    lines.append(f"--{boundary}\r\n".encode())
    lines.append(b'Content-Disposition: form-data; name="timestamp"\r\n\r\n')
    lines.append(timestamp.encode() + b"\r\n")
    lines.append(f"--{boundary}\r\n".encode())
    lines.append(b'Content-Disposition: form-data; name="batch_file"; filename="smoke.zip"\r\n')
    lines.append(b"Content-Type: application/zip\r\n\r\n")
    lines.append(zip_bytes + b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode())
    return b"".join(lines)


def main() -> int:
    print("healthz", get_json("/healthz"))
    print("readyz", get_json("/readyz"))
    print("upload", post_upload())
    time.sleep(4)
    print("machines", get_json("/api/machines"))
    print("queue", get_json("/api/queue/status"))
    print("worker", get_json("/api/worker/status"))
    print("image-flow", get_json(f"/api/image-flow/recent?machine_id={MACHINE_ID}&limit=3"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
