# Machine Image Uploader System

High-throughput machine image upload and compression pipeline to replace SMB-based transfer.

---

## Overview

This system is designed for multiple machines producing images at high frequency
(about 10 FPS per machine), and provides a stable, high-throughput, scalable
upload and compression workflow.

---

## Why Replace SMB?

- SMB connection limits can cause upload failures
- High-frequency IO can block or slow machine operation
- No built-in buffering for network instability
- Uncompressed storage fills up quickly
- SMB is not suitable for sustained 300MB/s-class ingestion

---

## Architecture

```text
Machine Agent -> FastAPI Ingestion -> Queue -> Worker -> Storage
                 ^
                 |
          Control Plane / Fleet Dashboard
```

---

## Features

- Non-blocking machine upload
- Batch upload to reduce network overhead
- Automatic retry mechanism
- Image compression (JPEG/WebP)
- Folder auto-organization
- Scalable worker architecture
- Queue-based decoupling
- Industrial monitoring dashboard planning
- Machine-side client configuration UI planning
- Source image preservation: originals stay in `image_root` and are only copied into the upload buffer
- Recursive segmented scan under `image_root` with `source-index`, `directory-index`, and `staged-index`
- Relative path preservation from machine source tree through upload and processed storage
- Cross-platform server metrics via `psutil`
- Self-hosted dashboard and API docs (no external CDN required)
- Separate executable packages for server and machine client
- Centralized control plane for login, server registry, fleet monitoring, and unified dashboard

---

## Components

### 1. Machine Agent

- Collect images from `image_root`
- Preserve original source files (never moved or deleted)
- Copy new or modified images into a local buffer
- Recursively scan nested folders using segmented scan units
- Preserve relative source path in staged files, manifests, and uploaded batches
- Build compressed batches and upload asynchronously
- Retry failed uploads and support backup server fallback

### 2. Ingestion Server (FastAPI)

- Receive uploads
- Validate machine ID and API token
- Store raw batch files with checksum verification
- Push jobs into the queue with idempotency protection
- Serve dashboard, Swagger UI, and ReDoc as self-hosted static assets

### 3. Queue

- File-backed queue by default
- Optional Redis backend via `queue_backend: redis`
- Decouple ingestion and processing

### 4. Worker

- Extract batches into a temp workspace
- Validate image files
- Convert to WebP when Pillow is available
- Save processed files into `processed/<machine>/<relative_path>`
- Write failed jobs into an investigation path

### 5. Monitoring Dashboard

- Machine overview
- Cross-platform server metrics (CPU, RAM, disk, network via `psutil`)
- Queue monitor
- Storage status
- Alert center

### 6. Machine Client UI

- Server endpoint configuration
- Control plane endpoint configuration
- Local storage path configuration
- Local buffer monitoring
- Retry and log visibility
- Centralized operator login, password change, and admin account actions

### 7. Control Plane

- Centralized user authentication and authorization
- Server registry and fleet polling
- Unified dashboard APIs and WebSocket updates
- Aggregated machine, queue, worker, storage, and alert views

---

## Storage Structure

```text
/storage/
  MACHINE_ID/
    B07-01/
      LOT001/
        NG/
          image.webp
```

---

## Documentation

- System design spec: `docs/system-design-spec.md`
- Dashboard UI/UX design: `docs/ui-ux-dashboard-design.md`
- Machine client UI spec: `docs/machine-client-ui-spec.md`
- Implementation plan: `docs/implementation-plan.md`
- Operations runbook: `docs/operations-runbook.md`
- Executable packaging: `docs/executable-packaging.md`
- Multi-server control plane spec: `docs/multi-server-control-plane-spec.md`
- Path-preserving upload change spec: `docs/path-preserving-upload-change-spec.md`

---

## Frontend

- Runtime dashboard: `server/static/dashboard/` (no npm dependency at runtime)
- Fleet control dashboard: `control_server/static/dashboard/`
- Swagger UI bundle: `server/static/vendor/swagger-ui-bundle.js`
- Swagger UI CSS: `server/static/vendor/swagger-ui.css`
- ReDoc bundle: `server/static/vendor/redoc.standalone.js`
- Legacy React source/build (optional dev workspace only): `dashboard/`

### Optional dashboard development workspace

```bash
cd dashboard
npm install
npm run dev
```

### Offline dashboard via backend static hosting

Start only the Python server and open:

```text
http://127.0.0.1:8000/dashboard/
```

Swagger UI and ReDoc are also self-hosted and do not need external CDNs:

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/redoc
```

---

## Deployment Notes

- Systemd unit examples: `deploy/systemd/`
- TLS reverse proxy example: `deploy/nginx/machine-image-uploader.conf`
- Source release archive: `deploy/scripts/package-release.sh`
- Standalone executable build scripts:
  - `deploy/scripts/build-server-exe.sh`
  - `deploy/scripts/build-machine-client-exe.sh`
- PyInstaller spec files:
  - `packaging/pyinstaller/server.spec`
  - `packaging/pyinstaller/machine_client.spec`
- Backup script: `deploy/scripts/backup-runtime.sh`
- Smoke test script: `scripts/smoke_test.py`
- Config path overrides:
  - `MIUS_MACHINE_CONFIG`
  - `MIUS_SERVER_CONFIG`
  - `MIUS_CONTROL_CONFIG`
- Server environment overrides:
  - `MIUS_SERVER_HOST`
  - `MIUS_SERVER_PORT`
  - `MIUS_STORAGE_ROOT`
  - `MIUS_QUEUE_ROOT`
  - `MIUS_MACHINE_TOKENS_JSON`
  - `MIUS_IP_ALLOWLIST`
  - `MIUS_TRUST_X_FORWARDED_FOR`

---

## Performance Target

| Metric | Target |
|--------|--------|
| Throughput | 300MB/s per server |
| Latency | < 2 sec ingest |
| Compression ratio | 40~70% reduction |
| Uptime | 99.9% |

---

## Security

- API Token authentication
- Machine ID validation
- Optional HTTPS
- Network isolation support

---

## Retry Strategy

- Exponential backoff
- Local disk buffer fallback
- Queue persistence

---

## Tech Stack

- Python 3.10+
- FastAPI
- Redis / RabbitMQ
- Pillow / OpenCV
- WebP encoder
- PyQt5 / PySide6 for machine client UI

---

## Deployment

### Install dependencies

```bash
pip install -r requirements-machine-client.txt -r requirements-server.txt -r requirements-worker.txt -r requirements-control-server.txt
```

### Run API server

```bash
python -m server
```

The same server also serves the local dashboard static site, Swagger UI, and ReDoc without external network resources.

### Run control plane server

```bash
python -m control_server
```

The control plane serves the centralized fleet dashboard and auth APIs:

```text
http://127.0.0.1:8100/dashboard/
```

### Run worker

```bash
python -m worker
```

### Run machine client

```bash
python -m machine_client
```

#### Source image preservation mode

The machine client never moves or deletes files from `image_root`.

- Original photos stay in place
- New or modified files are copied into the local buffer
- Recursive segmented scan discovers images inside nested folders under `image_root`
- Relative path is preserved through:
  - `source-index.json`
  - `directory-index.json`
  - `staged-index.json`
  - batch manifest and zip entries
- A per-path signature index (`<buffer_path>/source-index.json`) prevents re-uploading the same source file
- When a source file content changes, it is uploaded again on the next cycle

### Run maintenance cleanup once

```bash
python -m server.maintenance_main
```

### Run smoke test

```bash
python scripts/smoke_test.py http://127.0.0.1:8000 replace-me MC01
```

### Build executable packages

```bash
pip install -r requirements-packaging.txt
bash deploy/scripts/build-server-exe.sh
bash deploy/scripts/build-machine-client-exe.sh
```

Server output:

```text
dist/uploadtool-server/
```

Machine client output:

```text
dist/uploadtool-client/
```

See `docs/executable-packaging.md` for platform notes and runtime layout.

---

## Future Improvements

- Kafka streaming pipeline
- GPU-based image compression
- Edge computing preprocessing
- Multi-region storage sync
- Real-time dashboard (Grafana)
- Industrial web dashboard
- Full machine-side operator console

---

## Key Design Principle

> Never let image capture depend on network transmission.

---

## Author

System designed for a high-throughput industrial machine imaging pipeline.
