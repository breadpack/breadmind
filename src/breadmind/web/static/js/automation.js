(function () {
    'use strict';

    const STORAGE_KEY = 'breadmind_ptab_automation';

    // ── Helpers ──────────────────────────────────────────────────────────

    function esc(str) {
        if (!str && str !== 0) return '';
        const d = document.createElement('div');
        d.textContent = String(str);
        return d.innerHTML;
    }

    function authHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const token = document.cookie.match(/session_token=([^;]+)/)?.[1];
        if (token) headers['Authorization'] = `Bearer ${token}`;
        return headers;
    }

    async function apiFetch(url, opts = {}) {
        const headers = authHeaders();
        const resp = await fetch(url, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(body.error || body.detail || `HTTP ${resp.status}`);
        }
        return resp.json().catch(() => ({}));
    }

    function toast(msg, type) {
        if (typeof showToast === 'function') showToast(msg, type || 'info');
    }

    function parseProgress(raw) {
        if (!raw) return { percentage: 0, message: '' };
        if (typeof raw === 'string') { try { raw = JSON.parse(raw); } catch { return { percentage: 0, message: '' }; } }
        return { percentage: raw.percentage || 0, message: raw.message || '', totalSteps: raw.total_steps || 0, lastStep: raw.last_completed_step || 0 };
    }

    function formatJobTime(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            const pad = n => String(n).padStart(2, '0');
            return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
        } catch { return ''; }
    }

    // ── Tab definitions ──────────────────────────────────────────────────

    const TABS = [
        { id: 'webhooks',  label: 'Webhooks' },
        { id: 'scheduler', label: 'Scheduler' },
        { id: 'swarm',     label: 'Swarm' },
        { id: 'jobs',      label: 'Jobs' },
        { id: 'containers',label: 'Containers' },
    ];

    // ── Page Init ────────────────────────────────────────────────────────

    window.initAutomationPage = function () {
        const container = document.getElementById('automation-content');
        if (!container) return;

        // Make container a flex column so panels stretch
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
        container.style.flex = '1';
        container.style.overflow = 'hidden';

        // Build tab bar
        let tabsHtml = '<div class="page-tabs">';
        for (const t of TABS) {
            tabsHtml += `<button class="page-tab" data-subtab="${t.id}" onclick="switchPageTab('automation','${t.id}')">${t.label}</button>`;
        }
        tabsHtml += '</div>';

        // Build panels (no wrapper div — direct children for flex layout)
        let panelsHtml = '';
        for (const t of TABS) {
            const content = t.id === 'webhooks' ? '<div id="webhook-content"></div>' : '';
            panelsHtml += `<div class="page-panel" id="subtab-automation-${t.id}" style="display:none;">${content}</div>`;
        }

        container.innerHTML = tabsHtml + panelsHtml;

        // Restore last tab — defer to next tick so DOM is fully updated
        let saved = 'webhooks';
        try { saved = localStorage.getItem(STORAGE_KEY) || 'webhooks'; } catch (e) {}
        activateAutomationTab(saved);
        setTimeout(function() { loadAutomationTab(saved); }, 0);
    };

    // ── Tab activation (explicit display toggle, no CSS dependency) ─────

    function activateAutomationTab(tabName) {
        const container = document.getElementById('automation-content');
        if (!container) return;
        container.querySelectorAll('.page-tab').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.subtab === tabName);
        });
        container.querySelectorAll('.page-panel').forEach(function(panel) {
            panel.style.display = panel.id === 'subtab-automation-' + tabName ? 'block' : 'none';
        });
        try { localStorage.setItem(STORAGE_KEY, tabName); } catch (e) {}
    }

    // ── Hook switchPageTab ───────────────────────────────────────────────

    (function () {
        const _orig = window.switchPageTab;
        window.switchPageTab = function (pageId, tabName) {
            if (typeof _orig === 'function') _orig(pageId, tabName);
            if (pageId === 'automation') {
                activateAutomationTab(tabName);
                loadAutomationTab(tabName);
            }
        };
    })();

    // ── Tab Dispatcher ───────────────────────────────────────────────────

    window.loadAutomationTab = function (tab) {
        switch (tab) {
            case 'webhooks':
                if (typeof initWebhookTab === 'function') initWebhookTab();
                break;
            case 'scheduler':
                renderScheduler();
                break;
            case 'swarm':
                renderSwarm();
                break;
            case 'jobs':
                renderJobs();
                break;
            case 'containers':
                renderContainers();
                break;
        }
    };

    // ── Scheduler ────────────────────────────────────────────────────────

    async function renderScheduler() {
        const panel = document.getElementById('subtab-automation-scheduler');
        if (!panel) return;
        panel.innerHTML = '<div style="color:var(--text-secondary,#94a3b8);font-size:12px;">Loading...</div>';

        let crons = [], heartbeats = [];
        try {
            const cd = await apiFetch('/api/scheduler/cron');
            crons = cd.jobs || cd.crons || cd || [];
        } catch { crons = []; }
        try {
            const hd = await apiFetch('/api/scheduler/heartbeat');
            heartbeats = hd.heartbeats || hd || [];
        } catch { heartbeats = []; }

        let html = '';

        // ── Cron Jobs ────────────────────────────────────────────────────
        html += `<div class="wh-card" style="margin-bottom:16px;">
            <div class="wh-card-header">
                <div class="wh-card-title">Cron Jobs</div>
            </div>`;
        if (crons.length === 0) {
            html += `<div style="color:var(--text-tertiary,#64748b);font-size:12px;padding:8px 0;">No cron jobs defined.</div>`;
        } else {
            html += '<div class="wh-list">';
            for (const c of crons) {
                html += `<div class="wh-card" style="margin-bottom:8px;">
                    <div class="wh-card-header">
                        <div class="wh-card-title">${esc(c.name)}</div>
                        <div class="wh-card-actions">
                            <button class="wh-card-btn danger" onclick="deleteAutoCron('${esc(c.id)}')">Delete</button>
                        </div>
                    </div>
                    <div class="wh-card-meta">
                        <span>Schedule: <strong>${esc(c.schedule)}</strong></span>
                        <span>Task: <strong>${esc(c.task)}</strong></span>
                    </div>
                </div>`;
            }
            html += '</div>';
        }
        // Add form
        html += `<div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;align-items:center;">
            <input class="wh-input" id="auto-cron-name" placeholder="Job name" style="width:120px;" />
            <input class="wh-input" id="auto-cron-schedule" placeholder="0 9 * * 1" style="width:130px;" />
            <input class="wh-input" id="auto-cron-task" placeholder="Message to agent" style="flex:1;min-width:160px;" />
            <button class="wh-btn wh-btn-primary" onclick="addAutoCron()">Add</button>
        </div>`;
        html += '</div>';

        // ── Heartbeats ───────────────────────────────────────────────────
        html += `<div class="wh-card">
            <div class="wh-card-header">
                <div class="wh-card-title">Heartbeats</div>
            </div>`;
        if (heartbeats.length === 0) {
            html += `<div style="color:var(--text-tertiary,#64748b);font-size:12px;padding:8px 0;">No heartbeats defined.</div>`;
        } else {
            html += '<div class="wh-list">';
            for (const h of heartbeats) {
                html += `<div class="wh-card" style="margin-bottom:8px;">
                    <div class="wh-card-header">
                        <div class="wh-card-title">${esc(h.name)}</div>
                        <div class="wh-card-actions">
                            <button class="wh-card-btn danger" onclick="deleteAutoHb('${esc(h.id)}')">Delete</button>
                        </div>
                    </div>
                    <div class="wh-card-meta">
                        <span>Interval: <strong>${esc(h.interval_minutes || h.interval)} min</strong></span>
                        <span>Task: <strong>${esc(h.task)}</strong></span>
                    </div>
                </div>`;
            }
            html += '</div>';
        }
        // Add form
        html += `<div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;align-items:center;">
            <input class="wh-input" id="auto-hb-name" placeholder="Name" style="width:120px;" />
            <input class="wh-input" id="auto-hb-interval" type="number" min="1" placeholder="30" style="width:80px;" />
            <span style="color:var(--text-tertiary,#64748b);font-size:12px;line-height:32px;">min</span>
            <input class="wh-input" id="auto-hb-task" placeholder="Message to agent" style="flex:1;min-width:160px;" />
            <button class="wh-btn wh-btn-primary" onclick="addAutoHb()">Add</button>
        </div>`;
        html += '</div>';

        panel.innerHTML = html;
    }

    window.addAutoCron = async function () {
        const name     = document.getElementById('auto-cron-name')?.value.trim();
        const schedule = document.getElementById('auto-cron-schedule')?.value.trim();
        const task     = document.getElementById('auto-cron-task')?.value.trim();
        if (!name || !schedule || !task) { toast('Fill all cron fields', 'warning'); return; }
        try {
            await apiFetch('/api/scheduler/cron', { method: 'POST', body: JSON.stringify({ name, schedule, task }) });
            toast('Cron job added', 'success');
            renderScheduler();
        } catch (e) { toast(e.message, 'error'); }
    };

    window.deleteAutoCron = async function (id) {
        if (!confirm('Delete this cron job?')) return;
        try {
            await apiFetch(`/api/scheduler/cron/${id}`, { method: 'DELETE' });
            toast('Cron job deleted', 'success');
            renderScheduler();
        } catch (e) { toast(e.message, 'error'); }
    };

    window.addAutoHb = async function () {
        const name     = document.getElementById('auto-hb-name')?.value.trim();
        const interval = parseInt(document.getElementById('auto-hb-interval')?.value, 10);
        const task     = document.getElementById('auto-hb-task')?.value.trim();
        if (!name || !interval || !task) { toast('Fill all heartbeat fields', 'warning'); return; }
        try {
            await apiFetch('/api/scheduler/heartbeat', { method: 'POST', body: JSON.stringify({ name, interval_minutes: interval, task }) });
            toast('Heartbeat added', 'success');
            renderScheduler();
        } catch (e) { toast(e.message, 'error'); }
    };

    window.deleteAutoHb = async function (id) {
        if (!confirm('Delete this heartbeat?')) return;
        try {
            await apiFetch(`/api/scheduler/heartbeat/${id}`, { method: 'DELETE' });
            toast('Heartbeat deleted', 'success');
            renderScheduler();
        } catch (e) { toast(e.message, 'error'); }
    };

    // ── Swarm ────────────────────────────────────────────────────────────

    async function renderSwarm() {
        const panel = document.getElementById('subtab-automation-swarm');
        if (!panel) return;
        panel.innerHTML = '<div style="color:var(--text-secondary,#94a3b8);font-size:12px;">Loading...</div>';

        let swarmStatus = {}, swarmList = [], orchStatus = {};
        try { swarmStatus   = await apiFetch('/api/swarm/status'); } catch { swarmStatus = {}; }
        try { const d = await apiFetch('/api/swarm/list'); swarmList = d.swarms || d || []; } catch { swarmList = []; }
        try { orchStatus    = await apiFetch('/api/orchestrator/status'); } catch { orchStatus = {}; }

        const orchAvail   = orchStatus.available !== false;
        const activeCount = Array.isArray(swarmList) ? swarmList.filter(s => s.status === 'running' || s.status === 'active').length : (swarmStatus.active_count || 0);

        let html = '';

        // Status cards
        html += `<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
            <div class="wh-card" style="flex:1;min-width:160px;">
                <div class="wh-card-title" style="font-size:12px;color:var(--text-secondary,#94a3b8);">Orchestrator</div>
                <div style="margin-top:4px;">
                    <span class="wh-badge ${orchAvail ? 'enabled' : 'disabled'}">
                        <span class="wh-badge-dot"></span>${orchAvail ? 'Available' : 'Unavailable'}
                    </span>
                </div>
            </div>
            <div class="wh-card" style="flex:1;min-width:160px;">
                <div class="wh-card-title" style="font-size:12px;color:var(--text-secondary,#94a3b8);">Active Swarms</div>
                <div style="margin-top:4px;font-size:22px;font-weight:600;">${esc(activeCount)}</div>
            </div>
        </div>`;

        // Launch Swarm form
        html += `<div class="wh-card" style="margin-bottom:16px;">
            <div class="wh-card-header"><div class="wh-card-title">Launch Swarm</div></div>
            <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
                <input class="wh-input" id="auto-swarm-goal" placeholder="Goal for the swarm team..." style="flex:1;min-width:200px;" />
                <button class="wh-btn wh-btn-primary" onclick="launchAutoSwarm()">Launch Swarm</button>
            </div>
        </div>`;

        // Spawn Sub-agent form
        html += `<div class="wh-card" style="margin-bottom:16px;">
            <div class="wh-card-header"><div class="wh-card-title">Spawn Sub-agent</div></div>
            <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
                <input class="wh-input" id="auto-subagent-task" placeholder="Task to delegate..." style="flex:1;min-width:200px;" />
                <button class="wh-btn wh-btn-secondary" onclick="spawnAutoSubagent()">Spawn</button>
            </div>
        </div>`;

        // Swarm history
        html += `<div class="wh-card">
            <div class="wh-card-header"><div class="wh-card-title">Swarm History</div></div>`;
        if (!Array.isArray(swarmList) || swarmList.length === 0) {
            html += `<div style="color:var(--text-tertiary,#64748b);font-size:12px;padding:8px 0;">No swarms yet.</div>`;
        } else {
            html += '<div class="wh-list" style="margin-top:8px;">';
            for (const s of swarmList) {
                const statusClass = s.status === 'completed' ? 'enabled' : s.status === 'failed' ? 'disabled' : 'enabled';
                html += `<div class="wh-card" style="margin-bottom:8px;">
                    <div class="wh-card-header">
                        <div class="wh-card-title">${esc(s.goal || s.id)}</div>
                        <div class="wh-card-actions">
                            <span class="wh-badge ${statusClass}"><span class="wh-badge-dot"></span>${esc(s.status || 'unknown')}</span>
                        </div>
                    </div>
                    ${s.created_at ? `<div class="wh-card-meta"><span>${esc(s.created_at)}</span></div>` : ''}
                </div>`;
            }
            html += '</div>';
        }
        html += '</div>';

        panel.innerHTML = html;
    }

    window.launchAutoSwarm = async function () {
        const goal = document.getElementById('auto-swarm-goal')?.value.trim();
        if (!goal) { toast('Enter a goal for the swarm', 'warning'); return; }
        try {
            await apiFetch('/api/swarm/spawn', { method: 'POST', body: JSON.stringify({ goal }) });
            toast('Swarm launched', 'success');
            document.getElementById('auto-swarm-goal').value = '';
            renderSwarm();
        } catch (e) { toast(e.message, 'error'); }
    };

    window.spawnAutoSubagent = async function () {
        const task = document.getElementById('auto-subagent-task')?.value.trim();
        if (!task) { toast('Enter a task for the sub-agent', 'warning'); return; }
        try {
            await apiFetch('/api/subagent/spawn', { method: 'POST', body: JSON.stringify({ task }) });
            toast('Sub-agent spawned', 'success');
            document.getElementById('auto-subagent-task').value = '';
        } catch (e) { toast(e.message, 'error'); }
    };

    // ── Jobs ─────────────────────────────────────────────────────────────

    async function renderJobs() {
        const panel = document.getElementById('subtab-automation-jobs');
        if (!panel) return;
        panel.innerHTML = '<div style="color:var(--text-secondary,#94a3b8);font-size:12px;">Loading...</div>';

        let codingJobs = [], bgJobs = [];
        try { const d = await apiFetch('/api/coding-jobs'); codingJobs = d.jobs || d || []; } catch { codingJobs = []; }
        try { const d = await apiFetch('/api/bg-jobs');     bgJobs     = d.jobs || d || []; } catch { bgJobs = []; }

        let html = '';

        // Coding Jobs
        html += `<div class="wh-card" style="margin-bottom:16px;">
            <div class="wh-card-header"><div class="wh-card-title">Coding Jobs</div></div>`;
        if (!Array.isArray(codingJobs) || codingJobs.length === 0) {
            html += `<div style="color:var(--text-tertiary,#64748b);font-size:12px;padding:8px 0;">No coding jobs.</div>`;
        } else {
            html += '<div class="wh-list" style="margin-top:8px;">';
            for (const j of codingJobs) {
                const statusClass = j.status === 'completed' ? 'enabled' : j.status === 'failed' ? 'disabled' : 'enabled';
                const title = j.project || j.title || j.name || j.id;
                const progress = parseProgress(j.progress);
                const createdAt = formatJobTime(j.created_at);

                let metaParts = [];
                if (j.job_type) metaParts.push(`<span>Type: <strong>${esc(j.job_type)}</strong></span>`);
                if (j.platform) metaParts.push(`<span>Platform: <strong>${esc(j.platform)}</strong></span>`);
                if (createdAt) metaParts.push(`<span>Created: <strong>${esc(createdAt)}</strong></span>`);
                if (j.phases) metaParts.push(`<span>Phases: <strong>${esc(Array.isArray(j.phases) ? j.phases.join(', ') : j.phases)}</strong></span>`);

                html += `<div class="wh-card" style="margin-bottom:8px;">
                    <div class="wh-card-header">
                        <div class="wh-card-title">${esc(title)}</div>
                        <div class="wh-card-actions">
                            <span class="wh-badge ${statusClass}"><span class="wh-badge-dot"></span>${esc(j.status || 'unknown')}</span>
                        </div>
                    </div>
                    ${j.description ? `<div style="color:var(--text-secondary,#94a3b8);font-size:12px;padding:2px 0 4px;">${esc(j.description)}</div>` : ''}
                    ${metaParts.length ? `<div class="wh-card-meta">${metaParts.join('')}</div>` : ''}
                    ${progress.percentage > 0 ? `<div style="margin-top:6px;">
                        <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-tertiary,#64748b);margin-bottom:2px;">
                            <span>${esc(progress.message || 'Progress')}</span>
                            <span>${progress.percentage}%</span>
                        </div>
                        <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
                            <div style="height:100%;width:${Math.min(progress.percentage, 100)}%;background:var(--accent,#6366f1);border-radius:2px;transition:width 0.3s;"></div>
                        </div>
                    </div>` : ''}
                    ${j.error ? `<div style="color:var(--error,#ef4444);font-size:12px;margin-top:4px;">${esc(j.error)}</div>` : ''}
                </div>`;
            }
            html += '</div>';
        }
        html += '</div>';

        // Background Jobs
        html += `<div class="wh-card">
            <div class="wh-card-header"><div class="wh-card-title">Background Jobs</div></div>`;
        if (!Array.isArray(bgJobs) || bgJobs.length === 0) {
            html += `<div style="color:var(--text-tertiary,#64748b);font-size:12px;padding:8px 0;">No background jobs.</div>`;
        } else {
            html += '<div class="wh-list" style="margin-top:8px;">';
            for (const j of bgJobs) {
                const statusClass = j.status === 'completed' ? 'enabled' : j.status === 'failed' ? 'disabled' : 'enabled';
                const title = j.title || j.name || j.id;
                const progress = parseProgress(j.progress);
                const createdAt = formatJobTime(j.created_at);
                const updatedAt = formatJobTime(j.updated_at);

                let metaParts = [];
                if (j.job_type) metaParts.push(`<span>Type: <strong>${esc(j.job_type)}</strong></span>`);
                if (j.platform) metaParts.push(`<span>Platform: <strong>${esc(j.platform)}</strong></span>`);
                if (createdAt) metaParts.push(`<span>Created: <strong>${esc(createdAt)}</strong></span>`);
                if (updatedAt) metaParts.push(`<span>Updated: <strong>${esc(updatedAt)}</strong></span>`);

                html += `<div class="wh-card" style="margin-bottom:8px;">
                    <div class="wh-card-header">
                        <div class="wh-card-title">${esc(title)}</div>
                        <div class="wh-card-actions">
                            <span class="wh-badge ${statusClass}"><span class="wh-badge-dot"></span>${esc(j.status || 'unknown')}</span>
                        </div>
                    </div>
                    ${j.description ? `<div style="color:var(--text-secondary,#94a3b8);font-size:12px;padding:2px 0 4px;">${esc(j.description)}</div>` : ''}
                    ${metaParts.length ? `<div class="wh-card-meta">${metaParts.join('')}</div>` : ''}
                    ${progress.percentage > 0 ? `<div style="margin-top:6px;">
                        <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-tertiary,#64748b);margin-bottom:2px;">
                            <span>${esc(progress.message || 'Progress')}</span>
                            <span>${progress.percentage}%</span>
                        </div>
                        <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
                            <div style="height:100%;width:${Math.min(progress.percentage, 100)}%;background:var(--accent,#6366f1);border-radius:2px;transition:width 0.3s;"></div>
                        </div>
                    </div>` : ''}
                    ${j.error ? `<div style="color:var(--error,#ef4444);font-size:12px;margin-top:4px;">${esc(j.error)}</div>` : ''}
                    ${j.result ? `<div style="color:var(--success,#22c55e);font-size:12px;margin-top:4px;">Result: ${esc(typeof j.result === 'string' ? j.result : JSON.stringify(j.result))}</div>` : ''}
                </div>`;
            }
            html += '</div>';
        }
        html += '</div>';

        panel.innerHTML = html;
    }

    // ── Containers ───────────────────────────────────────────────────────

    async function renderContainers() {
        const panel = document.getElementById('subtab-automation-containers');
        if (!panel) return;
        panel.innerHTML = '<div style="color:var(--text-secondary,#94a3b8);font-size:12px;">Loading...</div>';

        let status = {};
        try { status = await apiFetch('/api/container/status'); } catch { status = {}; }

        const dockerAvail = status.available !== false && status.docker_available !== false;
        const runningCount = status.running_count || (Array.isArray(status.containers) ? status.containers.filter(c => c.status === 'running').length : 0);
        const containers  = status.containers || [];

        let html = '';

        // Docker status
        html += `<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
            <div class="wh-card" style="flex:1;min-width:160px;">
                <div class="wh-card-title" style="font-size:12px;color:var(--text-secondary,#94a3b8);">Docker</div>
                <div style="margin-top:4px;">
                    <span class="wh-badge ${dockerAvail ? 'enabled' : 'disabled'}">
                        <span class="wh-badge-dot"></span>${dockerAvail ? 'Available' : 'Unavailable'}
                    </span>
                </div>
            </div>
            <div class="wh-card" style="flex:1;min-width:160px;">
                <div class="wh-card-title" style="font-size:12px;color:var(--text-secondary,#94a3b8);">Running</div>
                <div style="margin-top:4px;font-size:22px;font-weight:600;">${esc(runningCount)}</div>
            </div>
        </div>`;

        // Command execution form
        html += `<div class="wh-card" style="margin-bottom:16px;">
            <div class="wh-card-header"><div class="wh-card-title">Run Command</div></div>
            <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
                <input class="wh-input" id="auto-container-cmd" placeholder="Command to run in container..." style="flex:1;min-width:200px;" />
                <button class="wh-btn wh-btn-primary" onclick="runAutoContainer()">Run</button>
            </div>
            <pre id="auto-container-output" style="display:none;margin-top:8px;background:#0f172a;border:1px solid #334155;border-radius:6px;padding:8px;font-size:12px;max-height:200px;overflow-y:auto;white-space:pre-wrap;"></pre>
        </div>`;

        // Running containers list
        html += `<div class="wh-card">
            <div class="wh-card-header"><div class="wh-card-title">Running Containers</div></div>`;
        if (!Array.isArray(containers) || containers.length === 0) {
            html += `<div style="color:var(--text-tertiary,#64748b);font-size:12px;padding:8px 0;">No containers found.</div>`;
        } else {
            html += '<div class="wh-list" style="margin-top:8px;">';
            for (const c of containers) {
                html += `<div class="wh-card" style="margin-bottom:8px;">
                    <div class="wh-card-header">
                        <div class="wh-card-title">${esc(c.name || c.id)}</div>
                        <div class="wh-card-actions">
                            <span class="wh-badge enabled"><span class="wh-badge-dot"></span>${esc(c.status || 'running')}</span>
                        </div>
                    </div>
                    ${c.image ? `<div class="wh-card-meta"><span>Image: <strong>${esc(c.image)}</strong></span></div>` : ''}
                </div>`;
            }
            html += '</div>';
        }
        html += '</div>';

        panel.innerHTML = html;
    }

    window.runAutoContainer = async function () {
        const cmd = document.getElementById('auto-container-cmd')?.value.trim();
        if (!cmd) { toast('Enter a command', 'warning'); return; }
        const outEl = document.getElementById('auto-container-output');
        if (outEl) { outEl.style.display = 'none'; outEl.textContent = ''; }
        try {
            const result = await apiFetch('/api/container/run', { method: 'POST', body: JSON.stringify({ command: cmd }) });
            if (outEl) {
                outEl.textContent = result.output || result.stdout || JSON.stringify(result, null, 2);
                outEl.style.display = 'block';
            }
        } catch (e) {
            toast(e.message, 'error');
            if (outEl) { outEl.textContent = e.message; outEl.style.display = 'block'; }
        }
    };

})();
