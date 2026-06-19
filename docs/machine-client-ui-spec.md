# Machine Client UI/UX Specification

## 1. System Positioning

The machine-side UI is a lightweight edge agent interface for local operation and monitoring.

### 1.1 Main Functions

- Configure the image upload server
- Configure the local image storage path
- Monitor upload status, including FPS, latency, and queue depth
- Review errors and retry status
- Ensure buffered data is not lost

### 1.2 Design Principles

- Must not affect machine operation, with low CPU and low IO impact
- Configuration should be completed within three clicks where possible
- Fail-safe defaults should be used
- The client must remain usable in offline mode

---

## 2. UI Architecture

```text
Machine Client UI
|- Account
|- Dashboard
|- Upload Settings
|- Storage Settings
|- Network Settings
|- Queue Monitor
`- Logs
```

---

## 3. Dashboard

### 3.1 Display Fields

- Machine ID
- Online status
- FPS, meaning image generation rate
- Upload success rate
- Upload latency
- Local buffer usage

### 3.2 Example UI

```text
+------------------------------+
| MACHINE ID: MC01             |
| STATUS: ONLINE               |
+------------------------------+
| FPS: 10.3                    |
| Upload: 98.7% success        |
| Latency: 120ms               |
| Buffer: 320 / 1000 images    |
+------------------------------+
```

### 3.3 UX Notes

- The dashboard should expose current health without opening any settings page
- Offline mode and near-full buffer states must remain visually prominent

---

## 4. Upload Settings

### 4.1 Purpose

Configure image upload behavior:

- Batch size
- Batch interval
- Retry count
- Compression mode

### 4.2 Fields

| Field | Description | Default |
|-------|-------------|---------|
| Batch Size | Number of images per upload batch | 20 |
| Interval (sec) | Upload frequency in seconds | 1 |
| Retry Count | Maximum retry attempts | 5 |
| Compression | `jpeg`, `webp`, or `none` | `webp` |

### 4.3 Example UI

```text
Batch Size:      [ 20 ]
Interval(sec):   [ 1  ]
Retry Count:     [ 5  ]
Compression:     [ WebP ]

[ Save Settings ]
```

---

## 5. Network Settings

### 5.1 Purpose

Configure the server endpoints used for image upload.

### 5.2 Fields

| Field | Description |
|-------|-------------|
| Server URL | Primary upload API endpoint |
| Backup Server | Secondary upload endpoint |
| Control Server | Centralized auth and control plane endpoint |
| API Token | Authentication token |
| Timeout | Request timeout in seconds |

### 5.3 Example UI

```text
Server URL:
[ http://10.0.0.5:8000/upload ]

Backup Server:
[ http://10.0.0.6:8000/upload ]

Control Server:
[ http://10.0.0.10:8100 ]

API Token:
[ *************** ]

Timeout (sec):
[ 5 ]

[ Test Connection ]
[ Save ]
```

### 5.4 Test Mechanism

The `Test Connection` action should:

- Ping the server
- Upload one test image
- Return measured latency
- Validate the API token

---

## 5A. Account

### 5A.1 Purpose

Protect settings from general operators and route user authentication through the centralized control plane.

### 5A.2 Functions

- Login with employee ID and password
- Logout
- Change current password
- Admin-only user registration
- Admin-only password reset

### 5A.3 UX Rules

- Upload, network, and storage settings remain locked until login succeeds
- Admin-only actions are visible or enabled only for admin users

---

## 6. Storage Settings

### 6.1 Purpose

Configure where machine-side images and buffers are stored.

### 6.2 Fields

| Field | Description |
|-------|-------------|
| Image Root Path | Path for source images |
| Temp Buffer Path | Path for upload queue buffer |
| Max Disk Usage | Maximum allowed disk usage |
| Auto Cleanup | Whether old files are cleaned automatically |
| Retention Days | Retention period for cleanup |

### 6.3 Example UI

```text
Image Root Path:
[ D:\MachineData\Images ]

Temp Buffer Path:
[ D:\MachineData\Buffer ]

Max Disk Usage:
[ 80 % ]

Auto Cleanup:
[ Enabled ]

Retention Days:
[ 7 ]

[ Browse Folder ]
[ Save ]
```

### 6.4 Buffer Management Rules

- If usage exceeds the configured max usage, show a stop-ingest warning
- If usage exceeds 90 percent, raise a critical alert
- Optional automatic deletion of oldest files may be enabled

---

## 7. Queue Monitor

### 7.1 Purpose

Display:

- Number of pending images
- Queue growth speed
- Backlog pressure

### 7.2 Example UI

```text
Buffer Queue:
██████████████ 320 images

Upload Rate: 10 img/sec
Queue Growth: +2.3/sec
Status: STABLE
```

---

## 8. Logs

### 8.1 Displayed Events

- Upload success
- Upload failure
- Retry events
- Disk full warnings
- Server timeout

### 8.2 Example UI

```text
[INFO] Upload success batch_12001
[WARN] Retry attempt 2/5
[ERROR] Server timeout 10.0.0.5
[INFO] Switched to backup server
```

---

## 9. Configuration Safety Rules

### 9.1 Validation Rules

- Server URL must be reachable
- Token must validate successfully before save
- Storage path must exist
- Disk usage limit must not exceed 95 percent

### 9.2 Offline Mode

When the server is unavailable:

- Image capture must continue
- All data must be written into the local buffer
- UI must clearly show `OFFLINE MODE`

---

## 10. User Flow

### 10.1 First-Time Setup

```text
Open UI
  |
  v
Set Storage Path
  |
  v
Set Server URL and Token
  |
  v
Test Connection
  |
  v
Save
  |
  v
Start Upload Service
```

---

## 11. UX Priorities

### 11.1 Three Core Rules

#### 1. UI must not affect machine operation

If the UI crashes, image capture and buffering must continue.

#### 2. System should work by default

The agent should start automatically on boot.

#### 3. Recovery must be fast

If the server fails, the client should retry automatically and switch to backup when configured.

### 11.2 Red-First UX

Prioritize visibility for:

- Server disconnect
- Buffer full
- Disk full

---

## 12. Implementation Recommendations

### 12.1 UI Technology

| Type | Recommendation |
|------|----------------|
| Desktop UI | PyQt5 or PySide6 |
| Web UI | Electron or local web server |
| Hybrid | Flask plus WebView |

Recommended for factory environments: `PyQt5` because of stability and offline support.

### 12.2 Internal Architecture

```text
UI (PyQt5)
   |
   v
Agent Core (async uploader)
   |
   v
Local Queue (disk-based)
   |
   v
HTTP Client
```

---

## 13. Suggested Configuration Format

```json
{
  "machine_id": "MC01",
  "server": {
    "primary": "http://10.0.0.5:8000/upload",
    "backup": "http://10.0.0.6:8000/upload",
    "token": "xxxxx"
  },
  "storage": {
    "image_root": "D:/MachineData/Images",
    "buffer_path": "D:/MachineData/Buffer",
    "max_usage_percent": 80,
    "auto_cleanup": true,
    "retention_days": 7
  },
  "upload": {
    "batch_size": 20,
    "interval_sec": 1,
    "retry": 5,
    "compression": "webp"
  }
}
```
