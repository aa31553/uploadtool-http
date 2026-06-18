# Machine Image Uploader System

## 1. Project Name

**Machine Image Upload and Compression Processing System**

---

## 2. Background and Current Problems

### 2.1 Current SMB-Based Architecture Issues

The existing system uses SMB shared folders for image upload, which causes the following problems:

- Machine connection count can reach the SMB limit and cause upload failures
- High-frequency writes (about 10 FPS per machine) create heavy IO pressure
- Network file locking and sync delay can affect machine operation
- No buffering mechanism means network issues can cause data loss
- Uncompressed storage quickly consumes disk capacity

### 2.2 System Scale

| Item | Value |
|------|-------|
| Machine count | About 15 machines / server |
| Per-machine rate | 10 images / sec |
| Single image size | About 2 MB |
| Total traffic | About 300 MB/s (uncompressed) |

---

## 3. Design Goals

### 3.1 Core Goals

- Do not affect machine operation (zero blocking)
- Remove SMB dependency
- Support high-throughput image upload
- Support horizontal scaling
- Reduce storage cost through compression and tiered storage
- Ensure data durability with retry and buffering

### 3.2 Non-Functional Requirements

- Support more than 300MB/s ingestion
- Support more than 150 img/sec per server
- Support reconnect and retry
- Queue entry latency under 2 seconds
- Reduce stored size by 40~70% after compression

---

## 4. Overall Architecture

```text
                 +--------------------+
                 |   Machine Devices  |
                 |   (Python Agent)   |
                 +---------+----------+
                           |
                           | HTTP Batch Upload
                           v
              +------------------------+
              |  Ingestion API Server  |
              |       (FastAPI)        |
              +---------+--------------+
                        |
                        | enqueue
                        v
              +------------------------+
              | Message Queue          |
              | (Redis / RabbitMQ)     |
              +---------+--------------+
                        |
                        v
              +------------------------+
              | Worker Cluster         |
              | - decompress batch     |
              | - image compress       |
              | - format convert       |
              +---------+--------------+
                        |
                        v
              +------------------------+
              | Storage Layer          |
              | NAS / Disk / MinIO     |
              +------------------------+
```

---

## 5. Module Design

### 5.1 Machine Agent (Uploader)

#### Responsibilities

- Local image buffering
- Batch compression (zip/zstd)
- Asynchronous upload
- Failed upload retry queue
- No blocking of image generation workflow

#### Flow

```text
Capture Image
   |
   v
Write to local buffer
   |
   v
Batch every N seconds / N images
   |
   v
Compress (zip/zstd)
   |
   v
Async upload via HTTP
   |
   v
Server ACK -> delete local batch
```

#### Design Rules

- Async thread or asyncio based implementation
- Disk-backed local queue
- Upload timeout retry with exponential backoff
- Network failure fallback storage

### 5.2 Ingestion API Server (FastAPI)

#### Responsibilities

- Receive batch files
- Validate machine ID
- Write to raw storage
- Push message into queue
- Return ACK quickly

#### Boundaries

- Does not perform compression
- Does not perform image processing
- Only handles ingestion

#### API

```text
POST /upload
```

#### Payload

- `machine_id`
- `timestamp`
- `batch_file` (zip)

### 5.3 Message Queue

#### Recommended Options

- Redis for lightweight MVP
- RabbitMQ for stable production use
- Kafka for very high throughput

#### Responsibilities

- Decouple ingestion from processing
- Buffer traffic spikes
- Provide retry mechanism

### 5.4 Worker (Image Processing Core)

#### Responsibilities

- Extract batch
- Compress images
- Convert formats (JPEG -> WebP)
- Organize directory structure
- Save processed files into storage

#### Compression Strategy

| Method | Expected Effect |
|--------|-----------------|
| JPEG quality 75 | -30% to -50% |
| WebP | -40% to -70% |
| Thumbnail | Optimized for browsing/query |

#### Storage Layout

```text
/storage/
  MC01/
    2026/
      06/
        18/
          img_00001.webp
```

### 5.5 Storage Layer

#### Candidate Options

- Local disk for early phase
- NAS for medium scale
- MinIO for S3-compatible object storage

#### Recommendations

- Separate raw and compressed storage tiers
- Apply lifecycle policy to clean old raw files automatically

---

## 6. Performance Design

### 6.1 Throughput Targets

| Item | Value |
|------|-------|
| Ingestion | 300MB/s |
| Worker processing | Horizontal scaling |
| Latency | < 2s queue delay |

### 6.2 Pressure Control

- Batch upload
- Queue backpressure
- Worker autoscaling
- Disk buffering

---

## 7. Reliability Design

### 7.1 Fail-Safe Mechanisms

- Local buffer for disconnection protection
- Retry queue
- Checksum verification
- Idempotent upload

### 7.2 Data Durability Strategy

- Delete local file only after upload ACK
- Server writes to storage first, then enqueues
- Queue persistence must be enabled

---

## 8. Security Design

- API token authentication
- Machine ID binding
- Optional TLS / HTTPS
- IP whitelist for factory environments

---

## 9. Scalability Design

- Horizontal worker scaling
- Multi-server ingestion deployment
- Per-machine routing shard
- Storage scaling from NAS to S3-compatible object storage

---

## 10. Technology Choices

| Module | Technology |
|--------|------------|
| API | FastAPI |
| Queue | Redis / RabbitMQ |
| Worker | Python multiprocessing |
| Compression | Pillow / OpenCV / pywebp |
| Agent | Python asyncio |
| Storage | NAS / MinIO |

---

## 11. Operations Dashboard and Frontend Plan

The system should include an operations dashboard for real-time monitoring and troubleshooting.
This dashboard is part of the production operating model, not an optional reporting page.

Core frontend modules:

- Machine overview
- Server metrics panel
- Queue monitor
- Storage monitor
- Image flow viewer
- Alert center

Frontend requirements:

- Real-time first design
- One-screen health visibility
- Red-first abnormal state emphasis
- Minimal navigation depth
- SCADA-like industrial monitoring presentation

Recommended frontend architecture:

- React or Vue 3 frontend
- WebSocket-based live update channel
- ECharts or Recharts for metrics visualization
- Zustand or Pinia for client-side state management

Recommended backend endpoints for UI:

- `GET /api/machines`
- `GET /api/server/metrics`
- `GET /api/queue/status`
- `GET /api/storage/status`
- `/ws/live`

For the full dashboard specification, see `docs/ui-ux-dashboard-design.md`.

---

## 12. Machine Client UI and Configuration Plan

The machine-side agent should include a lightweight operator UI for setup, monitoring, and recovery.
This interface is intended for factory operation and must remain safe under poor network conditions.

Core machine client modules:

- Dashboard
- Upload settings
- Storage settings
- Network settings
- Queue monitor
- Logs

Functional requirements:

- Configure primary and backup server endpoints
- Configure image root path and buffer path
- Monitor FPS, upload success rate, latency, and buffer usage
- Show retry status, upload failures, and disk pressure
- Continue operating in offline mode with disk-backed buffering

Machine client UX requirements:

- Low CPU and low IO overhead
- Three-click configuration where practical
- Fail-safe defaults
- Red-first warning design for disconnect and storage risk
- UI failure must not interrupt capture or upload buffering

Recommended implementation:

- PyQt5 or PySide6 desktop client
- Async uploader core separated from UI process concerns
- Disk-backed local queue
- Connection test flow before saving configuration

Suggested settings validation:

- Server URL reachability check
- API token validation before save
- Storage path existence check
- Disk usage cap must remain at or below 95 percent

For the full machine client UI specification, see `docs/machine-client-ui-spec.md`.

---

## 13. Delivery Plan

Implementation should proceed in phases rather than as a single cutover.

Recommended phase order:

- Foundation and environment
- Machine client MVP
- Ingestion server MVP
- Queue and worker pipeline
- Monitoring dashboard
- Reliability hardening
- Security and deployment readiness
- Pilot rollout and production expansion

For the detailed execution plan, deliverables, acceptance criteria, and risks, see `docs/implementation-plan.md`.
