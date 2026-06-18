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
- [ ] Prepare queue handoff boundary in saved metadata

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

- [ ] Create `worker/` package and queue message contract
- [ ] Replace in-memory queue placeholders with Redis-backed pipeline
- [ ] Add real storage retention and cleanup jobs
