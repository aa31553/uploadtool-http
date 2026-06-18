import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { connectDashboardStream, fetchDashboardSnapshot, fetchMachineDetail, fetchRecentImageFlow } from './api'

const statusMeta = {
  online: { label: 'ONLINE', tone: 'ok' },
  warning: { label: 'WARNING', tone: 'warn' },
  offline: { label: 'OFFLINE', tone: 'off' },
  critical: { label: 'CRITICAL', tone: 'crit' },
  idle: { label: 'IDLE', tone: 'off' },
  processing: { label: 'PROCESSING', tone: 'ok' },
  error: { label: 'ERROR', tone: 'crit' },
  unknown: { label: 'UNKNOWN', tone: 'off' },
}

const emptySnapshot = {
  timestamp: null,
  machines: [],
  server_metrics: null,
  queue: null,
  storage: null,
  alerts: [],
  worker: null,
}

function App() {
  const [snapshot, setSnapshot] = useState(emptySnapshot)
  const [history, setHistory] = useState([])
  const [selectedMachineId, setSelectedMachineId] = useState('')
  const [machineDetail, setMachineDetail] = useState(null)
  const [imageFlow, setImageFlow] = useState([])
  const [streamState, setStreamState] = useState('connecting')
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    let isMounted = true
    let socket

    async function bootstrap() {
      try {
        const initial = await fetchDashboardSnapshot()
        if (isMounted) {
          setSnapshot(initial)
          setHistory((current) => appendHistory(current, initial))
          setSelectedMachineId((current) => current || initial.machines[0]?.machine_id || '')
          setErrorMessage('')
        }
      } catch (error) {
        if (isMounted) {
          setErrorMessage(error.message)
        }
      }

      socket = connectDashboardStream({
        onSnapshot: (next) => {
          if (!isMounted) {
            return
          }
          setSnapshot(next)
          setHistory((current) => appendHistory(current, next))
          setSelectedMachineId((current) => current || next.machines[0]?.machine_id || '')
          setStreamState('live')
          setErrorMessage('')
        },
        onError: () => {
          if (!isMounted) {
            return
          }
          setStreamState('degraded')
          setErrorMessage('WebSocket stream unavailable. Showing latest HTTP snapshot.')
        },
      })

      socket.onopen = () => {
        if (isMounted) {
          setStreamState('live')
        }
      }

      socket.onclose = () => {
        if (isMounted) {
          setStreamState('degraded')
        }
      }
    }

    bootstrap()

    return () => {
      isMounted = false
      socket?.close()
    }
  }, [])

  useEffect(() => {
    if (!selectedMachineId) {
      return undefined
    }

    let isMounted = true

    async function loadDrillDown() {
      try {
        const [detail, flow] = await Promise.all([
          fetchMachineDetail(selectedMachineId),
          fetchRecentImageFlow(selectedMachineId),
        ])
        if (!isMounted) {
          return
        }
        setMachineDetail(detail)
        setImageFlow(flow)
      } catch (error) {
        if (isMounted) {
          setErrorMessage(error.message)
        }
      }
    }

    loadDrillDown()
    return () => {
      isMounted = false
    }
  }, [selectedMachineId, snapshot.timestamp])

  const systemHealth = useMemo(() => {
    if (snapshot.alerts.some((alert) => alert.level === 'critical')) {
      return { label: 'CRITICAL', tone: 'crit' }
    }
    if (snapshot.alerts.some((alert) => alert.level === 'warning')) {
      return { label: 'WARNING', tone: 'warn' }
    }
    return { label: 'NORMAL', tone: 'ok' }
  }, [snapshot.alerts])

  const sortedMachines = useMemo(() => {
    const rank = { critical: 0, offline: 1, warning: 2, online: 3 }
    return [...snapshot.machines].sort((a, b) => {
      const rankDiff = (rank[a.status] ?? 9) - (rank[b.status] ?? 9)
      if (rankDiff !== 0) {
        return rankDiff
      }
      return a.machine_id.localeCompare(b.machine_id)
    })
  }, [snapshot.machines])

  const trendData = useMemo(
    () =>
      history.map((item) => ({
        time: formatTimestamp(item.timestamp),
        cpu: item.server_metrics?.cpu_percent ?? 0,
        queue: item.queue?.queue_length ?? 0,
        disk: item.storage?.usage_percent ?? 0,
      })),
    [history],
  )

  return (
    <div className="app-shell">
      <header className={`topbar tone-${systemHealth.tone}`}>
        <div>
          <div className="eyebrow">Machine Image Uploader System</div>
          <h1>Operations Dashboard</h1>
        </div>
        <div className="topbar-meta">
          <StatusPill label={`SYSTEM ${systemHealth.label}`} tone={systemHealth.tone} />
          <StatusPill label={`STREAM ${streamState.toUpperCase()}`} tone={streamState === 'live' ? 'ok' : 'warn'} />
        </div>
      </header>

      <section className="banner-row">
        <div className="banner-card">
          <span className="banner-label">Active Alerts</span>
          <span className="banner-value">{snapshot.alerts.length}</span>
        </div>
        <div className="banner-card">
          <span className="banner-label">Queue Depth</span>
          <span className="banner-value">{snapshot.queue?.queue_length ?? '--'}</span>
        </div>
        <div className="banner-card">
          <span className="banner-label">Disk Usage</span>
          <span className="banner-value">{formatPercent(snapshot.storage?.usage_percent)}</span>
        </div>
        <div className="banner-card">
          <span className="banner-label">Worker</span>
          <span className="banner-value">{snapshot.worker?.status?.toUpperCase() ?? '--'}</span>
        </div>
      </section>

      {errorMessage ? <div className="error-strip">{errorMessage}</div> : null}

      <main className="dashboard-grid">
        <section className="panel machine-panel">
          <PanelHeader title="Machine Overview" subtitle="Prioritized by abnormal state" />
          <div className="machine-grid">
            {sortedMachines.map((machine) => (
              <MachineCard
                key={machine.machine_id}
                machine={machine}
                active={machine.machine_id === selectedMachineId}
                onSelect={() => setSelectedMachineId(machine.machine_id)}
              />
            ))}
          </div>
        </section>

        <section className="panel metrics-panel">
          <PanelHeader title="Server Metrics" subtitle="Runtime-derived system load" />
          <div className="metric-grid">
            <MetricTile label="CPU" value={formatPercent(snapshot.server_metrics?.cpu_percent)} detail={`Load ${snapshot.server_metrics?.load_avg_1 ?? '--'} / ${snapshot.server_metrics?.load_avg_5 ?? '--'} / ${snapshot.server_metrics?.load_avg_15 ?? '--'}`} tone={valueTone(snapshot.server_metrics?.cpu_percent, 75, 90)} />
            <MetricTile label="RAM" value={formatPercent(snapshot.server_metrics?.ram_percent)} detail="Memory pressure" tone={valueTone(snapshot.server_metrics?.ram_percent, 75, 90)} />
            <MetricTile label="Disk" value={formatPercent(snapshot.server_metrics?.disk_percent)} detail={`Write ${formatRate(snapshot.server_metrics?.disk_write_mbps)}`} tone={valueTone(snapshot.server_metrics?.disk_percent, 80, 90)} />
            <MetricTile label="Ingress" value={formatRate(snapshot.server_metrics?.net_in_mbps)} detail={`Egress ${formatRate(snapshot.server_metrics?.net_out_mbps)}`} tone="ok" />
          </div>
        </section>

        <section className="panel trends-panel">
          <PanelHeader title="Trend Lines" subtitle="CPU, queue, and storage over live snapshots" />
          <div className="chart-shell">
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={trendData}>
                <CartesianGrid stroke="#19313f" strokeDasharray="3 3" />
                <XAxis dataKey="time" stroke="#89a2b1" minTickGap={24} />
                <YAxis stroke="#89a2b1" />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="cpu" stroke="#31d4a4" dot={false} strokeWidth={2} name="CPU %" />
                <Line type="monotone" dataKey="queue" stroke="#efbb49" dot={false} strokeWidth={2} name="Queue Depth" />
                <Line type="monotone" dataKey="disk" stroke="#ff6b6b" dot={false} strokeWidth={2} name="Disk %" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="panel queue-panel">
          <PanelHeader title="Queue Monitor" subtitle="Backpressure and worker activity" />
          <div className="queue-hero">
            <div>
              <div className="hero-label">Queue Depth</div>
              <div className="hero-value">{snapshot.queue?.queue_length ?? '--'}</div>
            </div>
            <div className="queue-bar-track">
              <div className="queue-bar-fill" style={{ width: `${Math.min(((snapshot.queue?.queue_length ?? 0) / 20) * 100, 100)}%` }} />
            </div>
          </div>
          <div className="queue-stats">
            <MetricLine label="Processing Rate" value={`${snapshot.queue?.processing_rate?.toFixed?.(1) ?? '--'} img/s`} />
            <MetricLine label="Backlog Delta" value={signed(snapshot.queue?.backlog_delta)} />
            <MetricLine label="Worker Utilization" value={formatPercent(snapshot.queue?.worker_utilization)} />
          </div>
          <div className="per-machine-list">
            {Object.entries(snapshot.queue?.per_machine ?? {}).map(([machineId, depth]) => (
              <div className="per-machine-item" key={machineId}>
                <span>{machineId}</span>
                <span>{depth}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="panel storage-panel">
          <PanelHeader title="Storage Status" subtitle="Raw, processed, and failed zones" />
          <div className="storage-main">
            <MetricTile label="Total Used" value={`${snapshot.storage?.used_tb?.toFixed?.(2) ?? '--'} TB`} detail={`of ${snapshot.storage?.total_tb?.toFixed?.(2) ?? '--'} TB`} tone={valueTone(snapshot.storage?.usage_percent, 80, 90)} />
            <MetricTile label="Growth" value={`${snapshot.storage?.growth_tb_per_day?.toFixed?.(4) ?? '--'} TB/day`} detail={`ETA ${snapshot.storage?.eta_full_days?.toFixed?.(1) ?? '--'} days`} tone={valueTone(snapshot.storage?.usage_percent, 80, 90)} />
          </div>
          <div className="storage-breakdown">
            <MetricLine label="Raw" value={`${snapshot.storage?.raw_used_gb?.toFixed?.(2) ?? '--'} GB`} />
            <MetricLine label="Processed" value={`${snapshot.storage?.processed_used_gb?.toFixed?.(2) ?? '--'} GB`} />
            <MetricLine label="Failed" value={`${snapshot.storage?.failed_used_gb?.toFixed?.(2) ?? '--'} GB`} />
          </div>
        </section>

        <section className="panel worker-panel">
          <PanelHeader title="Worker State" subtitle="Queue consumer heartbeat" />
          <div className="worker-grid">
            <StatusPill label={snapshot.worker?.status?.toUpperCase() ?? 'UNKNOWN'} tone={statusMeta[snapshot.worker?.status]?.tone ?? 'off'} />
            <MetricLine label="Current Job" value={snapshot.worker?.current_job_id ?? '--'} />
            <MetricLine label="Processed Jobs" value={String(snapshot.worker?.processed_jobs ?? '--')} />
            <MetricLine label="Failed Jobs" value={String(snapshot.worker?.failed_jobs ?? '--')} />
            <MetricLine label="Heartbeat" value={formatTimestamp(snapshot.worker?.heartbeat_at)} />
          </div>
        </section>

        <section className="panel alerts-panel">
          <PanelHeader title="Alert Center" subtitle="Red-first operational visibility" />
          <div className="alerts-list">
            {snapshot.alerts.length === 0 ? <div className="alert-row info">No active alerts</div> : null}
            {snapshot.alerts.map((alert, index) => (
              <div className={`alert-row ${alert.level}`} key={`${alert.source}-${index}`}>
                <span className="alert-level">{alert.level.toUpperCase()}</span>
                <span className="alert-message">{alert.message}</span>
                <span className="alert-source">{alert.source}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="panel detail-panel">
          <PanelHeader title="Machine Detail" subtitle={selectedMachineId ? `Drill-down for ${selectedMachineId}` : 'Select a machine'} />
          {machineDetail ? <MachineDetailPanel detail={machineDetail} /> : <EmptyState text="No machine selected" />}
        </section>

        <section className="panel flow-panel">
          <PanelHeader title="Image Flow Viewer" subtitle="Recent batch lifecycle by machine" />
          {imageFlow.length > 0 ? <ImageFlowList items={imageFlow} /> : <EmptyState text="No recent batch data" />}
        </section>
      </main>
    </div>
  )
}

function PanelHeader({ title, subtitle }) {
  return (
    <div className="panel-header">
      <h2>{title}</h2>
      <span>{subtitle}</span>
    </div>
  )
}

function MachineCard({ machine, active, onSelect }) {
  const meta = statusMeta[machine.status] ?? statusMeta.unknown
  return (
    <button type="button" className={`machine-card tone-${meta.tone} ${active ? 'active' : ''}`} onClick={onSelect}>
      <div className="machine-card-header">
        <strong>{machine.machine_id}</strong>
        <StatusPill label={meta.label} tone={meta.tone} />
      </div>
      <div className="machine-card-grid">
        <MetricLine label="FPS" value={machine.fps?.toFixed?.(1) ?? '--'} compact />
        <MetricLine label="Latency" value={`${machine.latency_ms ?? '--'} ms`} compact />
        <MetricLine label="Queue" value={String(machine.queue_size ?? '--')} compact />
        <MetricLine label="Last Upload" value={formatTimestamp(machine.last_upload)} compact />
      </div>
    </button>
  )
}

function MachineDetailPanel({ detail }) {
  return (
    <div className="detail-grid">
      <MetricLine label="Status" value={detail.machine.status.toUpperCase()} />
      <MetricLine label="Latency" value={`${detail.machine.latency_ms} ms`} />
      <MetricLine label="FPS" value={detail.machine.fps.toFixed(1)} />
      <MetricLine label="Queue Depth" value={String(detail.queue_depth)} />
      <MetricLine label="Last Upload" value={formatTimestamp(detail.machine.last_upload)} />
      <MetricLine label="Recent Batches" value={String(detail.recent_upload_count)} />
      <div className="subpanel">
        <div className="subpanel-title">Recent Batches</div>
        {detail.recent_batches.map((batch) => (
          <div className="batch-row" key={batch.job_id}>
            <span>{batch.job_id}</span>
            <span>{batch.status}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ImageFlowList({ items }) {
  return (
    <div className="flow-list">
      {items.map((item) => (
        <div className={`flow-row tone-${statusMeta[item.status]?.tone ?? 'off'}`} key={item.job_id}>
          <div>
            <strong>{item.machine_id}</strong>
            <div className="flow-meta">{item.batch_filename ?? item.job_id}</div>
          </div>
          <div>
            <div>{item.status.toUpperCase()}</div>
            <div className="flow-meta">{item.image_count} image(s)</div>
          </div>
          <div>
            <div>{formatTimestamp(item.received_at)}</div>
            <div className="flow-meta">{item.last_error ?? item.processed_root ?? 'awaiting worker'}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

function EmptyState({ text }) {
  return <div className="empty-state">{text}</div>
}

function MetricTile({ label, value, detail, tone }) {
  return (
    <div className={`metric-tile tone-${tone}`}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
      <span className="metric-detail">{detail}</span>
    </div>
  )
}

function MetricLine({ label, value, compact = false }) {
  return (
    <div className={`metric-line ${compact ? 'compact' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function StatusPill({ label, tone }) {
  return <span className={`status-pill tone-${tone}`}>{label}</span>
}

function valueTone(value, warn, crit) {
  if (typeof value !== 'number') {
    return 'off'
  }
  if (value >= crit) {
    return 'crit'
  }
  if (value >= warn) {
    return 'warn'
  }
  return 'ok'
}

function formatPercent(value) {
  return typeof value === 'number' ? `${value.toFixed(1)}%` : '--'
}

function formatRate(value) {
  return typeof value === 'number' ? `${value.toFixed(2)} MB/s` : '--'
}

function formatTimestamp(value) {
  if (!value) {
    return '--'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '--'
  }
  return date.toLocaleTimeString()
}

function signed(value) {
  return typeof value === 'number' ? `${value >= 0 ? '+' : ''}${value}` : '--'
}

function appendHistory(current, snapshot) {
  const next = [
    ...current,
    {
      timestamp: snapshot.timestamp,
      server_metrics: snapshot.server_metrics,
      queue: snapshot.queue,
      storage: snapshot.storage,
    },
  ]
  return next.slice(-30)
}

export default App
