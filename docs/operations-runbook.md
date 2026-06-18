# Operations Runbook

## Startup Order

1. Start `server`
2. Verify `GET /healthz` and `GET /readyz`
3. Start `worker`
4. Start machine client agents
5. Open `dashboard/` and confirm live updates

## Configuration Overrides

- Machine client config path: `MIUS_MACHINE_CONFIG`
- Server config path: `MIUS_SERVER_CONFIG`
- Server host override: `MIUS_SERVER_HOST`
- Server port override: `MIUS_SERVER_PORT`
- Storage root override: `MIUS_STORAGE_ROOT`
- Queue root override: `MIUS_QUEUE_ROOT`
- Machine tokens JSON override: `MIUS_MACHINE_TOKENS_JSON`
- IP allowlist override: `MIUS_IP_ALLOWLIST`
- Trust proxy forwarding: `MIUS_TRUST_X_FORWARDED_FOR`

## Network Security

- Upload and dashboard access can be restricted with `ip_allowlist`
- If the server is behind Nginx or another reverse proxy, set `MIUS_TRUST_X_FORWARDED_FOR=true`
- Example TLS reverse proxy config is provided at `deploy/nginx/machine-image-uploader.conf`

## Upload Validation Behavior

- `E201`: checksum mismatch
  - Recovery: resend the same batch; if repeated, rebuild the batch file
- `E202`: missing checksum header
  - Recovery: machine client must send `X-Checksum-SHA256`
- `E203`: missing idempotency header
  - Recovery: machine client must send `X-Idempotency-Key`
- `E301`: server readiness failure
  - Recovery: check storage permissions and free disk space

## Restart Recovery

- Machine client moves `inflight/` batches back to `ready/` on startup
- Server queue moves `processing/` jobs back to `pending/` on startup
- Worker resumes from queue state files without rebuilding metadata

## Cleanup Policy

- Raw files older than `raw_retention_days` are deleted during server startup maintenance
- Temp files older than `temp_retention_hours` are deleted during server startup maintenance
- Sent client batches older than client retention are deleted locally

## Disk Pressure Guidance

- Machine buffer above configured threshold: staging pauses and warning is shown
- Machine buffer above 90%: critical pressure state, clear disk immediately
- Server storage above `max_disk_usage_percent`: investigate retention and free space before resuming load

## Service Deployment

Example unit files are provided under `deploy/systemd/`:

- `machine-client.service`
- `server.service`
- `worker.service`

## Backup and Restore

### Backup

- Runtime/config backup script: `deploy/scripts/backup-runtime.sh`
- Recommended backup targets:
  - `config.json`
  - `server-config.json`
  - `runtime/server-metadata/`
  - `runtime/server-queue/`

### Restore

1. Stop `server` and `worker`
2. Restore config files and runtime metadata
3. Ensure queue files are present under `runtime/server-queue/`
4. Start `server`, then `worker`
5. Confirm `readyz` passes and dashboard shows worker heartbeat

## Packaging

- Deployment bundle script: `deploy/scripts/package-release.sh`
- The generated archive excludes `.git`, `dist`, and `dashboard/node_modules`
