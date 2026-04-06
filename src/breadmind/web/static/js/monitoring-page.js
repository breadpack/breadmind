(function () {
    'use strict';

    const STORAGE_KEY = 'breadmind_ptab_monitoring';

    const TABS = [
        { id: 'events',    label: 'Events' },
        { id: 'audit',     label: 'Audit Log' },
        { id: 'usage',     label: 'Usage' },
        { id: 'metrics',   label: 'Tool Metrics' },
        { id: 'approvals', label: 'Approvals' },
    ];

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

    // ── Page Init ────────────────────────────────────────────────────────

    window.initMonitoringPage = function () {
        const pageEl = document.getElementById('page-monitoring');
        if (!pageEl) return;

        // Guard: don't re-inject tabs if already done
        if (pageEl.querySelector('.page-tabs')) return;

        const monDiv = pageEl.querySelector('.monitoring');
        if (!monDiv) return;

        // Ensure the page element is flex column
        pageEl.style.flexDirection = 'column';

        // Capture existing monitoring content (events + coding jobs)
        const existingContent = monDiv.innerHTML;

        // Build tab bar
        let tabsHtml = '<div class="page-tabs">';
        for (const t of TABS) {
            tabsHtml += `<button class="page-tab" data-subtab="${t.id}" onclick="switchPageTab('monitoring','${t.id}')">${t.label}</button>`;
        }
        tabsHtml += '</div>';

        // Build panels
        // Events panel wraps existing content
        let panelsHtml = '';
        panelsHtml += `<div class="page-panel" id="subtab-monitoring-events">${existingContent}</div>`;
        panelsHtml += `<div class="page-panel" id="subtab-monitoring-audit" style="display:none;overflow-y:auto;"></div>`;
        panelsHtml += `<div class="page-panel" id="subtab-monitoring-usage" style="display:none;overflow-y:auto;"></div>`;
        panelsHtml += `<div class="page-panel" id="subtab-monitoring-metrics" style="display:none;overflow-y:auto;"></div>`;
        panelsHtml += `<div class="page-panel" id="subtab-monitoring-approvals" style="display:none;overflow-y:auto;"></div>`;

        // Restructure the .monitoring div: flex column, no extra padding override needed
        monDiv.style.padding = '0';
        monDiv.style.overflow = 'hidden';
        monDiv.innerHTML = tabsHtml + panelsHtml;

        // Restore last active tab
        let saved = 'events';
        try { saved = localStorage.getItem(STORAGE_KEY) || 'events'; } catch (e) {}
        switchPageTab('monitoring', saved);
        _loadMonitoringTab(saved);
    };

    // ── Hook switchPageTab ───────────────────────────────────────────────

    (function () {
        const _orig = window.switchPageTab;
        window.switchPageTab = function (pageId, tabName) {
            if (typeof _orig === 'function') _orig(pageId, tabName);
            if (pageId === 'monitoring') {
                _loadMonitoringTab(tabName);
            }
        };
    })();

    function _loadMonitoringTab(tab) {
        switch (tab) {
            case 'events':
                if (typeof loadEvents === 'function') loadEvents();
                break;
            case 'audit':
                loadAudit();
                break;
            case 'usage':
                loadUsage();
                break;
            case 'metrics':
                loadMetrics();
                break;
            case 'approvals':
                loadApprovals();
                break;
        }
    }

    // ── Audit Log ────────────────────────────────────────────────────────

    async function loadAudit() {
        const panel = document.getElementById('subtab-monitoring-audit');
        if (!panel) return;
        panel.innerHTML = '<div style="color:#94a3b8;font-size:13px;padding:20px;">Loading...</div>';

        let data = {};
        try {
            data = await apiFetch('/api/audit');
        } catch (err) {
            panel.innerHTML = `<div style="color:#fca5a5;padding:20px;">${esc(err.message)}</div>`;
            return;
        }

        const entries = data.entries || [];
        if (entries.length === 0) {
            panel.innerHTML = '<div class="no-data" style="text-align:center;color:#64748b;padding:40px;font-size:14px;">No audit log entries.</div>';
            return;
        }

        let html = '<div style="display:flex;flex-direction:column;gap:8px;">';
        entries.forEach(function (e) {
            const action = esc(e.action || e.tool_name || JSON.stringify(e));
            const user = e.user ? ' by ' + esc(e.user) : '';
            const time = e.timestamp ? new Date(e.timestamp).toLocaleString() : '';
            html += `<div class="wh-card" style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;gap:16px;">
                <span style="font-size:13px;color:#cbd5e1;">${action}${user}</span>
                <span style="font-size:11px;color:#64748b;white-space:nowrap;">${time}</span>
            </div>`;
        });
        html += '</div>';
        panel.innerHTML = html;
    }

    // ── Usage ────────────────────────────────────────────────────────────

    async function loadUsage() {
        const panel = document.getElementById('subtab-monitoring-usage');
        if (!panel) return;
        panel.innerHTML = '<div style="color:#94a3b8;font-size:13px;padding:20px;">Loading...</div>';

        let data = {};
        try {
            data = await apiFetch('/api/usage');
        } catch (err) {
            panel.innerHTML = `<div style="color:#fca5a5;padding:20px;">${esc(err.message)}</div>`;
            return;
        }

        const u = data.usage || {};
        if (Object.keys(u).length === 0) {
            panel.innerHTML = '<div class="no-data" style="text-align:center;color:#64748b;padding:40px;font-size:14px;">No usage data available.</div>';
            return;
        }

        let html = '<div class="usage-grid" style="display:flex;flex-wrap:wrap;gap:12px;">';
        if (u.input_tokens !== undefined) {
            html += usageCard('Input Tokens', u.input_tokens.toLocaleString());
        }
        if (u.output_tokens !== undefined) {
            html += usageCard('Output Tokens', u.output_tokens.toLocaleString());
        }
        if (u.cache_tokens !== undefined) {
            html += usageCard('Cache Tokens', u.cache_tokens.toLocaleString());
        }
        if (u.total_cost !== undefined) {
            html += usageCard('Total Cost', '$' + u.total_cost.toFixed(4));
        }
        html += '</div>';
        panel.innerHTML = html;
    }

    function usageCard(label, value) {
        return `<div class="wh-card" style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:16px 20px;min-width:140px;">
            <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;">${esc(label)}</div>
            <div style="font-size:24px;font-weight:600;margin-top:6px;color:#e2e8f0;">${esc(value)}</div>
        </div>`;
    }

    // ── Tool Metrics ─────────────────────────────────────────────────────

    async function loadMetrics() {
        const panel = document.getElementById('subtab-monitoring-metrics');
        if (!panel) return;
        panel.innerHTML = '<div style="color:#94a3b8;font-size:13px;padding:20px;">Loading...</div>';

        let data = {};
        try {
            data = await apiFetch('/api/metrics');
        } catch (err) {
            panel.innerHTML = `<div style="color:#fca5a5;padding:20px;">${esc(err.message)}</div>`;
            return;
        }

        const m = data.metrics || {};
        const toolEntries = Object.entries(m);
        if (toolEntries.length === 0) {
            panel.innerHTML = '<div class="no-data" style="text-align:center;color:#64748b;padding:40px;font-size:14px;">No tool metrics available.</div>';
            return;
        }

        const sorted = toolEntries
            .sort(function (a, b) { return (b[1].call_count || 0) - (a[1].call_count || 0); })
            .slice(0, 20);

        let html = '<div style="overflow-x:auto;">';
        html += '<table class="metrics-table" style="width:100%;border-collapse:collapse;font-size:13px;">';
        html += '<thead><tr style="background:#1e293b;color:#94a3b8;text-align:left;">';
        html += '<th style="padding:10px 14px;border-bottom:1px solid #334155;">Tool</th>';
        html += '<th style="padding:10px 14px;border-bottom:1px solid #334155;">Calls</th>';
        html += '<th style="padding:10px 14px;border-bottom:1px solid #334155;">Success %</th>';
        html += '<th style="padding:10px 14px;border-bottom:1px solid #334155;">Avg Time</th>';
        html += '</tr></thead><tbody>';

        sorted.forEach(function ([name, d]) {
            const rate = d.call_count > 0 ? ((d.success_count || 0) / d.call_count * 100) : 0;
            const rateColor = rate >= 90 ? '#86efac' : rate >= 70 ? '#fde68a' : '#fca5a5';
            const avgTime = d.avg_duration_ms !== undefined ? d.avg_duration_ms.toFixed(0) + 'ms' : '-';
            html += `<tr style="border-bottom:1px solid #1e293b;">
                <td style="padding:10px 14px;color:#cbd5e1;">${esc(name)}</td>
                <td style="padding:10px 14px;color:#94a3b8;">${d.call_count || 0}</td>
                <td style="padding:10px 14px;color:${rateColor};font-weight:600;">${rate.toFixed(0)}%</td>
                <td style="padding:10px 14px;color:#94a3b8;">${esc(avgTime)}</td>
            </tr>`;
        });

        html += '</tbody></table></div>';
        panel.innerHTML = html;
    }

    // ── Approvals ────────────────────────────────────────────────────────

    async function loadApprovals() {
        const panel = document.getElementById('subtab-monitoring-approvals');
        if (!panel) return;
        panel.innerHTML = '<div style="color:#94a3b8;font-size:13px;padding:20px;">Loading...</div>';

        let data = {};
        try {
            data = await apiFetch('/api/approvals');
        } catch (err) {
            panel.innerHTML = `<div style="color:#fca5a5;padding:20px;">${esc(err.message)}</div>`;
            return;
        }

        const apps = data.approvals || [];
        if (apps.length === 0) {
            panel.innerHTML = '<div class="no-data" style="text-align:center;color:#64748b;padding:40px;font-size:14px;">No pending approvals.</div>';
            return;
        }

        let html = '<div style="display:flex;flex-direction:column;gap:8px;">';
        apps.forEach(function (a) {
            const toolName = esc(a.tool_name || a.name || 'Unknown');
            const detail = a.arguments ? esc(JSON.stringify(a.arguments)) : esc(a.detail || '');
            html += `<div class="wh-card approval-card" style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:14px 16px;display:flex;justify-content:space-between;align-items:center;gap:16px;">
                <div>
                    <div style="font-size:14px;font-weight:600;color:#e2e8f0;margin-bottom:4px;">${toolName}</div>
                    <div style="font-size:12px;color:#94a3b8;word-break:break-all;">${detail}</div>
                </div>
                <div style="display:flex;gap:8px;flex-shrink:0;">
                    <button class="wh-btn" onclick="approveMonItem('${esc(a.id)}')" style="padding:6px 16px;background:#16a34a;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;">Approve</button>
                    <button class="wh-btn" onclick="denyMonItem('${esc(a.id)}')" style="padding:6px 16px;background:#dc2626;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;">Deny</button>
                </div>
            </div>`;
        });
        html += '</div>';
        panel.innerHTML = html;
    }

    // ── Window-exposed approval actions ──────────────────────────────────

    window.approveMonItem = async function (id) {
        try {
            await apiFetch(`/api/approvals/${id}/approve`, { method: 'POST' });
            toast('Approved', 'success');
            loadApprovals();
        } catch (err) {
            toast(err.message || 'Failed to approve', 'error');
        }
    };

    window.denyMonItem = async function (id) {
        try {
            await apiFetch(`/api/approvals/${id}/deny`, { method: 'POST' });
            toast('Denied', 'success');
            loadApprovals();
        } catch (err) {
            toast(err.message || 'Failed to deny', 'error');
        }
    };

})();
