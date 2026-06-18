# TODO

## Phase 1: Machine Client MVP

### Tasks

- [x] Finalize persistent config path and default bootstrap behavior
- [x] Implement config validation for URL, paths, disk threshold, and upload settings
- [x] Implement config save flow from UI
- [x] Implement `Test Connection` against server health and upload endpoint
- [x] Implement disk-backed buffer directories and manifests
- [x] Implement source image staging from `image_root`
- [x] Implement batch creation by image count and age threshold
- [x] Implement upload loop with retry and ACK-based deletion
- [x] Implement backup server fallback
- [x] Implement UI status refresh from real agent state
- [x] Implement queue monitor tab and live logs
- [x] Keep uploader core independent from UI event loop

### File Design

- `machine_client/config.py`
  - Load, save, and validate machine client config
- `machine_client/disk_queue.py`
  - Manage staged files, ready batches, inflight batches, and manifests
- `machine_client/transport.py`
  - HTTP health check, test upload, and batch upload client
- `machine_client/agent.py`
  - Background loop, counters, retry logic, and status snapshots
- `machine_client/ui.py`
  - Operator UI, settings save, connection test, and log view
- `machine_client/main.py`
  - Config bootstrap and app startup
- `config.json`
  - Local machine-specific runtime config

## Phase 2: Ingestion Server MVP

### Tasks

- [x] Add server runtime config loader
- [x] Add allowed machine and token validation
- [x] Add health and readiness endpoints
- [x] Persist raw upload files into configurable raw storage root
- [x] Record upload metadata to durable local file
- [x] Track recent upload state for monitoring APIs
- [x] Return ACK only after raw file and metadata are stored
- [x] Improve WebSocket live endpoint to push snapshots periodically
- [x] Prepare queue handoff boundary in saved metadata

### File Design

- `server/config.py`
  - Load server config, storage paths, and machine token rules
- `server/storage.py`
  - Persist raw upload files and metadata
- `server/routes.py`
  - Upload, health, readiness, monitoring, and WebSocket endpoints
- `server/store.py`
  - Runtime machine status and dashboard snapshot data
- `server/models.py`
  - API response models and upload metadata shape
- `server-config.json`
  - Server-specific runtime config

## Next After Phase 2

## Phase 3: Queue and Worker Pipeline

### Tasks

- [x] Add file-backed queue contract for pending, processing, completed, and failed jobs
- [x] Enqueue upload metadata immediately after raw persistence
- [x] Add worker runtime state file and heartbeat
- [x] Build worker loop that claims jobs from queue
- [x] Extract uploaded zip into temp workspace
- [x] Validate extracted image files and manifest fields
- [x] Write processed files into `/processed/<machine>/<YYYY>/<MM>/<DD>/`
- [x] Record worker completion and failure metadata
- [x] Move failed jobs into investigation path with retry tracking

### File Design

- `server/queue.py`
  - File-backed queue message contract and directory transitions
- `worker/service.py`
  - Worker poll loop, queue claiming, retries, and state heartbeat
- `worker/processor.py`
  - Zip extraction, file validation, and processed output writing
- `worker/main.py`
  - Worker bootstrap using shared server config

## Phase 4: Monitoring and Dashboard Backend

### Tasks

- [x] Replace purely random monitoring data with runtime-derived snapshots
- [x] Compute machine status from actual upload events and queue depth
- [x] Compute queue metrics from queue directories and worker state
- [x] Compute storage usage from real filesystem paths
- [x] Compute ingest and processing throughput from recent metadata
- [x] Push richer WebSocket snapshots including worker state
- [x] Add alert rules for offline machine, queue backlog, worker stale heartbeat, and disk pressure

### File Design

- `server/store.py`
  - Runtime snapshot builder from upload metadata, queue stats, and worker state
- `worker/state.py`
  - Worker heartbeat and performance state persistence
- `server/routes.py`
  - Monitoring APIs and WebSocket payload assembly

## Phase 4: Dashboard Frontend

### Tasks

- [x] Add dashboard frontend scaffold
- [x] Wire dashboard homepage to monitoring HTTP APIs
- [x] Wire dashboard homepage to `/ws/live` stream
- [x] Implement top status bar, machine grid, metrics, queue, storage, worker, and alerts panels
- [x] Add drill-down pages for image flow and machine details
- [x] Add charting library integration for time-series panels

### File Design

- `dashboard/src/App.jsx`
  - Dashboard homepage composition and live state wiring
- `dashboard/src/api.js`
  - API and WebSocket integration
- `dashboard/src/styles.css`
  - Industrial monitoring visual language and responsive layout

## Next After Phase 4

- [x] Replace file queue with Redis-backed pipeline when multi-process scale is needed
- [x] Add real storage retention and cleanup jobs

## Phase 5: Reliability and Fail-Safe Hardening

### Tasks

- [x] Add batch checksum generation and server-side verification
- [x] Add idempotency key generation and duplicate upload handling
- [x] Recover machine-side inflight batches on restart
- [x] Recover server-side processing jobs on restart
- [x] Add raw and temp cleanup policy execution
- [x] Add disk pressure guardrails on machine and server
- [x] Keep backup server fallback and primary failback behavior deterministic
- [x] Add retry-safe worker failure handling metadata
- [x] Add operator-facing error codes and recovery guidance in upload path

### File Design

- `machine_client/disk_queue.py`
  - Inflight recovery, manifest checksum, and disk pressure stats
- `machine_client/transport.py`
  - Upload checksum and idempotency headers
- `server/storage.py`
  - Checksum validation, idempotency index, and duplicate ACK behavior
- `server/queue.py`
  - Recovery of stale processing jobs
- `server/maintenance.py`
  - Raw/temp cleanup and storage guardrails

## Phase 6: Security and Deployment Readiness

### Tasks

- [x] Add environment-variable overrides for runtime config
- [x] Add config path overrides for machine client, server, and worker
- [x] Add IP allowlist support for plant network
- [x] Add HTTPS or reverse proxy TLS strategy artifacts
- [x] Add deployment service unit examples for server and worker
- [x] Add machine agent service example for startup behavior
- [x] Add packaging script for deployment bundle
- [x] Add backup and restore procedure for config and metadata
- [x] Add operations runbook baseline
- [x] Add environment and deployment documentation in README

### File Design

- `server/config.py`
  - Config load plus environment overrides
- `machine_client/main.py`
  - Machine config path override support
- `server/main.py`
  - Server config path override support
- `worker/main.py`
  - Worker config path override support
- `deploy/systemd/*.service`
  - Example service units
- `docs/operations-runbook.md`
  - Restart, recovery, and validation procedures
