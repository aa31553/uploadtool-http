(function () {
  const app = document.getElementById('app')
  let currentView = ''

  async function getJson(path) {
    const token = window.localStorage.getItem('control_access_token') || ''
    const response = await fetch(path, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!response.ok) {
      throw new Error(`Request failed: ${path} (${response.status})`)
    }
    return response.json()
  }

  async function bootstrap() {
    if (!window.localStorage.getItem('control_access_token')) {
      renderLogin('')
      return
    }
    try {
      const overview = await getJson('/api/fleet/overview')
      const servers = await getJson('/api/fleet/servers')
      const machines = await getJson('/api/fleet/machines')
      const alerts = await getJson('/api/fleet/alerts')
      render({ overview, servers, machines, alerts })
    } catch (error) {
      renderLogin(error.message)
    }
  }

  function render(state) {
    currentView = 'dashboard'
    app.innerHTML = `
      <div class="app-shell">
        <div class="topbar">
          <div>
            <h1>Fleet Control Dashboard</h1>
            <p>Unified monitoring across ingestion servers</p>
          </div>
          <div>
            <span class="badge">Status: ${state.overview.fleet_status.toUpperCase()}</span>
            <button id="logout-button">Logout</button>
          </div>
        </div>
        <div class="grid">
          <div class="card"><h3>Servers</h3><p>${state.overview.server_counts.total}</p></div>
          <div class="card"><h3>Machines</h3><p>${state.overview.machine_counts.total}</p></div>
          <div class="card"><h3>Queue</h3><p>${state.overview.queue.total_queue_length}</p></div>
          <div class="card"><h3>Alerts</h3><p>${state.overview.alerts.active_total}</p></div>
        </div>
        <div class="list">
          <div class="card"><h4>Servers</h4><pre>${escapeHtml(JSON.stringify(state.servers, null, 2))}</pre></div>
          <div class="card"><h4>Machines</h4><pre>${escapeHtml(JSON.stringify(state.machines, null, 2))}</pre></div>
          <div class="card"><h4>Alerts</h4><pre>${escapeHtml(JSON.stringify(state.alerts, null, 2))}</pre></div>
        </div>
      </div>
    `
    document.getElementById('logout-button')?.addEventListener('click', () => {
      window.localStorage.removeItem('control_access_token')
      window.localStorage.removeItem('control_refresh_token')
      bootstrap()
    })
  }

  function renderLogin(message) {
    const employeeId = document.getElementById('employee-id')?.value || ''
    const password = document.getElementById('password')?.value || ''
    if (currentView === 'login' && !message) {
      return
    }
    currentView = 'login'
    app.innerHTML = `
      <div class="app-shell">
        <div class="card">
          <h3>Control Dashboard Login</h3>
          ${message ? `<p>${escapeHtml(message)}</p>` : ''}
          <p><input id="employee-id" placeholder="Employee ID" value="${escapeHtml(employeeId)}" /></p>
          <p><input id="password" type="password" placeholder="Password" value="${escapeHtml(password)}" /></p>
          <p><button id="login-button">Login</button></p>
        </div>
      </div>
    `
    document.getElementById('login-button')?.addEventListener('click', login)
  }

  async function login() {
    const employeeId = document.getElementById('employee-id')?.value || ''
    const password = document.getElementById('password')?.value || ''
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ employee_id: employeeId, password, client_type: 'dashboard', client_id: 'browser' }),
      })
      if (!response.ok) {
        throw new Error(`Login failed (${response.status})`)
      }
      const payload = await response.json()
      window.localStorage.setItem('control_access_token', payload.access_token)
      window.localStorage.setItem('control_refresh_token', payload.refresh_token)
      bootstrap()
    } catch (error) {
      renderLogin(error.message)
    }
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
  }

  bootstrap()
  window.setInterval(bootstrap, 5000)
})()
