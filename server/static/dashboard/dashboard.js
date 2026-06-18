(function () {
  const apiBase = window.location.origin

  const statusMeta = {
    online: { label: 'ONLINE', tone: 'ok' },
    warning: { label: 'WARNING', tone: 'warn' },
    offline: { label: 'OFFLINE', tone: 'off' },
    critical: { label: 'CRITICAL', tone: 'crit' },
    idle: { label: 'IDLE', tone: 'off' },
    processing: { label: 'PROCESSING', tone: 'ok' },
    error: { label: 'ERROR', tone: 'crit' },
    unknown: { label: 'UNKNOWN', tone: 'off' },
    completed: { label: 'COMPLETED', tone: 'ok' },
    failed: { label: 'FAILED', tone: 'crit' },
    pending: { label: 'PENDING', tone: 'warn' },
  }

  const state = {
    snapshot: {
      timestamp: null,
      machines: [],
      server_metrics: null,
      queue: null,
      storage: null,
      alerts: [],
      worker: null,
    },
    history: [],
    selectedMachineId: '',
    machineDetail: null,
    imageFlow: [],
    streamState: 'polling',
    errorMessage: '',
    pollTimer: null,
  }

  function getJson(path) {
    return fetch(`${apiBase}${path}`).then((response) => {
      if (!response.ok) {
        throw new Error(`Request failed: ${path} (${response.status})`)
      }
      return response.json()
    })
  }

  function fetchSnapshot() {
    return Promise.all([
      getJson('/api/machines'),
      getJson('/api/server/metrics'),
      getJson('/api/queue/status'),
      getJson('/api/storage/status'),
      getJson('/api/alerts'),
      getJson('/api/worker/status'),
    ]).then(([machines, serverMetrics, queue, storage, alerts, worker]) => ({
      timestamp: new Date().toISOString(),
      machines,
      server_metrics: serverMetrics,
      queue,
      storage,
      alerts,
      worker,
    }))
  }

  function fetchMachineDetail(machineId) {
    return getJson(`/api/machines/${encodeURIComponent(machineId)}`)
  }

  function fetchRecentImageFlow(machineId) {
    const query = machineId ? `?machine_id=${encodeURIComponent(machineId)}&limit=12` : '?limit=12'
    return getJson(`/api/image-flow/recent${query}`)
  }

  function startPolling() {
    if (state.pollTimer !== null) {
      return
    }
    state.pollTimer = window.setInterval(() => {
      fetchSnapshot()
        .then((snapshot) => {
          applySnapshot(snapshot)
          render()
        })
        .catch((error) => {
          state.errorMessage = error.message
          render()
        })
    }, 3000)
  }

  function stopPolling() {
    if (state.pollTimer === null) {
      return
    }
    window.clearInterval(state.pollTimer)
    state.pollTimer = null
  }

  function applySnapshot(snapshot) {
    state.snapshot = snapshot
    state.history = appendHistory(state.history, snapshot)
    if (!state.selectedMachineId) {
      state.selectedMachineId = snapshot.machines[0]?.machine_id || ''
    }
    if (state.selectedMachineId) {
      loadDrillDown(state.selectedMachineId)
    }
  }

  function loadDrillDown(machineId) {
    Promise.all([fetchMachineDetail(machineId), fetchRecentImageFlow(machineId)])
      .then(([detail, flow]) => {
        state.machineDetail = detail
        state.imageFlow = flow
        render()
      })
      .catch((error) => {
        state.errorMessage = error.message
        render()
      })
  }

  function bootstrap() {
    fetchSnapshot()
      .then((snapshot) => {
        applySnapshot(snapshot)
        render()
      })
      .catch((error) => {
        state.errorMessage = error.message
        render()
      })
    startPolling()
  }

  function render() {
    document.getElementById('app').innerHTML = buildMarkup()
    bindEvents()
    renderTrendChart()
  }

  function buildMarkup() {
    const systemHealth = getSystemHealth(state.snapshot.alerts)
    const machines = [...state.snapshot.machines].sort(compareMachines)
    return `
      <div class="app-shell">
        <header class="topbar tone-${systemHealth.tone}">
          <div>
            <div class="eyebrow">Machine Image Uploader System</div>
            <h1>Operations Dashboard</h1>
          </div>
          <div class="topbar-meta">
            ${statusPill(`SYSTEM ${systemHealth.label}`, systemHealth.tone)}
            ${statusPill(`STREAM ${state.streamState.toUpperCase()}`, state.streamState === 'live' ? 'ok' : 'warn')}
          </div>
        </header>

        <section class="banner-row">
          ${bannerCard('Active Alerts', String(state.snapshot.alerts.length))}
          ${bannerCard('Queue Depth', String(state.snapshot.queue?.queue_length ?? '--'))}
          ${bannerCard('Disk Usage', formatPercent(state.snapshot.storage?.usage_percent))}
          ${bannerCard('Worker', state.snapshot.worker?.status?.toUpperCase() ?? '--')}
        </section>

        ${state.errorMessage ? `<div class="error-strip">${escapeHtml(state.errorMessage)}</div>` : ''}

        <main class="dashboard-grid">
          <section class="panel machine-panel">
            ${panelHeader('Machine Overview', 'Prioritized by abnormal state')}
            <div class="machine-grid">
              ${machines.map((machine) => machineCard(machine)).join('')}
            </div>
          </section>

          <section class="panel metrics-panel">
            ${panelHeader('Server Metrics', 'Runtime-derived system load')}
            <div class="metric-grid">
              ${metricTile('CPU', formatPercent(state.snapshot.server_metrics?.cpu_percent), `Load ${state.snapshot.server_metrics?.load_avg_1 ?? '--'} / ${state.snapshot.server_metrics?.load_avg_5 ?? '--'} / ${state.snapshot.server_metrics?.load_avg_15 ?? '--'}`, valueTone(state.snapshot.server_metrics?.cpu_percent, 75, 90))}
              ${metricTile('RAM', formatPercent(state.snapshot.server_metrics?.ram_percent), 'Memory pressure', valueTone(state.snapshot.server_metrics?.ram_percent, 75, 90))}
              ${metricTile('Disk', formatPercent(state.snapshot.server_metrics?.disk_percent), `Write ${formatRate(state.snapshot.server_metrics?.disk_write_mbps)}`, valueTone(state.snapshot.server_metrics?.disk_percent, 80, 90))}
              ${metricTile('Ingress', formatRate(state.snapshot.server_metrics?.net_in_mbps), `Egress ${formatRate(state.snapshot.server_metrics?.net_out_mbps)}`, 'ok')}
            </div>
          </section>

          <section class="panel trends-panel">
            ${panelHeader('Trend Lines', 'CPU, queue, and storage over live snapshots')}
            <div class="chart-shell">
              <svg class="spark-chart" viewBox="0 0 800 220" preserveAspectRatio="none"></svg>
              <div class="chart-legend">
                <span><i class="legend-dot legend-cpu"></i>CPU %</span>
                <span><i class="legend-dot legend-queue"></i>Queue Depth</span>
                <span><i class="legend-dot legend-disk"></i>Disk %</span>
              </div>
            </div>
          </section>

          <section class="panel queue-panel">
            ${panelHeader('Queue Monitor', 'Backpressure and worker activity')}
            <div class="queue-hero">
              <div>
                <div class="hero-label">Queue Depth</div>
                <div class="hero-value">${state.snapshot.queue?.queue_length ?? '--'}</div>
              </div>
              <div class="queue-bar-track"><div class="queue-bar-fill" style="width: ${Math.min(((state.snapshot.queue?.queue_length ?? 0) / 20) * 100, 100)}%"></div></div>
            </div>
            <div class="queue-stats">
              ${metricLine('Processing Rate', `${toFixed(state.snapshot.queue?.processing_rate, 1)} img/s`)}
              ${metricLine('Backlog Delta', signed(state.snapshot.queue?.backlog_delta))}
              ${metricLine('Worker Utilization', formatPercent(state.snapshot.queue?.worker_utilization))}
            </div>
            <div class="per-machine-list">
              ${Object.entries(state.snapshot.queue?.per_machine ?? {}).map(([machineId, depth]) => `<div class="per-machine-item"><span>${machineId}</span><span>${depth}</span></div>`).join('')}
            </div>
          </section>

          <section class="panel storage-panel">
            ${panelHeader('Storage Status', 'Raw, processed, and failed zones')}
            <div class="metric-grid">
              ${metricTile('Total Used', `${toFixed(state.snapshot.storage?.used_tb, 2)} TB`, `of ${toFixed(state.snapshot.storage?.total_tb, 2)} TB`, valueTone(state.snapshot.storage?.usage_percent, 80, 90))}
              ${metricTile('Growth', `${toFixed(state.snapshot.storage?.growth_tb_per_day, 4)} TB/day`, `ETA ${toFixed(state.snapshot.storage?.eta_full_days, 1)} days`, valueTone(state.snapshot.storage?.usage_percent, 80, 90))}
            </div>
            <div class="storage-breakdown">
              ${metricLine('Raw', `${toFixed(state.snapshot.storage?.raw_used_gb, 2)} GB`)}
              ${metricLine('Processed', `${toFixed(state.snapshot.storage?.processed_used_gb, 2)} GB`)}
              ${metricLine('Failed', `${toFixed(state.snapshot.storage?.failed_used_gb, 2)} GB`)}
            </div>
          </section>

          <section class="panel worker-panel">
            ${panelHeader('Worker State', 'Queue consumer heartbeat')}
            <div class="worker-grid">
              ${statusPill(state.snapshot.worker?.status?.toUpperCase() ?? 'UNKNOWN', statusMeta[state.snapshot.worker?.status]?.tone ?? 'off')}
              ${metricLine('Current Job', state.snapshot.worker?.current_job_id ?? '--')}
              ${metricLine('Processed Jobs', String(state.snapshot.worker?.processed_jobs ?? '--'))}
              ${metricLine('Failed Jobs', String(state.snapshot.worker?.failed_jobs ?? '--'))}
              ${metricLine('Heartbeat', formatTimestamp(state.snapshot.worker?.heartbeat_at))}
            </div>
          </section>

          <section class="panel alerts-panel">
            ${panelHeader('Alert Center', 'Red-first operational visibility')}
            <div class="alerts-list">
              ${(state.snapshot.alerts.length === 0 ? [{ level: 'info', message: 'No active alerts', source: 'system' }] : state.snapshot.alerts)
                .map((alert) => `<div class="alert-row ${alert.level}"><span>${alert.level.toUpperCase()}</span><span>${escapeHtml(alert.message)}</span><span class="alert-source">${escapeHtml(alert.source)}</span></div>`)
                .join('')}
            </div>
          </section>

          <section class="panel detail-panel">
            ${panelHeader('Machine Detail', state.selectedMachineId ? `Drill-down for ${state.selectedMachineId}` : 'Select a machine')}
            ${state.machineDetail ? machineDetailMarkup(state.machineDetail) : '<div class="empty-state">No machine selected</div>'}
          </section>

          <section class="panel flow-panel">
            ${panelHeader('Image Flow Viewer', 'Recent batch lifecycle by machine')}
            ${state.imageFlow.length ? imageFlowMarkup(state.imageFlow) : '<div class="empty-state">No recent batch data</div>'}
          </section>
        </main>
      </div>
    `
  }

  function bindEvents() {
    document.querySelectorAll('[data-machine-id]').forEach((element) => {
      element.addEventListener('click', () => {
        const machineId = element.getAttribute('data-machine-id')
        state.selectedMachineId = machineId || ''
        loadDrillDown(state.selectedMachineId)
        render()
      })
    })
  }

  function renderTrendChart() {
    const svg = document.querySelector('.spark-chart')
    if (!svg) {
      return
    }
    const data = state.history.map((item) => ({
      time: formatTimestamp(item.timestamp),
      cpu: item.server_metrics?.cpu_percent ?? 0,
      queue: item.queue?.queue_length ?? 0,
      disk: item.storage?.usage_percent ?? 0,
    }))
    if (data.length < 2) {
      svg.innerHTML = '<text x="20" y="30" class="chart-label">Waiting for live data...</text>'
      return
    }

    const width = 800
    const height = 220
    const padding = { top: 12, right: 12, bottom: 28, left: 42 }
    const chartWidth = width - padding.left - padding.right
    const chartHeight = height - padding.top - padding.bottom
    const maxQueue = Math.max(1, ...data.map((item) => item.queue))
    const maxValue = Math.max(100, maxQueue)

    const x = (index) => padding.left + (chartWidth * index) / (data.length - 1)
    const y = (value) => padding.top + chartHeight - (value / maxValue) * chartHeight
    const buildPath = (key) => data.map((item, index) => `${index === 0 ? 'M' : 'L'} ${x(index).toFixed(2)} ${y(item[key]).toFixed(2)}`).join(' ')

    const gridLines = Array.from({ length: 5 }, (_, idx) => {
      const value = (maxValue / 4) * idx
      const yPos = y(value)
      return `<g class="chart-grid"><line x1="${padding.left}" y1="${yPos}" x2="${width - padding.right}" y2="${yPos}"></line><text class="chart-label" x="4" y="${yPos + 4}">${Math.round(value)}</text></g>`
    }).join('')

    const xLabels = [0, Math.floor((data.length - 1) / 2), data.length - 1]
      .filter((value, index, array) => array.indexOf(value) === index)
      .map((index) => `<text class="chart-label" x="${x(index)}" y="${height - 6}" text-anchor="middle">${data[index].time}</text>`)
      .join('')

    svg.innerHTML = `
      ${gridLines}
      <path class="chart-path-cpu" d="${buildPath('cpu')}"></path>
      <path class="chart-path-queue" d="${buildPath('queue')}"></path>
      <path class="chart-path-disk" d="${buildPath('disk')}"></path>
      ${xLabels}
    `
  }

  function getSystemHealth(alerts) {
    if ((alerts || []).some((alert) => alert.level === 'critical')) {
      return { label: 'CRITICAL', tone: 'crit' }
    }
    if ((alerts || []).some((alert) => alert.level === 'warning')) {
      return { label: 'WARNING', tone: 'warn' }
    }
    return { label: 'NORMAL', tone: 'ok' }
  }

  function compareMachines(a, b) {
    const rank = { critical: 0, offline: 1, warning: 2, online: 3 }
    const rankDiff = (rank[a.status] ?? 9) - (rank[b.status] ?? 9)
    if (rankDiff !== 0) return rankDiff
    return a.machine_id.localeCompare(b.machine_id)
  }

  function appendHistory(current, snapshot) {
    return current.concat([{ timestamp: snapshot.timestamp, server_metrics: snapshot.server_metrics, queue: snapshot.queue, storage: snapshot.storage }]).slice(-30)
  }

  function panelHeader(title, subtitle) {
    return `<div class="panel-header"><h2>${title}</h2><span>${escapeHtml(subtitle)}</span></div>`
  }

  function bannerCard(label, value) {
    return `<div class="banner-card"><span class="banner-label">${label}</span><span class="banner-value">${value}</span></div>`
  }

  function metricTile(label, value, detail, tone) {
    return `<div class="metric-tile tone-${tone}"><span class="metric-label">${label}</span><strong class="metric-value">${escapeHtml(value)}</strong><span class="metric-detail">${escapeHtml(detail)}</span></div>`
  }

  function metricLine(label, value) {
    return `<div class="metric-line"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`
  }

  function statusPill(label, tone) {
    return `<span class="status-pill tone-${tone}">${escapeHtml(label)}</span>`
  }

  function machineCard(machine) {
    const meta = statusMeta[machine.status] || statusMeta.unknown
    const active = machine.machine_id === state.selectedMachineId ? 'active' : ''
    return `
      <button type="button" class="machine-card tone-${meta.tone} ${active}" data-machine-id="${machine.machine_id}">
        <div class="machine-card-header">
          <strong>${machine.machine_id}</strong>
          ${statusPill(meta.label, meta.tone)}
        </div>
        <div class="machine-card-grid">
          ${metricLine('FPS', toFixed(machine.fps, 1))}
          ${metricLine('Latency', `${machine.latency_ms} ms`)}
          ${metricLine('Queue', String(machine.queue_size))}
          ${metricLine('Last Upload', formatTimestamp(machine.last_upload))}
        </div>
      </button>
    `
  }

  function machineDetailMarkup(detail) {
    return `
      <div class="detail-grid">
        ${metricLine('Status', detail.machine.status.toUpperCase())}
        ${metricLine('Latency', `${detail.machine.latency_ms} ms`)}
        ${metricLine('FPS', toFixed(detail.machine.fps, 1))}
        ${metricLine('Queue Depth', String(detail.queue_depth))}
        ${metricLine('Last Upload', formatTimestamp(detail.machine.last_upload))}
        ${metricLine('Recent Batches', String(detail.recent_upload_count))}
        <div class="subpanel">
          <div class="subpanel-title">Recent Batches</div>
          ${detail.recent_batches.map((batch) => `<div class="batch-row"><span>${batch.job_id}</span><span>${batch.status}</span></div>`).join('')}
        </div>
      </div>
    `
  }

  function imageFlowMarkup(items) {
    return `<div class="flow-list">${items.map((item) => `
      <div class="flow-row tone-${(statusMeta[item.status] || statusMeta.unknown).tone}">
        <div><strong>${item.machine_id}</strong><div class="flow-meta">${escapeHtml(item.batch_filename || item.job_id)}</div></div>
        <div><div>${item.status.toUpperCase()}</div><div class="flow-meta">${item.image_count} image(s)</div></div>
        <div><div>${formatTimestamp(item.received_at)}</div><div class="flow-meta">${escapeHtml(item.last_error || item.processed_root || 'awaiting worker')}</div></div>
      </div>`).join('')}</div>`
  }

  function valueTone(value, warn, crit) {
    if (typeof value !== 'number') return 'off'
    if (value >= crit) return 'crit'
    if (value >= warn) return 'warn'
    return 'ok'
  }

  function formatPercent(value) {
    return typeof value === 'number' ? `${value.toFixed(1)}%` : '--'
  }

  function formatRate(value) {
    return typeof value === 'number' ? `${value.toFixed(2)} MB/s` : '--'
  }

  function formatTimestamp(value) {
    if (!value) return '--'
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? '--' : date.toLocaleTimeString()
  }

  function toFixed(value, digits) {
    return typeof value === 'number' ? value.toFixed(digits) : '--'
  }

  function signed(value) {
    return typeof value === 'number' ? `${value >= 0 ? '+' : ''}${value}` : '--'
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;')
  }

  bootstrap()
})()
