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

---

## Components

### 1. Machine Agent

- Collect images
- Local buffer storage
- Batch compression
- Async upload

### 2. Ingestion Server (FastAPI)

- Receive uploads
- Validate machine ID
- Store raw batch
- Push to queue

### 3. Queue

- Redis / RabbitMQ
- Decouple ingestion and processing

### 4. Worker

- Extract batch
- Compress images
- Convert format
- Save to storage

### 5. Monitoring Dashboard

- Machine overview
- Server metrics
- Queue monitor
- Storage status
- Alert center

### 6. Machine Client UI

- Server endpoint configuration
- Local storage path configuration
- Local buffer monitoring
- Retry and log visibility

---

## Storage Structure

```text
/storage/
  MACHINE_ID/
    YYYY/
      MM/
        DD/
          image.webp
```

---

## Documentation

- System design spec: `docs/system-design-spec.md`
- Dashboard UI/UX design: `docs/ui-ux-dashboard-design.md`
- Machine client UI spec: `docs/machine-client-ui-spec.md`

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
pip install fastapi uvicorn redis pillow opencv-python
```

### Run API server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Run worker

```bash
python worker.py
```

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
