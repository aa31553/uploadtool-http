const defaultApiBase = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'
const defaultWsBase = import.meta.env.VITE_WS_BASE ?? 'ws://127.0.0.1:8000'

export const apiBase = defaultApiBase.replace(/\/$/, '')
export const wsBase = defaultWsBase.replace(/\/$/, '')

async function getJson(path) {
  const response = await fetch(`${apiBase}${path}`)
  if (!response.ok) {
    throw new Error(`Request failed: ${path} (${response.status})`)
  }
  return response.json()
}

export async function fetchDashboardSnapshot() {
  const [machines, serverMetrics, queue, storage, alerts, worker] = await Promise.all([
    getJson('/api/machines'),
    getJson('/api/server/metrics'),
    getJson('/api/queue/status'),
    getJson('/api/storage/status'),
    getJson('/api/alerts'),
    getJson('/api/worker/status'),
  ])

  return {
    timestamp: new Date().toISOString(),
    machines,
    server_metrics: serverMetrics,
    queue,
    storage,
    alerts,
    worker,
  }
}

export function fetchMachineDetail(machineId) {
  return getJson(`/api/machines/${encodeURIComponent(machineId)}`)
}

export function fetchRecentImageFlow(machineId) {
  const query = machineId ? `?machine_id=${encodeURIComponent(machineId)}&limit=12` : '?limit=12'
  return getJson(`/api/image-flow/recent${query}`)
}

export function connectDashboardStream({ onSnapshot, onError }) {
  const socket = new WebSocket(`${wsBase}/ws/live`)
  socket.onmessage = (event) => {
    try {
      onSnapshot(JSON.parse(event.data))
    } catch (error) {
      onError?.(error)
    }
  }
  socket.onerror = (event) => onError?.(event)
  return socket
}
