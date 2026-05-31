// Fleet Orchestrator Dashboard

const API = {
    async get(path) {
        const resp = await fetch(path);
        return resp.json();
    },
    async post(path, body) {
        const resp = await fetch(path, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
        });
        return resp.json();
    }
};

// Mobile sidebar toggle
function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
    document.querySelector('.sidebar-overlay').classList.toggle('open');
}

// Navigation
document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const page = link.dataset.page;
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        document.getElementById(`page-${page}`).classList.add('active');
        link.classList.add('active');

        // Close sidebar on mobile after navigation
        if (window.innerWidth <= 768) {
            document.querySelector('.sidebar').classList.remove('open');
            document.querySelector('.sidebar-overlay').classList.remove('open');
        }

        if (page === 'dashboard') loadDashboard();
        if (page === 'agents') loadAgents();
        if (page === 'tools') loadTools();
        if (page === 'workflows') loadWorkflows();
        if (page === 'executions') loadExecutions();
        if (page === 'scheduler') loadScheduler();
        if (page === 'alerts') loadAlerts();
        if (page === 'policies') loadPolicies();
        if (page === 'escalations') loadEscalations();
        if (page === 'audit') loadAudit();
    });
});

// Dashboard
async function loadDashboard() {
    try {
        const stats = await API.get('/api/dashboard/stats');
        const grid = document.getElementById('stats-grid');
        grid.innerHTML = `
            <div class="stat-card">
                <div class="label">Total Agents</div>
                <div class="value">${stats.agents.total}</div>
            </div>
            <div class="stat-card">
                <div class="label">Online</div>
                <div class="value" style="color:var(--green)">${stats.agents.online}</div>
            </div>
            <div class="stat-card">
                <div class="label">Offline</div>
                <div class="value" style="color:var(--red)">${stats.agents.offline}</div>
            </div>
            <div class="stat-card">
                <div class="label">Total Tools</div>
                <div class="value" style="color:var(--accent)">${stats.tools.total}</div>
            </div>
            <div class="stat-card">
                <div class="label">Active Alerts</div>
                <div class="value" style="color:var(--red)">${stats.autonomous?.active_alerts || 0}</div>
            </div>
            <div class="stat-card">
                <div class="label">Escalations</div>
                <div class="value" style="color:var(--yellow)">${stats.autonomous?.active_escalations || 0}</div>
            </div>
            <div class="stat-card">
                <div class="label">Policies</div>
                <div class="value">${stats.autonomous?.policies_enabled || 0}/${stats.autonomous?.policies_total || 0}</div>
            </div>
            <div class="stat-card">
                <div class="label">Scheduled Jobs</div>
                <div class="value">${stats.autonomous?.scheduled_jobs || 0}</div>
            </div>
        `;

        const agents = await API.get('/api/agents');
        const statusList = document.getElementById('agent-status-list');
        statusList.innerHTML = '<table><thead><tr><th>Agent</th><th>URL</th><th>Status</th><th>Tools</th></tr></thead><tbody>' +
            agents.agents.map(a => `<tr>
                <td>${a.display_name}</td>
                <td style="color:var(--text-dim);font-size:12px">${a.url}</td>
                <td><span class="status status-${a.status}">${a.status}</span></td>
                <td>${a.tool_count}</td>
            </tr>`).join('') + '</tbody></table>';

        const execs = await API.get('/api/executions?limit=10');
        const execList = document.getElementById('recent-executions');
        if (execs.executions.length === 0) {
            execList.innerHTML = '<p style="color:var(--text-dim)">No recent executions</p>';
        } else {
            execList.innerHTML = '<table><thead><tr><th>Agent</th><th>Tool</th><th>Status</th><th>Duration</th><th>Time</th></tr></thead><tbody>' +
                execs.executions.map(e => `<tr>
                    <td>${e.agent_name}</td>
                    <td style="color:var(--accent)">${e.tool_name}</td>
                    <td><span class="status status-${e.status === 'success' ? 'online' : 'offline'}">${e.status}</span></td>
                    <td>${e.duration_ms || '-'}ms</td>
                    <td style="color:var(--text-dim);font-size:12px">${e.started_at || ''}</td>
                </tr>`).join('') + '</tbody></table>';
        }
    } catch (e) {
        console.error('Dashboard load error:', e);
    }
}

// Agents
async function loadAgents() {
    const data = await API.get('/api/agents');
    const grid = document.getElementById('agents-grid');
    grid.innerHTML = data.agents.map(a => `
        <div class="agent-card">
            <div class="agent-name">${a.display_name}</div>
            <div class="agent-url">${a.url}</div>
            <div class="agent-meta">
                <span class="status status-${a.status}">${a.status}</span>
                <span style="color:var(--text-dim)">${a.tool_count} tools</span>
            </div>
            <button class="btn btn-primary btn-sm" style="margin-top:12px"
                    onclick="connectAgent('${a.name}')">Connect</button>
            <button class="btn btn-sm" style="margin-top:12px;background:var(--bg);border:1px solid var(--border);color:var(--text)"
                    onclick="viewAgentTools('${a.name}')">View Tools</button>
        </div>
    `).join('');
}

async function connectAll() {
    const result = await API.post('/api/agents/connect-all');
    alert(`Connected! Total tools: ${result.total_tools}`);
    loadAgents();
}

async function connectAgent(name) {
    const result = await API.post(`/api/agents/${name}/connect`);
    alert(`${name}: ${result.status} (${result.tools_discovered} tools)`);
    loadAgents();
}

async function viewAgentTools(name) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.getElementById('page-tools').classList.add('active');
    document.querySelector('[data-page="tools"]').classList.add('active');

    const data = await API.get(`/api/agents/${name}/tools`);
    renderTools(data.tools, name);
}

// Tools
async function loadTools() {
    const data = await API.get('/api/tools/all');
    renderTools(data.tools);
}

async function searchTools() {
    const q = document.getElementById('tool-search').value;
    if (q.length < 2 && q.length > 0) return;
    const data = await API.get(`/api/tools/search?q=${encodeURIComponent(q)}`);
    renderTools(data.results);
}

function renderTools(tools, agentFilter) {
    const container = document.getElementById('tools-list');
    const title = agentFilter ? `Tools: ${agentFilter}` : 'All Tools';
    container.innerHTML = `<div class="card"><h3>${title} (${tools.length})</h3>` +
        tools.map(t => `
            <div class="tool-item">
                <div>
                    <div class="tool-name">${t.name}</div>
                    <div class="tool-desc">${(t.description || '').substring(0, 100)}</div>
                </div>
                <div class="tool-agent">${t.agent || t._agent || ''}</div>
            </div>
        `).join('') + '</div>';
}

// Workflows
async function loadWorkflows() {
    const data = await API.get('/api/workflows');
    const container = document.getElementById('workflows-list');
    if (!data.workflows || data.workflows.length === 0) {
        container.innerHTML = '<div class="card"><p style="color:var(--text-dim)">No workflows configured. Add YAML files to data/workflows/</p></div>';
        return;
    }
    container.innerHTML = data.workflows.map(w => `
        <div class="card">
            <h3>${w.name}</h3>
            <p style="margin-bottom:10px">${w.description}</p>
            <p style="color:var(--text-dim);font-size:12px">${w.steps} steps | Agents: ${w.agents.join(', ')}</p>
            <button class="btn btn-primary btn-sm" style="margin-top:10px"
                    onclick="runWorkflow('${w.name}')">Execute</button>
        </div>
    `).join('');
}

async function runWorkflow(name) {
    if (!confirm(`Execute workflow "${name}"?`)) return;
    const result = await API.post(`/api/workflows/${name}/execute`);
    alert(JSON.stringify(result, null, 2));
}

// Executions
async function loadExecutions() {
    const data = await API.get('/api/executions?limit=50');
    const container = document.getElementById('execution-log');
    if (data.executions.length === 0) {
        container.innerHTML = '<div class="card"><p style="color:var(--text-dim)">No executions yet</p></div>';
        return;
    }
    container.innerHTML = '<div class="card"><table><thead><tr><th>Agent</th><th>Tool</th><th>Status</th><th>Duration</th><th>Time</th><th>Error</th></tr></thead><tbody>' +
        data.executions.map(e => `<tr>
            <td>${e.agent_name}</td>
            <td style="color:var(--accent)">${e.tool_name}</td>
            <td><span class="status status-${e.status === 'success' ? 'online' : 'offline'}">${e.status}</span></td>
            <td>${e.duration_ms || '-'}ms</td>
            <td style="font-size:12px;color:var(--text-dim)">${e.started_at || ''}</td>
            <td style="font-size:11px;color:var(--red)">${e.error || ''}</td>
        </tr>`).join('') + '</tbody></table></div>';
}

// Chat
let ws = null;

function initChat() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/chat`);

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const container = document.getElementById('chat-messages');

        if (data.type === 'message') {
            container.innerHTML += `<div class="chat-msg assistant"><div class="bubble">${escapeHtml(data.content)}</div></div>`;
        } else if (data.type === 'tool_call') {
            container.innerHTML += `<div class="chat-msg tool"><div class="bubble">Calling: ${data.tool}</div></div>`;
        } else if (data.type === 'error') {
            container.innerHTML += `<div class="chat-msg tool"><div class="bubble" style="color:var(--red)">Error: ${escapeHtml(data.content)}</div></div>`;
        }
        container.scrollTop = container.scrollHeight;
    };

    ws.onerror = () => {
        document.getElementById('chat-messages').innerHTML += '<div class="chat-msg tool"><div class="bubble" style="color:var(--red)">WebSocket connection error</div></div>';
    };
}

function sendChat() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) initChat();

    const container = document.getElementById('chat-messages');
    container.innerHTML += `<div class="chat-msg user"><div class="bubble">${escapeHtml(msg)}</div></div>`;
    container.scrollTop = container.scrollHeight;

    ws.send(JSON.stringify({message: msg}));
    input.value = '';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Branding
async function loadBranding() {
    try {
        const b = await API.get('/api/branding');
        if (b.company_name) {
            document.getElementById('brand-name').textContent = b.company_name;
            document.getElementById('page-title').textContent = b.company_name;
        }
        if (b.logo_url) {
            const logo = document.getElementById('brand-logo');
            logo.src = b.logo_url;
            logo.style.display = 'block';
        }
        if (b.accent_color && b.accent_color !== '#6366f1') {
            document.documentElement.style.setProperty('--accent', b.accent_color);
        }
    } catch (e) {
        // Branding is optional — continue with defaults
    }
}

// Scheduler
async function loadScheduler() {
    const data = await API.get('/api/scheduler/jobs');
    const container = document.getElementById('scheduler-list');
    if (!data.jobs || data.jobs.length === 0) {
        container.innerHTML = '<div class="card"><p style="color:var(--text-dim)">No scheduled jobs configured</p></div>';
        return;
    }
    container.innerHTML = '<div class="card"><table><thead><tr><th>Name</th><th>Type</th><th>Trigger</th><th>Status</th><th>Last Run</th><th>Actions</th></tr></thead><tbody>' +
        data.jobs.map(j => `<tr>
            <td style="font-weight:500">${j.name}</td>
            <td>${j.action_type || ''}</td>
            <td style="color:var(--text-dim);font-size:12px">${j.trigger?.cron || (j.trigger?.interval_seconds ? j.trigger.interval_seconds + 's' : '-')}</td>
            <td><span class="status ${j.enabled ? 'status-online' : 'status-offline'}">${j.enabled ? 'enabled' : 'disabled'}</span></td>
            <td style="font-size:12px;color:var(--text-dim)">${j.last_run || 'never'}</td>
            <td>
                <button class="btn btn-sm btn-primary" onclick="toggleJob('${j.name}', ${!j.enabled})">${j.enabled ? 'Disable' : 'Enable'}</button>
                <button class="btn btn-sm" style="background:var(--bg);border:1px solid var(--border);color:var(--text);margin-left:4px" onclick="triggerJob('${j.name}')">Run Now</button>
            </td>
        </tr>`).join('') + '</tbody></table></div>';
}

async function toggleJob(name, enable) {
    const endpoint = enable ? 'enable' : 'disable';
    await API.post(`/api/scheduler/jobs/${name}/${endpoint}`);
    loadScheduler();
}

async function triggerJob(name) {
    if (!confirm(`Trigger job "${name}" now?`)) return;
    await API.post(`/api/scheduler/jobs/${name}/trigger`);
    alert('Job triggered');
}

// Alerts
async function loadAlerts() { loadAlertChannels(); }

async function loadAlertChannels() {
    const data = await API.get('/api/alerts/channels');
    const container = document.getElementById('alerts-content');
    container.innerHTML = '<div class="card"><h3>Notification Channels</h3>' +
        (data.channels && data.channels.length > 0 ?
            '<table><thead><tr><th>Name</th><th>Type</th><th>Status</th></tr></thead><tbody>' +
            data.channels.map(c => `<tr>
                <td>${c.name}</td>
                <td>${c.channel_type}</td>
                <td><span class="status ${c.enabled ? 'status-online' : 'status-offline'}">${c.enabled ? 'active' : 'disabled'}</span></td>
            </tr>`).join('') + '</tbody></table>'
            : '<p style="color:var(--text-dim)">No channels configured</p>') +
        '</div>';
}

async function loadAlertRules() {
    const data = await API.get('/api/alerts/rules');
    const container = document.getElementById('alerts-content');
    container.innerHTML = '<div class="card"><h3>Alert Rules</h3>' +
        (data.rules && data.rules.length > 0 ?
            '<table><thead><tr><th>Name</th><th>Condition</th><th>Severity</th><th>Status</th></tr></thead><tbody>' +
            data.rules.map(r => `<tr>
                <td>${r.name}</td>
                <td>${r.condition}</td>
                <td><span class="severity severity-${r.severity}">${r.severity}</span></td>
                <td><span class="status ${r.enabled ? 'status-online' : 'status-offline'}">${r.enabled ? 'active' : 'disabled'}</span></td>
            </tr>`).join('') + '</tbody></table>'
            : '<p style="color:var(--text-dim)">No alert rules configured</p>') +
        '</div>';
}

async function loadActiveAlerts() {
    const data = await API.get('/api/alerts/active');
    const container = document.getElementById('alerts-content');
    container.innerHTML = '<div class="card"><h3>Active Alerts</h3>' +
        (data.alerts && data.alerts.length > 0 ?
            '<table><thead><tr><th>Rule</th><th>Agent</th><th>Severity</th><th>Message</th><th>Fired</th><th>Actions</th></tr></thead><tbody>' +
            data.alerts.map(a => `<tr>
                <td>${a.rule_name}</td>
                <td>${a.agent_name || '-'}</td>
                <td><span class="severity severity-${a.severity}">${a.severity}</span></td>
                <td style="font-size:12px">${a.message}</td>
                <td style="font-size:12px;color:var(--text-dim)">${a.fired_at || ''}</td>
                <td><button class="btn btn-sm" style="background:var(--green);color:white" onclick="resolveAlert(${a.id})">Resolve</button></td>
            </tr>`).join('') + '</tbody></table>'
            : '<p style="color:var(--text-dim)">No active alerts</p>') +
        '</div>';
}

async function loadAlertHistory() {
    const data = await API.get('/api/alerts/history?limit=50');
    const container = document.getElementById('alerts-content');
    container.innerHTML = '<div class="card"><h3>Alert History</h3>' +
        (data.alerts && data.alerts.length > 0 ?
            '<table><thead><tr><th>Rule</th><th>Agent</th><th>Severity</th><th>Status</th><th>Fired</th><th>Resolved</th></tr></thead><tbody>' +
            data.alerts.map(a => `<tr>
                <td>${a.rule_name}</td>
                <td>${a.agent_name || '-'}</td>
                <td><span class="severity severity-${a.severity}">${a.severity}</span></td>
                <td><span class="status status-${a.status === 'resolved' ? 'online' : 'offline'}">${a.status}</span></td>
                <td style="font-size:12px;color:var(--text-dim)">${a.fired_at || ''}</td>
                <td style="font-size:12px;color:var(--text-dim)">${a.resolved_at || '-'}</td>
            </tr>`).join('') + '</tbody></table>'
            : '<p style="color:var(--text-dim)">No alert history</p>') +
        '</div>';
}

async function resolveAlert(id) {
    await API.post(`/api/alerts/${id}/resolve`);
    loadActiveAlerts();
}

// Policies
async function loadPolicies() {
    const data = await API.get('/api/policies');
    const container = document.getElementById('policies-list');
    if (!data.policies || data.policies.length === 0) {
        container.innerHTML = '<div class="card"><p style="color:var(--text-dim)">No policies loaded</p></div>';
        return;
    }
    container.innerHTML = data.policies.map(p => `
        <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                    <h3 style="text-transform:none;color:var(--text)">${p.name}</h3>
                    <p style="font-size:13px;color:var(--text-dim);margin-top:4px">${p.description || ''}</p>
                </div>
                <div>
                    <span class="status ${p.enabled ? 'status-online' : 'status-offline'}" style="margin-right:8px">${p.enabled ? 'enabled' : 'disabled'}</span>
                    <button class="btn btn-sm btn-primary" onclick="togglePolicy('${p.name}', ${!p.enabled})">${p.enabled ? 'Disable' : 'Enable'}</button>
                </div>
            </div>
            <div style="margin-top:12px;font-size:12px;color:var(--text-dim)">
                Trigger: <strong>${p.trigger_type || '-'}</strong> |
                Conditions: ${JSON.stringify(p.conditions || {})} |
                Cooldown: ${p.cooldown_seconds || 0}s |
                Actions: ${(p.actions || []).length}
            </div>
        </div>
    `).join('');
}

async function togglePolicy(name, enable) {
    const endpoint = enable ? 'enable' : 'disable';
    await API.post(`/api/policies/${name}/${endpoint}`);
    loadPolicies();
}

// Escalations
async function loadEscalations() {
    const [statsData, activeData] = await Promise.all([
        API.get('/api/escalations/stats'),
        API.get('/api/escalations/active'),
    ]);

    const statsGrid = document.getElementById('escalation-stats-grid');
    const stats = statsData.stats || {};
    statsGrid.innerHTML = `
        <div class="stat-card">
            <div class="label">Active Issues</div>
            <div class="value" style="color:var(--yellow)">${stats.active_count || 0}</div>
        </div>
        <div class="stat-card">
            <div class="label">Acknowledged</div>
            <div class="value">${stats.acknowledged_count || 0}</div>
        </div>
        <div class="stat-card">
            <div class="label">Highest Level</div>
            <div class="value" style="color:var(--red)">${stats.highest_level !== undefined ? 'L' + stats.highest_level : '-'}</div>
        </div>
        <div class="stat-card">
            <div class="label">Total Resolved</div>
            <div class="value" style="color:var(--green)">${stats.total_resolved || 0}</div>
        </div>
    `;

    const container = document.getElementById('escalations-list');
    const escalations = activeData.escalations || [];
    if (escalations.length === 0) {
        container.innerHTML = '<div class="card"><p style="color:var(--text-dim)">No active escalations</p></div>';
        return;
    }
    container.innerHTML = '<div class="card"><table><thead><tr><th>Issue</th><th>Severity</th><th>Level</th><th>Attempts</th><th>Acknowledged</th><th>Actions</th></tr></thead><tbody>' +
        escalations.map(e => `<tr>
            <td>${e.issue_key}</td>
            <td><span class="severity severity-${e.severity}">${e.severity}</span></td>
            <td><span class="escalation-level level-${e.current_level}">L${e.current_level}</span></td>
            <td>${e.attempt_count}</td>
            <td>${e.acknowledged ? 'Yes' : 'No'}</td>
            <td>
                ${!e.acknowledged ? `<button class="btn btn-sm" style="background:var(--yellow);color:#000" onclick="ackEscalation('${e.issue_key}')">Ack</button>` : ''}
                <button class="btn btn-sm" style="background:var(--green);color:white;margin-left:4px" onclick="resolveEscalation('${e.issue_key}')">Resolve</button>
            </td>
        </tr>`).join('') + '</tbody></table></div>';
}

async function ackEscalation(key) {
    await API.post(`/api/escalations/${encodeURIComponent(key)}/acknowledge`);
    loadEscalations();
}

async function resolveEscalation(key) {
    await API.post(`/api/escalations/${encodeURIComponent(key)}/resolve`);
    loadEscalations();
}

// Audit Log
let _auditData = [];

async function loadAudit() {
    const data = await API.get('/api/audit?limit=200');
    _auditData = data.entries || [];
    renderAudit(_auditData);
}

function filterAudit() {
    const q = (document.getElementById('audit-filter').value || '').toLowerCase();
    if (!q) { renderAudit(_auditData); return; }
    const filtered = _auditData.filter(e =>
        (e.action || '').toLowerCase().includes(q) ||
        (e.agent_name || '').toLowerCase().includes(q) ||
        (e.tool_name || '').toLowerCase().includes(q) ||
        (e.user || '').toLowerCase().includes(q) ||
        JSON.stringify(e.details || '').toLowerCase().includes(q)
    );
    renderAudit(filtered);
}

function renderAudit(entries) {
    const container = document.getElementById('audit-log-content');
    if (!entries || entries.length === 0) {
        container.innerHTML = '<div class="card"><p style="color:var(--text-dim)">No audit entries found</p></div>';
        return;
    }
    container.innerHTML = '<div class="card"><table><thead><tr><th>Timestamp</th><th>Action</th><th>Agent</th><th>Tool</th><th>User</th><th>Details</th></tr></thead><tbody>' +
        entries.map(e => {
            const details = typeof e.details === 'object' ? JSON.stringify(e.details).substring(0, 80) : (e.details || '').substring(0, 80);
            return `<tr>
                <td style="font-size:12px;color:var(--text-dim);white-space:nowrap">${e.timestamp || ''}</td>
                <td style="font-weight:500">${e.action || ''}</td>
                <td>${e.agent_name || '-'}</td>
                <td style="color:var(--accent)">${e.tool_name || '-'}</td>
                <td>${e.user || '-'}</td>
                <td style="font-size:11px;color:var(--text-dim);max-width:200px;overflow:hidden;text-overflow:ellipsis">${escapeHtml(details)}</td>
            </tr>`;
        }).join('') + '</tbody></table></div>';
}

// Initial load
loadBranding();
loadDashboard();
