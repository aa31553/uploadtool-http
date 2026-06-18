# Machine Image System Dashboard UI/UX Design

## 1. Design Goals

### 1.1 Core Purpose

This UI is designed to:

- Monitor machine image upload status in real time
- Monitor server load, including CPU, RAM, disk IO, and network
- Observe queue congestion and processing pressure
- Locate abnormal machines or nodes quickly
- Help operators make immediate maintenance decisions

### 1.2 Design Principles

- Real-time first
- System health must be understandable in one screen
- Red-first design for abnormal conditions
- Low click cost with shallow navigation
- Industrial monitoring style similar to SCADA interfaces

---

## 2. Users and Roles

| Role | Need |
|------|------|
| Operations engineer | Health status and troubleshooting |
| Engineer | Throughput visibility and debugging |
| Manager | Capacity and long-term trend visibility |

---

## 3. UI Architecture

```text
Dashboard
 |- Machine Overview
 |- Server Metrics
 |- Queue Monitor
 |- Storage Status
 |- Image Flow Viewer
 `- Alert Center
```

---

## 4. Dashboard Home

### 4.1 Layout

```text
+--------------------------------------------+
| Top Status Bar (Global Health / Alerts)    |
+---------------+----------------------------+
| Machine Grid  | Server Metrics Panel       |
|               | CPU / RAM / Disk / Net     |
+---------------+----------------------------+
| Queue Status  | Storage Usage              |
+--------------------------------------------+
| Real-time Event Log / Alerts               |
+--------------------------------------------+
```

### 4.2 Design Intent

- The top status bar should always show overall health and active critical alerts
- Machine grid should support rapid scanning across all machines
- Metrics and queue panels must expose both current values and short trends
- Alert and event log should remain visible without navigation

---

## 5. Machine Overview

### 5.1 Machine Card Fields

Each machine should have one card containing:

- Machine ID
- Online or offline status
- FPS, meaning effective upload rate
- Upload latency
- Queue backlog
- Last upload timestamp
- Error count

### 5.2 Status Colors

| State | Color |
|-------|-------|
| Normal | Green |
| Warning | Yellow |
| Critical | Red |
| Offline | Gray |

### 5.3 Example Card

```text
+---------------+
| MC01       ONLINE |
| FPS: 10.2        |
| Latency: 120ms   |
| Queue: 32        |
| Last: 12:01:05   |
+---------------+
```

### 5.4 UX Rules

- Critical machines should sort to the front automatically
- Offline and high-latency machines should remain visually prominent
- No machine detail page should be required for the common 80 percent of troubleshooting cases

---

## 6. Server Metrics Panel

### 6.1 Metrics to Monitor

#### CPU

- Usage percentage
- Per-core load
- Load average for 1, 5, and 15 minutes

#### RAM

- Used versus total
- Cache usage
- Swap usage

#### Disk IO

- Read MB/s
- Write MB/s
- IOPS
- Disk queue length

#### Network

- Incoming Mbps
- Outgoing Mbps
- Packet drop rate

### 6.2 Visualization Style

- Line charts for real-time trends
- Gauges for instantaneous health
- Sparklines for compact recent history

### 6.3 UX Notes

- Disk IO and queue growth should be more visually dominant than CPU
- Use fixed scales where possible so spikes are easy to compare over time

---

## 7. Queue Monitor

### 7.1 Display Fields

- Total queue length
- Per-machine queue size
- Processing rate
- Worker utilization

### 7.2 Example Layout

```text
Queue Depth: ████████████ 1200
Processing:  980 img/s
Backlog:     +220 growing
```

### 7.3 Alert Conditions

| Condition | State |
|-----------|-------|
| Queue continuously rising | Warning |
| Worker throughput below ingest | Critical |
| Backlog above threshold | Alert |

---

## 8. Storage Monitor

### 8.1 Display Fields

- Total capacity
- Used capacity
- Growth rate in GB/day or TB/day
- Estimated time until full

### 8.2 Example Layout

```text
Storage Usage: 72%
Growth: +1.8TB/day
ETA Full: 3.2 days
```

### 8.3 UX Notes

- Capacity risk should be treated as a first-class alert signal
- Show both current pressure and projected exhaustion time

---

## 9. Image Flow Viewer

### 9.1 Purpose

This panel is intended for debugging and traceability:

- Review machine upload flow
- Preview recent batches
- Confirm compression success
- Detect missing images

### 9.2 UI Features

- Timeline slider
- Thumbnail grid
- Batch grouping

### 9.3 Usage Guidance

- Keep this as a drill-down tool, not the default landing surface
- Optimize for fast correlation between machine, batch, and storage result

---

## 10. Alert Center

### 10.1 Alert Types

- Machine offline
- Upload failure spike
- Queue overload
- Disk almost full
- Worker crash

### 10.2 Example Layout

```text
[CRITICAL] MC05 offline (2 min ago)
[WARNING] Queue backlog increasing
[INFO] MC02 latency improved
```

### 10.3 UX Rules

- Critical alerts must remain sticky until acknowledged or resolved
- Alert list should support severity, source, and time filters
- Recovery signals should be shown explicitly to prevent stale panic

---

## 11. Frontend Technical Architecture

### 11.1 Recommended Stack

| Layer | Technology |
|-------|------------|
| Framework | React or Vue 3 |
| UI library | Ant Design or Vuetify |
| Charts | ECharts or Recharts |
| Real-time transport | WebSocket |
| State | Zustand or Pinia |

### 11.2 Real-Time Update Architecture

```text
Backend Metrics Collector
        |
        v
   WebSocket Server
        |
        v
   Frontend Dashboard
```

### 11.3 Update Frequency

| Module | Frequency |
|--------|-----------|
| CPU / RAM | 1s |
| Queue | 1s |
| Machine status | 1s |
| Storage | 5s |
| Logs | Real-time |

---

## 12. Backend API Plan for Frontend

### 12.1 Machine API

```http
GET /api/machines
```

Example response:

```json
[
  {
    "machine_id": "MC01",
    "status": "online",
    "fps": 10.2,
    "latency_ms": 120,
    "queue_size": 32,
    "last_upload": "2026-06-18T12:01:05"
  }
]
```

### 12.2 Server Metrics API

```http
GET /api/server/metrics
```

### 12.3 Queue API

```http
GET /api/queue/status
```

### 12.4 Storage API

```http
GET /api/storage/status
```

### 12.5 WebSocket Endpoint

```http
/ws/live
```

Pushed events should include:

- Machine updates
- CPU and RAM updates
- Queue changes
- Alerts

---

## 13. Key UX Decisions

### 13.1 One-Glance System Health

The homepage must answer this question without requiring any click:

> Is the system close to failure right now?

### 13.2 Red-First Design

Prioritize visibility for:

- Queue backlog
- Disk usage
- Offline machines

### 13.3 Minimal Click Principle

- Dashboard should cover 80 percent of operational visibility in one page
- Drill-down should exist only for debugging and forensics

---

## 14. Text Mockup

```text
+--------------------------------------------+
| SYSTEM HEALTH: WARNING                     |
| Queue: +220 growing                        |
+--------------------------------------------+
| MC01 OK  MC02 OK  MC03 WARN  MC04 CRIT     |
| MC05 OFFLINE                               |
+--------------------------------------------+
| CPU 72%   RAM 61%   Disk 88%   Net 320MB/s |
+--------------------------------------------+
| Queue Depth: 1200                          |
+--------------------------------------------+
| Alerts:                                    |
| [CRITICAL] MC05 offline                    |
| [WARNING] Queue increasing                 |
+--------------------------------------------+
```

---

## 15. Suggested Next-Phase Enhancements

### 15.1 Prometheus and Grafana

- Native CPU, RAM, disk, and network monitoring
- Long-term metrics retention and historical visualization

### 15.2 OpenTelemetry

- Trace upload latency across pipeline stages
- Profile the worker processing path

### 15.3 AI-Based Anomaly Detection

- Queue abnormality detection
- Disk growth prediction

---

## 16. Dashboard Scope Boundary

The dashboard should focus on operational monitoring and troubleshooting.
It should not become a general admin portal in the first phase.

Phase 1 priority:

- Real-time visibility
- Alerting
- Fast root-cause clues

Phase 2 priority:

- Trend analysis
- Forensic drill-down
- Predictive operations
