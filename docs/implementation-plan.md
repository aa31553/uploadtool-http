# Machine Image Uploader System Implementation Plan

## 1. Purpose

This document turns the current system design, server dashboard design, and machine client UI design into a phased delivery plan that can be executed step by step.

The goal is to move from the current skeleton code to a production-ready industrial image ingestion system with controlled risk.

---

## 2. Delivery Principles

- Keep machine capture independent from network transmission at all times
- Build the ingestion path before optimization layers
- Deliver observable milestones, not only internal refactors
- Prefer small deployable increments over a large one-shot rewrite
- Validate each stage with measurable acceptance criteria

---

## 3. Scope Summary

The implementation plan covers:

- Machine-side uploader agent
- Machine-side operator UI
- Ingestion server API
- Queue and worker pipeline
- Storage layout and retention
- Server monitoring dashboard
- Reliability, security, and rollout work

---

## 4. Phase Overview

| Phase | Goal | Main Output |
|------|------|-------------|
| Phase 0 | Foundation and environment | Repo structure, configs, dev standards |
| Phase 1 | Machine client MVP | Local config, buffer, upload loop, UI shell |
| Phase 2 | Ingestion server MVP | Upload API, raw file persistence, ACK flow |
| Phase 3 | Queue and worker pipeline | Queueing, batch extraction, compression, output storage |
| Phase 4 | Monitoring and dashboard | Metrics APIs, alerts, dashboard UI |
| Phase 5 | Reliability and fail-safe hardening | Retry, idempotency, recovery, retention, backup flow |
| Phase 6 | Security and deployment readiness | Auth, TLS strategy, packaging, service deployment |
| Phase 7 | Pilot rollout and production expansion | Factory pilot, benchmark, tuning, scale-out |

---

## 5. Phase 0: Foundation and Environment

### Objective

Make the codebase ready for parallel development and controlled testing.

### Tasks

- Finalize project layout for `machine_client`, `server`, and future `worker`
- Add separate requirements files or a unified dependency strategy
- Define runtime directories for uploads, processed files, logs, and temp files
- Add configuration templates for machine client and server
- Standardize logging format and error codes
- Add basic developer scripts for local startup
- Decide initial queue target for MVP: Redis is recommended

### Deliverables

- Stable folder structure
- `config.example.json` for machine client
- Server config template
- `.gitignore`
- Basic local run instructions

### Acceptance Criteria

- Team can run machine client shell and server shell locally
- Configuration locations are fixed and documented
- No ambiguous runtime path decisions remain

### Risks

- Starting feature work before config and storage conventions are fixed
- Mixing UI logic and uploader core too early

### Suggested Duration

- 2 to 3 days

---

## 6. Phase 1: Machine Client MVP

### Objective

Build the first usable machine-side uploader that can run independently of the server dashboard work.

### Tasks

- Implement machine config loading and saving
- Implement storage path validation
- Implement local disk-backed buffer abstraction
- Implement image discovery or capture integration entry point
- Implement batch builder using count or time threshold
- Implement HTTP uploader with timeout and retry
- Implement backup server failover behavior
- Implement machine client UI pages:
  - Dashboard
  - Upload settings
  - Network settings
  - Storage settings
  - Logs
- Implement `Test Connection`
- Ensure UI process failure does not stop uploader core

### Deliverables

- Runnable machine client application
- Persistent configuration file handling
- Buffered upload loop with retry
- Local logs for upload and retry events

### Acceptance Criteria

- Machine client can save config and restart with same settings
- When server is offline, files remain buffered locally
- When server recovers, buffered files resume uploading
- Upload ACK is required before local batch deletion
- UI can show online or offline status, buffer usage, and latest errors

### Risks

- Using only in-memory queue logic instead of disk-backed persistence
- Coupling UI actions directly to upload worker internals

### Suggested Duration

- 1 to 2 weeks

---

## 7. Phase 2: Ingestion Server MVP

### Objective

Receive machine uploads safely and return fast ACK without image processing in the request path.

### Tasks

- Finalize `POST /upload` request contract
- Add machine ID validation and token validation
- Persist uploaded batch files into raw storage area
- Generate upload metadata record
- Return ACK only after storage write succeeds
- Add structured logging for uploads and failures
- Add basic health endpoint and readiness endpoint
- Add runtime configuration for storage root and temp path

### Deliverables

- FastAPI ingestion service
- Raw upload storage layout
- Upload metadata persistence strategy
- Health endpoints for deployment

### Acceptance Criteria

- Server accepts batch uploads from machine client
- Upload returns ACK only after raw file is written
- Failed uploads do not leave machine client in false-success state
- Upload path can handle concurrent machine requests without blocking machine-side capture

### Risks

- Doing decompression or conversion inside upload request handling
- Missing storage write verification before ACK

### Suggested Duration

- 1 week

---

## 8. Phase 3: Queue and Worker Pipeline

### Objective

Move processing out of ingestion and build the real storage pipeline.

### Tasks

- Introduce queue backend, preferably Redis first and RabbitMQ later if needed
- Enqueue uploaded batch metadata after raw persistence
- Build worker process to consume queue messages
- Extract batches to temp working directory
- Validate files and optional checksums
- Compress images and convert formats to WebP or configured target
- Write processed images into final storage structure
- Separate raw and processed storage tiers
- Add worker error handling and retry strategy
- Add dead-letter or failed-job storage path for investigation

### Deliverables

- Worker service
- Queue integration
- Processed image storage output
- Failed-job handling path

### Acceptance Criteria

- Ingestion and processing are fully decoupled
- Processed files are stored under machine and date path layout
- Failed batches can be retried without corrupting state
- Raw files can be retained temporarily and cleaned by policy

### Risks

- No idempotency protection for repeated uploads or retries
- Temp extraction growth causing disk exhaustion

### Suggested Duration

- 1 to 2 weeks

---

## 9. Phase 4: Monitoring and Dashboard

### Objective

Provide one-screen operational visibility for machines, server load, queue pressure, and alerts.

### Tasks

- Define metrics collection points in server and worker
- Implement server metrics collection, either system-based or mocked first then real
- Implement machine status aggregation endpoint
- Implement queue status endpoint
- Implement storage status endpoint
- Implement alerts model and rule evaluation
- Implement WebSocket live update flow
- Build dashboard frontend shell
- Build main dashboard page with:
  - Global health bar
  - Machine grid
  - Server metrics panel
  - Queue monitor
  - Storage monitor
  - Alert center

### Deliverables

- Monitoring APIs
- Dashboard frontend MVP
- Live status updates
- Alert list and severity display

### Acceptance Criteria

- Operator can identify offline machine, queue growth, and disk risk from one screen
- API and WebSocket data match backend state within expected update interval
- Dashboard remains usable under 15-machine load

### Risks

- Building a visually rich dashboard before alert logic is trustworthy
- Pushing too much raw event traffic over WebSocket

### Suggested Duration

- 1 to 2 weeks

---

## 10. Phase 5: Reliability and Fail-Safe Hardening

### Objective

Close the gap between MVP and factory-safe behavior.

### Tasks

- Implement upload idempotency key strategy
- Implement checksum verification for uploaded batches
- Implement queue persistence and recovery tests
- Implement machine-side resume after restart
- Implement server-side safe restart behavior
- Implement cleanup policy for raw and temp files
- Implement disk usage guardrails on machine and server
- Implement backup server routing and failback policy
- Add operator-facing error codes and recovery guidance

### Deliverables

- Recovery-safe upload flow
- Persistent queue and restart recovery behavior
- Retention and cleanup jobs
- Error handling guidelines

### Acceptance Criteria

- Power loss or process restart does not silently lose buffered data
- Duplicate upload attempts do not create broken duplicate processing records
- Disk pressure generates warnings before service failure

### Risks

- Cleanup jobs deleting files still needed by queue or retry flow
- Retry loops causing storage duplication or queue storms

### Suggested Duration

- 1 to 2 weeks

---

## 11. Phase 6: Security and Deployment Readiness

### Objective

Prepare the system for controlled factory deployment.

### Tasks

- Add API token authentication to upload and management endpoints
- Bind token to allowed machine ID where required
- Add HTTPS or reverse proxy TLS strategy
- Add IP allowlist support for plant network
- Package machine client for deployment
- Package server and worker as services
- Define environment-specific configuration handling
- Add backup and restore procedure for config and metadata
- Add operational runbook for common failure scenarios

### Deliverables

- Deployment-ready services
- Security controls baseline
- Runbook and packaging instructions

### Acceptance Criteria

- Unauthorized requests are rejected
- Deployment steps are repeatable on clean hosts
- Operators have a written process for restart and recovery

### Risks

- Security added too late, forcing endpoint changes after client rollout
- No deployment automation leading to configuration drift

### Suggested Duration

- 1 week

---

## 12. Phase 7: Pilot Rollout and Production Expansion

### Objective

Validate the system in real factory conditions before broader rollout.

### Tasks

- Start with 1 to 2 machines in pilot environment
- Run throughput and recovery tests under real image generation load
- Measure ingest latency, queue depth, worker throughput, and disk growth
- Tune batch size, retry policy, and compression settings
- Expand to one full server group of around 15 machines
- Record incident lessons and adjust alert thresholds
- Decide when to upgrade queue or storage components

### Deliverables

- Pilot test report
- Performance tuning record
- Rollout decision checklist

### Acceptance Criteria

- Pilot proves non-blocking upload behavior
- Queue delay remains within operational target under expected load
- Storage growth and retention policy are understood and controlled
- Team is confident to scale from pilot to production group

### Risks

- Skipping pilot and discovering bottlenecks only during full rollout
- Using unrealistic test image patterns that hide burst behavior

### Suggested Duration

- 2 to 4 weeks including tuning

---

## 13. Cross-Phase Technical Workstreams

These tracks should continue across multiple phases.

### 13.1 Testing

- Unit tests for config, batching, retry, and validation
- Integration tests for upload to raw storage
- End-to-end tests for buffer to final storage
- Restart recovery tests
- Load tests for concurrent upload and worker throughput

### 13.2 Observability

- Structured logs
- Metrics naming conventions
- Alert thresholds and ownership
- Future Prometheus and Grafana integration

### 13.3 Data Management

- File naming rules
- Metadata schema
- Retention and cleanup policy
- Raw versus processed storage lifecycle

### 13.4 Operations

- Runbooks
- Deployment checklist
- Version compatibility between machine client and server

---

## 14. Recommended Implementation Order Inside the Current Repo

1. Finish machine client config save and validation flow
2. Finish server upload contract and raw storage persistence
3. Add worker package and local queue-backed processing flow
4. Replace mock monitoring data with real service metrics
5. Build dashboard frontend against stable monitoring APIs
6. Harden retry, idempotency, cleanup, and restart recovery
7. Prepare packaging and pilot deployment

---

## 15. MVP Definition

The first meaningful MVP is reached when all of the following are true:

- Machine client can buffer and upload batches
- Server can persist uploaded batch files and ACK safely
- Worker can convert batches into processed storage output
- Queue decouples ingestion from processing
- Basic dashboard shows machine, queue, storage, and alert status

This MVP does not require:

- Kafka
- AI anomaly detection
- Multi-region sync
- GPU acceleration

---

## 16. Production Readiness Checklist

- Upload path is non-blocking for machine capture
- Local buffer survives restart and network outages
- ACK behavior is storage-safe
- Queue persistence is enabled
- Worker retry behavior is defined
- Disk cleanup policy is active
- Authentication is enabled
- Monitoring and alerts are visible in one screen
- Pilot throughput data has been collected

---

## 17. Recommended Next Coding Tasks

Based on the current repository status, the most practical next tasks are:

1. Implement machine client config save and field validation
2. Implement real `Test Connection` in machine client
3. Add server config, token validation, and upload metadata recording
4. Create `worker/` package and queue message contract
5. Add periodic WebSocket push instead of one-time snapshot
