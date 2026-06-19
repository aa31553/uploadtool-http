# Multi-Server Control Plane Data Model and API Specification

## 1. Purpose

This document defines the detailed data structures and API contracts for a multi-server control plane.

The control plane is responsible for:

- Centralized user authentication and role-based access control
- Server registry for multiple ingestion nodes
- Aggregated monitoring across all servers and machines
- Unified dashboard APIs for fleet-wide visibility
- Audit logging for security-sensitive actions

This control plane does not handle image uploads directly.
Image ingestion, queueing, processing, and storage remain on each ingestion server.

---

## 2. Design Goals

- Keep image upload paths independent from centralized monitoring
- Provide one dashboard for all servers, workers, queues, and machines
- Centralize account management and password policies
- Avoid copying user password data to every ingestion server
- Allow gradual rollout without breaking the current single-server deployment

---

## 3. Scope

This specification covers:

- Control plane service responsibilities
- Logical data model
- JSON object shapes
- REST API contracts
- WebSocket live update contract
- Authentication and authorization model
- Control plane to ingestion server integration model

This specification does not define:

- Final database technology choice
- Full frontend visual design
- Image upload request contract changes

---

## 4. Topology

```text
Machine Client -> Ingestion Server A -> Queue/Worker A -> Storage A
Machine Client -> Ingestion Server B -> Queue/Worker B -> Storage B
Machine Client -> Ingestion Server C -> Queue/Worker C -> Storage C

                    \        |        /
                     \       |       /
                      v      v      v
                 Central Control Server
                 - Auth / RBAC
                 - Server registry
                 - Metrics aggregation
                 - Fleet dashboard API
                 - Audit logs

Dashboard UI -> Central Control Server
Machine Client UI -> Central Control Server for login and account actions
```

---

## 5. Control Plane Responsibilities

### 5.1 Authentication and Authorization

- Login using employee ID and password
- Issue access token and refresh token
- Register users
- Change password
- Reset password
- Disable or enable users
- Enforce role-based access control

### 5.2 Fleet Monitoring

- Poll or subscribe to each ingestion server
- Normalize local snapshots into one fleet model
- Compute fleet-wide health and alerts
- Provide unified APIs for dashboard and machine drill-down

### 5.3 Server Registry

- Register ingestion servers
- Store metadata such as site, labels, enabled state, and credentials
- Track last successful poll and server reachability

### 5.4 Audit Logging

- Record who logged in
- Record who registered users
- Record who reset passwords
- Record who changed server registry state

---

## 6. Roles and Permissions

### 6.1 Roles

| Role | Purpose |
|------|---------|
| `admin` | User management, server registry, fleet visibility, password reset |
| `supervisor` | Fleet visibility and diagnostics, no user management |
| `operator` | Machine client login and limited local configuration |

### 6.2 Optional Future Scope Filters

The control plane should allow future authorization scopes:

- `site_ids`
- `server_ids`
- `machine_ids`

These fields are optional in phase 1 but should be reserved in the data model.

---

## 7. Authentication Model

### 7.1 Recommended Token Strategy

- Access token: JWT, 15 minutes
- Refresh token: opaque token or JWT, 8 to 12 hours
- Passwords stored only in the control plane
- Ingestion servers validate control-plane-issued tokens

### 7.2 Recommended JWT Claims

| Claim | Meaning |
|------|---------|
| `sub` | Employee ID |
| `role` | User role |
| `token_version` | For revocation after password reset or account disable |
| `site_ids` | Optional allowed sites |
| `server_ids` | Optional allowed servers |
| `machine_ids` | Optional allowed machines |
| `iat` | Issued at |
| `exp` | Expiration |
| `iss` | Control plane issuer |
| `aud` | Client audience such as `dashboard` or `machine-client` |

### 7.3 Token Validation Modes

Two validation modes are allowed:

1. Simple mode
   - Ingestion server calls control plane introspection endpoint
2. Preferred mode
   - Control plane exposes JWKS or public key
   - Ingestion server validates JWT locally

Preferred mode is recommended for production.

---

## 8. Logical Data Model

### 8.1 Users

Represents centralized employee accounts.

| Field | Type | Required | Notes |
|------|------|----------|-------|
| `employee_id` | string | yes | Unique login identifier |
| `display_name` | string | yes | Human-friendly name |
| `role` | string | yes | `admin`, `supervisor`, or `operator` |
| `password_hash` | string | yes | Stored only on control plane |
| `password_salt` | string | yes | Optional if hash format already embeds salt |
| `enabled` | boolean | yes | Disabled users cannot log in |
| `token_version` | integer | yes | Increment to revoke prior tokens |
| `site_ids` | array[string] | no | Optional scope filter |
| `server_ids` | array[string] | no | Optional scope filter |
| `machine_ids` | array[string] | no | Optional scope filter |
| `created_at` | datetime | yes | ISO 8601 |
| `updated_at` | datetime | yes | ISO 8601 |
| `password_changed_at` | datetime | yes | ISO 8601 |
| `last_login_at` | datetime | no | ISO 8601 |

### 8.2 User Sessions

Represents active refreshable sessions.

| Field | Type | Required | Notes |
|------|------|----------|-------|
| `session_id` | string | yes | Unique session identifier |
| `employee_id` | string | yes | Linked user |
| `refresh_token_hash` | string | yes | Never store refresh token in plaintext |
| `client_type` | string | yes | `dashboard` or `machine-client` |
| `client_id` | string | no | Optional machine ID or browser instance |
| `issued_at` | datetime | yes | ISO 8601 |
| `expires_at` | datetime | yes | ISO 8601 |
| `last_seen_at` | datetime | no | ISO 8601 |
| `revoked_at` | datetime | no | ISO 8601 |
| `source_ip` | string | no | For audit and anomaly checks |

### 8.3 Registered Servers

Represents each ingestion server managed by the control plane.

| Field | Type | Required | Notes |
|------|------|----------|-------|
| `server_id` | string | yes | Unique server key |
| `name` | string | yes | Human-friendly label |
| `base_url` | string | yes | Base URL for local metrics APIs |
| `site` | string | yes | Factory, line, or plant grouping |
| `labels` | object | no | Free-form metadata |
| `enabled` | boolean | yes | Disabled servers are excluded from polling |
| `auth_mode` | string | yes | `shared_secret` or `mtls` |
| `shared_secret_hash` | string | no | If `shared_secret` is used |
| `public_key_id` | string | no | Optional future use |
| `poll_interval_sec` | integer | yes | Recommended 1 to 10 seconds |
| `timeout_sec` | integer | yes | Request timeout |
| `last_seen_at` | datetime | no | Last successful metrics collection |
| `last_error` | string | no | Most recent polling error |
| `created_at` | datetime | yes | ISO 8601 |
| `updated_at` | datetime | yes | ISO 8601 |

### 8.4 Server Snapshot

Represents normalized state of one ingestion server at a point in time.

| Field | Type | Required | Notes |
|------|------|----------|-------|
| `server_id` | string | yes | Linked server |
| `collected_at` | datetime | yes | Time control plane stored snapshot |
| `source_timestamp` | datetime | no | Timestamp reported by ingestion server |
| `status` | string | yes | `online`, `warning`, `degraded`, `offline` |
| `health_ok` | boolean | yes | Health or readiness summary |
| `server_metrics` | object | yes | CPU, RAM, disk, network, load |
| `queue` | object | yes | Queue depth, processing rate, backlog |
| `storage` | object | yes | Usage and growth |
| `worker` | object | yes | Worker state |
| `machine_count` | integer | yes | Count of active machines known by that server |
| `alert_count` | integer | yes | Count of active alerts |
| `alerts` | array[object] | no | Optional denormalized latest alerts |

### 8.5 Machine Snapshot

Represents latest known state of one machine as seen by a specific ingestion server.

| Field | Type | Required | Notes |
|------|------|----------|-------|
| `machine_id` | string | yes | Machine identifier |
| `server_id` | string | yes | Current owning ingestion server |
| `site` | string | no | Optional denormalized grouping |
| `status` | string | yes | `online`, `warning`, `offline` |
| `fps` | number | yes | Effective upload rate |
| `latency_ms` | integer | yes | Latest latency |
| `queue_size` | integer | yes | Local queue depth |
| `last_upload` | datetime | yes | Last upload seen |
| `updated_at` | datetime | yes | Last snapshot update |

### 8.6 Alert Records

Represents fleet or server alerts.

| Field | Type | Required | Notes |
|------|------|----------|-------|
| `alert_id` | string | yes | Unique alert id |
| `level` | string | yes | `info`, `warning`, `critical` |
| `source_type` | string | yes | `fleet`, `server`, `machine`, `worker`, `storage`, `queue` |
| `source_id` | string | yes | Example `srv-a` or `MC01` |
| `server_id` | string | no | Owning server if applicable |
| `machine_id` | string | no | Affected machine if applicable |
| `message` | string | yes | Operator-facing text |
| `code` | string | no | Structured code |
| `created_at` | datetime | yes | ISO 8601 |
| `cleared_at` | datetime | no | ISO 8601 |
| `status` | string | yes | `active` or `cleared` |

### 8.7 Audit Logs

Represents security-sensitive or operational actions.

| Field | Type | Required | Notes |
|------|------|----------|-------|
| `audit_id` | string | yes | Unique id |
| `actor_employee_id` | string | yes | Who performed the action |
| `actor_role` | string | yes | Role at time of action |
| `action` | string | yes | Example `user.register`, `server.disable` |
| `target_type` | string | yes | `user`, `server`, `machine`, `session` |
| `target_id` | string | yes | Target identifier |
| `result` | string | yes | `success` or `failure` |
| `details` | object | no | Structured metadata |
| `source_ip` | string | no | Optional request IP |
| `created_at` | datetime | yes | ISO 8601 |

---

## 9. JSON Shapes

### 9.1 User Summary

```json
{
  "employee_id": "E1001",
  "display_name": "Alice Chen",
  "role": "admin",
  "enabled": true,
  "site_ids": ["plant-a"],
  "server_ids": [],
  "machine_ids": [],
  "created_at": "2026-06-18T09:00:00Z",
  "updated_at": "2026-06-18T09:00:00Z",
  "password_changed_at": "2026-06-18T09:00:00Z",
  "last_login_at": "2026-06-18T10:02:11Z"
}
```

### 9.2 Server Summary

```json
{
  "server_id": "srv-a",
  "name": "Ingestion Server A",
  "base_url": "https://srv-a.example.com",
  "site": "plant-a",
  "enabled": true,
  "status": "online",
  "machine_count": 15,
  "alert_count": 2,
  "last_seen_at": "2026-06-18T10:04:12Z",
  "last_error": null
}
```

### 9.3 Fleet Overview

```json
{
  "timestamp": "2026-06-18T10:04:12Z",
  "fleet_status": "warning",
  "server_counts": {
    "total": 3,
    "online": 2,
    "warning": 1,
    "degraded": 0,
    "offline": 0
  },
  "machine_counts": {
    "total": 42,
    "online": 38,
    "warning": 3,
    "offline": 1
  },
  "queue": {
    "total_queue_length": 128,
    "total_processing_rate": 850.4,
    "backlog_delta": 12
  },
  "storage": {
    "total_used_tb": 8.34,
    "total_capacity_tb": 24.0,
    "usage_percent": 34.8
  },
  "alerts": {
    "active_total": 5,
    "critical": 1,
    "warning": 4
  }
}
```

---

## 10. Control Plane API

### 10.1 Common Rules

- All timestamps use ISO 8601 UTC format
- All authenticated endpoints require `Authorization: Bearer <token>`
- All write endpoints must emit audit logs
- Error response body should use a structured form

### 10.2 Common Error Shape

```json
{
  "code": "AUTH_401",
  "message": "Invalid access token",
  "recovery": "Login again and retry the request"
}
```

---

## 11. Authentication API

### 11.1 `POST /api/auth/login`

Login with employee ID and password.

Request:

```json
{
  "employee_id": "E1001",
  "password": "secret123"
}
```

Response `200`:

```json
{
  "access_token": "jwt-token",
  "refresh_token": "opaque-refresh-token",
  "token_type": "bearer",
  "expires_in_sec": 900,
  "user": {
    "employee_id": "E1001",
    "display_name": "Alice Chen",
    "role": "admin",
    "enabled": true
  }
}
```

Errors:

- `400` missing employee ID or password
- `401` invalid credentials
- `403` disabled account

### 11.2 `POST /api/auth/refresh`

Issue a new access token using refresh token.

Request:

```json
{
  "refresh_token": "opaque-refresh-token"
}
```

Response `200`:

```json
{
  "access_token": "new-jwt-token",
  "token_type": "bearer",
  "expires_in_sec": 900
}
```

### 11.3 `POST /api/auth/logout`

Revoke current session.

Request:

```json
{
  "refresh_token": "opaque-refresh-token"
}
```

Response `200`:

```json
{
  "success": true,
  "message": "Logged out"
}
```

### 11.4 `GET /api/auth/me`

Return current user summary.

Response `200`:

```json
{
  "employee_id": "E1001",
  "display_name": "Alice Chen",
  "role": "admin",
  "enabled": true,
  "site_ids": ["plant-a"],
  "server_ids": [],
  "machine_ids": []
}
```

### 11.5 `POST /api/auth/register`

Create a new user. Admin only.

Request:

```json
{
  "employee_id": "E2003",
  "display_name": "Bob Lin",
  "password": "secret123",
  "role": "operator",
  "site_ids": ["plant-a"]
}
```

Response `201`:

```json
{
  "success": true,
  "message": "User registered",
  "user": {
    "employee_id": "E2003",
    "display_name": "Bob Lin",
    "role": "operator",
    "enabled": true
  }
}
```

### 11.6 `POST /api/auth/change-password`

Change password for current user.

Request:

```json
{
  "current_password": "old-secret",
  "new_password": "new-secret"
}
```

Response `200`:

```json
{
  "success": true,
  "message": "Password updated"
}
```

### 11.7 `POST /api/auth/reset-password`

Reset password for another user. Admin only.

Request:

```json
{
  "employee_id": "E2003",
  "new_password": "temporary-secret"
}
```

Response `200`:

```json
{
  "success": true,
  "message": "Password reset"
}
```

### 11.8 `POST /api/auth/disable-user`

Disable a user. Admin only.

Request:

```json
{
  "employee_id": "E2003"
}
```

Response `200`:

```json
{
  "success": true,
  "message": "User disabled"
}
```

### 11.9 `POST /api/auth/enable-user`

Enable a user. Admin only.

### 11.10 `GET /.well-known/jwks.json`

Expose public keys for JWT validation by ingestion servers.

### 11.11 `POST /api/auth/introspect`

Optional simple-mode token validation endpoint for ingestion servers.

Request:

```json
{
  "token": "jwt-token"
}
```

Response `200`:

```json
{
  "active": true,
  "employee_id": "E1001",
  "role": "admin",
  "site_ids": ["plant-a"],
  "server_ids": [],
  "machine_ids": [],
  "exp": 1781778600
}
```

---

## 12. User Management API

### 12.1 `GET /api/users`

List users with filters.

Query parameters:

- `role`
- `enabled`
- `site`
- `q`

Response `200`:

```json
{
  "items": [
    {
      "employee_id": "E1001",
      "display_name": "Alice Chen",
      "role": "admin",
      "enabled": true,
      "last_login_at": "2026-06-18T10:02:11Z"
    }
  ],
  "total": 1
}
```

### 12.2 `GET /api/users/{employee_id}`

Return one user summary.

### 12.3 `PATCH /api/users/{employee_id}`

Update mutable fields.

Allowed updates:

- `display_name`
- `role`
- `enabled`
- `site_ids`
- `server_ids`
- `machine_ids`

---

## 13. Server Registry API

### 13.1 `GET /api/servers`

Return all registered servers.

Response `200`:

```json
{
  "items": [
    {
      "server_id": "srv-a",
      "name": "Ingestion Server A",
      "base_url": "https://srv-a.example.com",
      "site": "plant-a",
      "enabled": true,
      "status": "online",
      "machine_count": 15,
      "alert_count": 2,
      "last_seen_at": "2026-06-18T10:04:12Z",
      "last_error": null
    }
  ],
  "total": 1
}
```

### 13.2 `POST /api/servers`

Register a new ingestion server. Admin only.

Request:

```json
{
  "server_id": "srv-a",
  "name": "Ingestion Server A",
  "base_url": "https://srv-a.example.com",
  "site": "plant-a",
  "auth_mode": "shared_secret",
  "shared_secret": "server-secret",
  "poll_interval_sec": 3,
  "timeout_sec": 2,
  "labels": {
    "line": "line-1"
  }
}
```

Response `201`:

```json
{
  "success": true,
  "message": "Server registered"
}
```

### 13.3 `GET /api/servers/{server_id}`

Return one server summary and latest snapshot.

### 13.4 `PATCH /api/servers/{server_id}`

Update mutable server settings.

Allowed updates:

- `name`
- `base_url`
- `site`
- `enabled`
- `poll_interval_sec`
- `timeout_sec`
- `labels`

### 13.5 `POST /api/servers/{server_id}/disable`

Disable polling and mark server as administratively disabled.

### 13.6 `POST /api/servers/{server_id}/enable`

Enable polling.

### 13.7 `POST /api/servers/{server_id}/refresh`

Trigger immediate fetch of server metrics.

Response `202`:

```json
{
  "success": true,
  "message": "Refresh scheduled"
}
```

---

## 14. Fleet Dashboard API

### 14.1 `GET /api/fleet/overview`

Return fleet-wide top summary.

Response `200`:

```json
{
  "timestamp": "2026-06-18T10:04:12Z",
  "fleet_status": "warning",
  "server_counts": {
    "total": 3,
    "online": 2,
    "warning": 1,
    "degraded": 0,
    "offline": 0
  },
  "machine_counts": {
    "total": 42,
    "online": 38,
    "warning": 3,
    "offline": 1
  },
  "queue": {
    "total_queue_length": 128,
    "total_processing_rate": 850.4,
    "backlog_delta": 12
  },
  "storage": {
    "total_used_tb": 8.34,
    "total_capacity_tb": 24.0,
    "usage_percent": 34.8
  },
  "alerts": {
    "active_total": 5,
    "critical": 1,
    "warning": 4
  }
}
```

### 14.2 `GET /api/fleet/servers`

Return server list for grid cards.

Query parameters:

- `site`
- `status`
- `enabled`

### 14.3 `GET /api/fleet/servers/{server_id}`

Return detailed snapshot for one server.

Response fields should include:

- server summary
- current metrics
- queue state
- storage state
- worker state
- active alerts
- machines under this server

### 14.4 `GET /api/fleet/machines`

Return machine list across all servers.

Query parameters:

- `server_id`
- `site`
- `status`
- `q`

### 14.5 `GET /api/fleet/machines/{machine_id}`

Return one machine drill-down.

Response should include:

- machine summary
- owning server summary
- recent batches
- recent alerts
- queue depth

### 14.6 `GET /api/fleet/alerts`

Return active or historical alerts.

Query parameters:

- `status`
- `level`
- `server_id`
- `machine_id`
- `limit`

### 14.7 `GET /api/fleet/image-flow/recent`

Return recent batches across all servers.

Query parameters:

- `server_id`
- `machine_id`
- `limit`

### 14.8 `GET /api/fleet/trends`

Return time-series data for fleet charts.

Query parameters:

- `window` such as `5m`, `1h`, `24h`
- `server_id` optional filter

Response `200`:

```json
{
  "points": [
    {
      "timestamp": "2026-06-18T10:00:00Z",
      "cpu_percent": 62.1,
      "queue_length": 110,
      "disk_percent": 34.2
    }
  ]
}
```

---

## 15. Audit API

### 15.1 `GET /api/audit-logs`

Return audit history. Admin only.

Query parameters:

- `actor_employee_id`
- `action`
- `target_type`
- `target_id`
- `result`
- `limit`

Response `200`:

```json
{
  "items": [
    {
      "audit_id": "aud-001",
      "actor_employee_id": "E1001",
      "actor_role": "admin",
      "action": "user.reset_password",
      "target_type": "user",
      "target_id": "E2003",
      "result": "success",
      "details": {
        "reason": "operator-request"
      },
      "created_at": "2026-06-18T10:10:00Z"
    }
  ],
  "total": 1
}
```

---

## 16. WebSocket Live Update API

### 16.1 `WS /ws/fleet/live`

Push aggregated dashboard updates.

Authentication:

- Bearer token in query string for phase 1, or
- Cookie/session upgrade if browser-based auth is used

Message shape:

```json
{
  "type": "fleet_snapshot",
  "timestamp": "2026-06-18T10:04:12Z",
  "overview": {
    "fleet_status": "warning",
    "server_counts": {
      "total": 3,
      "online": 2,
      "warning": 1,
      "degraded": 0,
      "offline": 0
    }
  },
  "servers": [],
  "machines": [],
  "alerts": []
}
```

---

## 17. Ingestion Server Integration API

Each ingestion server should expose a control-plane-facing local API.

### 17.1 Authentication Options

- Shared secret header between control plane and ingestion server
- Mutual TLS in later phases

Recommended header:

- `X-Control-Server-ID`
- `X-Control-Signature` or `X-Control-Token`

### 17.2 `GET /api/local/server-info`

Return basic identity and version.

Response `200`:

```json
{
  "server_id": "srv-a",
  "name": "Ingestion Server A",
  "site": "plant-a",
  "version": "0.2.0",
  "timestamp": "2026-06-18T10:04:12Z"
}
```

### 17.3 `GET /api/local/snapshot`

Return one normalized local snapshot for control-plane aggregation.

Response `200`:

```json
{
  "timestamp": "2026-06-18T10:04:12Z",
  "machines": [],
  "server_metrics": {},
  "queue": {},
  "storage": {},
  "worker": {},
  "alerts": []
}
```

This endpoint can be backed by the existing local APIs if direct snapshot assembly is easier:

- `GET /api/machines`
- `GET /api/server/metrics`
- `GET /api/queue/status`
- `GET /api/storage/status`
- `GET /api/worker/status`
- `GET /api/alerts`

### 17.4 `GET /api/local/health`

Return local service availability and readiness for control plane polling.

### 17.5 `POST /api/local/auth/verify`

Optional simple-mode endpoint if ingestion server delegates token validation to control plane or maintains a compatibility path.

---

## 18. Aggregation Rules

### 18.1 Fleet Status

Suggested fleet status priority:

- `critical` if any critical alert exists
- `warning` if any server or machine is in warning and no critical alert exists
- `degraded` if any server is degraded and no warning or critical override applies
- `normal` otherwise

### 18.2 Server Status

Suggested server status logic:

- `offline` if no successful poll within 60 seconds
- `degraded` if server health responds but worker heartbeat is stale
- `warning` if queue or disk thresholds are exceeded
- `online` otherwise

### 18.3 Machine Uniqueness

The fleet model assumes a machine belongs to one active server at a time.

If the same `machine_id` appears on multiple servers simultaneously:

- mark as conflict in aggregation output
- raise a fleet alert
- preserve all raw server-side records for audit

---

## 19. Error Codes

Suggested control plane error code prefixes:

| Prefix | Area |
|--------|------|
| `AUTH_*` | Login, token, password, user status |
| `USER_*` | User management |
| `SRV_*` | Server registry |
| `FLEET_*` | Aggregation and fleet queries |
| `AUDIT_*` | Audit log access |

Examples:

- `AUTH_401` invalid token
- `AUTH_403` disabled user
- `USER_409` employee ID exists
- `SRV_404` server not found
- `FLEET_409` duplicate machine ownership conflict

---

## 20. Rollout Plan

### Phase 1

- Add control plane service
- Centralize users and login
- Add server registry
- Poll each existing ingestion server's current `/api/*` endpoints
- Build fleet overview APIs

### Phase 2

- Add JWT validation in ingestion servers
- Add machine client login against control plane
- Add audit log UI

### Phase 3

- Add WebSocket fleet live updates
- Add site and scope-based authorization
- Add HA and backup strategy for control plane

---

## 21. Open Decisions

The following items still need implementation-time decisions:

- Database choice: JSON file, SQLite, PostgreSQL
- Token format: JWT plus opaque refresh recommended
- Control plane polling interval by environment
- Whether machine clients may use a local emergency admin fallback
- Whether fleet history should be stored as time-series or short rolling snapshots

---

## 22. Recommendation

For this repository, the lowest-risk first implementation is:

1. Add a new `control_server/` service
2. Centralize user storage and login there
3. Reuse existing ingestion server monitoring APIs through polling
4. Introduce fleet APIs without changing upload contracts
5. Later migrate machine client login and ingestion server token validation to the control plane
