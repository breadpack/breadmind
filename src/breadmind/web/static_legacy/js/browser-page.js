(function() {
    'use strict';

    const PTAB_KEY = 'breadmind_ptab_browser';
    let _liveWs = null;
    let _streaming = false;

    function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

    function authHeaders() {
        const h = { 'Content-Type': 'application/json' };
        const m = document.cookie.match(/session_token=([^;]+)/);
        if (m) h['Authorization'] = 'Bearer ' + m[1];
        return h;
    }

    async function apiFetch(url, opts) {
        opts = opts || {};
        const headers = Object.assign(authHeaders(), opts.headers || {});
        const resp = await fetch(url, Object.assign({}, opts, { headers: headers }));
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json().catch(function() { return {}; });
    }

    // ── Sessions Tab ──────────────────────────────────────────────────────

    async function loadSessions() {
        var panel = document.getElementById('subtab-browser-sessions');
        if (!panel) return;
        panel.innerHTML = '<div class="browser-empty"><div class="browser-empty-icon">⏳</div>Loading sessions...</div>';
        try {
            var data = await apiFetch('/api/browser/sessions');
            var sessions = data.sessions || [];
            if (!sessions.length) {
                panel.innerHTML =
                    '<div class="browser-empty">' +
                    '<div class="browser-empty-icon">🌐</div>' +
                    '<div>No active browser sessions</div>' +
                    '<div style="font-size:12px;color:var(--text-tertiary)">Use browser tools in chat to start a session</div>' +
                    '</div>';
                loadMacros(panel);
                return;
            }
            var html = '<div style="padding:4px"><h3 style="margin:0 0 12px;font-size:14px;color:var(--text-secondary)">Active Sessions</h3>';
            html += '<div class="browser-grid">';
            sessions.forEach(function(s) {
                var badge = s.persistent
                    ? '<span class="browser-session-badge persistent">Persistent</span>'
                    : '<span class="browser-session-badge transient">Transient</span>';
                html += '<div class="browser-session-card">' +
                    '<div class="browser-session-header">' +
                    '<span class="browser-session-name">' + esc(s.name) + '</span>' + badge +
                    '</div>' +
                    '<div class="browser-session-meta">' +
                    '<span>ID: ' + esc(s.id) + '</span>' +
                    '<span>Mode: ' + esc(s.mode) + ' | Tabs: ' + (s.tab_count || 0) + '</span>' +
                    '</div>' +
                    '<div class="browser-session-actions">' +
                    '<button class="browser-btn primary" onclick="browserLiveView(\'' + esc(s.id) + '\')">Live View</button>' +
                    '<button class="browser-btn danger" onclick="browserCloseSession(\'' + esc(s.id) + '\')">Close</button>' +
                    '</div></div>';
            });
            html += '</div></div>';
            panel.innerHTML = html;
            loadMacros(panel);
        } catch (err) {
            panel.innerHTML = '<div class="browser-empty"><div class="browser-empty-icon">⚠️</div>Failed to load sessions: ' + esc(err.message) + '</div>';
        }
    }

    async function loadMacros(panel) {
        try {
            var data = await apiFetch('/api/browser/macros');
            var macros = data.macros || [];
            if (!macros.length) return;
            var html = '<div style="padding:4px;margin-top:20px"><h3 style="margin:0 0 12px;font-size:14px;color:var(--text-secondary)">Saved Macros</h3>';
            html += '<div style="display:flex;flex-direction:column;gap:8px">';
            macros.forEach(function(m) {
                html += '<div class="browser-macro-card">' +
                    '<div class="browser-macro-info">' +
                    '<div class="browser-macro-name">' + esc(m.name) + '</div>' +
                    '<div class="browser-macro-meta">' + m.steps.length + ' steps | runs: ' + (m.execution_count || 0) + '</div>' +
                    '</div>' +
                    '<button class="browser-btn primary" onclick="browserRunMacro(\'' + esc(m.id) + '\')">Run</button>' +
                    '</div>';
            });
            html += '</div></div>';
            panel.innerHTML += html;
        } catch (err) { /* ignore */ }
    }

    // ── Live View Tab ─────────────────────────────────────────────────────

    function initLiveView() {
        var panel = document.getElementById('subtab-browser-live');
        if (!panel) return;
        panel.innerHTML =
            '<div class="browser-live-container">' +
            '<div class="browser-live-toolbar">' +
            '<select id="browser-live-session"><option value="">Select session...</option></select>' +
            '<label style="font-size:12px;color:var(--text-secondary)">FPS:</label>' +
            '<input type="number" id="browser-live-fps" value="2" min="1" max="5" style="width:50px">' +
            '<button class="browser-btn primary" id="browser-live-start" onclick="browserStartLive()">Start</button>' +
            '<button class="browser-btn" id="browser-live-stop" onclick="browserStopLive()" style="display:none">Stop</button>' +
            '<div class="browser-live-status"><span class="browser-live-dot" id="browser-live-dot"></span><span id="browser-live-status-text">Idle</span></div>' +
            '</div>' +
            '<div class="browser-live-viewport" id="browser-live-viewport">' +
            '<div class="browser-empty"><div class="browser-empty-icon">📺</div><div>Select a session and click Start</div></div>' +
            '</div></div>';
        refreshSessionSelect();
    }

    async function refreshSessionSelect() {
        var sel = document.getElementById('browser-live-session');
        if (!sel) return;
        try {
            var data = await apiFetch('/api/browser/sessions');
            var sessions = data.sessions || [];
            var html = '<option value="">Select session...</option>';
            sessions.forEach(function(s) {
                html += '<option value="' + esc(s.id) + '">' + esc(s.name) + ' (' + esc(s.id) + ')</option>';
            });
            sel.innerHTML = html;
        } catch (err) { /* ignore */ }
    }

    // ── WebSocket Live View ───────────────────────────────────────────────

    window.browserStartLive = function() {
        var sessionId = document.getElementById('browser-live-session').value;
        if (!sessionId) { if (typeof showToast === 'function') showToast('Select a session first', 'error'); return; }
        var fps = parseInt(document.getElementById('browser-live-fps').value) || 2;

        var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        _liveWs = new WebSocket(proto + '//' + location.host + '/ws/browser/live');

        _liveWs.onopen = function() {
            _liveWs.send(JSON.stringify({ type: 'start', session_id: sessionId, fps: fps }));
            _streaming = true;
            document.getElementById('browser-live-start').style.display = 'none';
            document.getElementById('browser-live-stop').style.display = '';
            document.getElementById('browser-live-dot').classList.add('active');
            document.getElementById('browser-live-status-text').textContent = 'Streaming';
        };

        _liveWs.onmessage = function(ev) {
            var msg = JSON.parse(ev.data);
            if (msg.type === 'frame') {
                var viewport = document.getElementById('browser-live-viewport');
                var img = viewport.querySelector('img');
                if (!img) {
                    viewport.innerHTML = '';
                    img = document.createElement('img');
                    viewport.appendChild(img);
                }
                img.src = 'data:image/png;base64,' + msg.data;
            } else if (msg.type === 'error') {
                if (typeof showToast === 'function') showToast(msg.message, 'error');
            }
        };

        _liveWs.onclose = function() {
            _streaming = false;
            document.getElementById('browser-live-start').style.display = '';
            document.getElementById('browser-live-stop').style.display = 'none';
            document.getElementById('browser-live-dot').classList.remove('active');
            document.getElementById('browser-live-status-text').textContent = 'Disconnected';
        };
    };

    window.browserStopLive = function() {
        if (_liveWs && _liveWs.readyState === WebSocket.OPEN) {
            _liveWs.send(JSON.stringify({ type: 'stop' }));
            _liveWs.close();
        }
        _streaming = false;
    };

    // ── Actions ───────────────────────────────────────────────────────────

    window.browserCloseSession = async function(sessionId) {
        if (!confirm('Close this browser session?')) return;
        try {
            await apiFetch('/api/browser/sessions/' + sessionId, { method: 'DELETE' });
            if (typeof showToast === 'function') showToast('Session closed', 'success');
            loadSessions();
        } catch (err) {
            if (typeof showToast === 'function') showToast('Failed to close session', 'error');
        }
    };

    window.browserLiveView = function(sessionId) {
        switchPageTab('browser', 'live');
        setTimeout(function() {
            var sel = document.getElementById('browser-live-session');
            if (sel) sel.value = sessionId;
        }, 100);
    };

    window.browserRunMacro = async function(macroId) {
        try {
            if (typeof showToast === 'function') showToast('Executing macro...', 'info');
            var data = await apiFetch('/api/browser/macros/' + macroId + '/execute', { method: 'POST' });
            if (typeof showToast === 'function') showToast('Macro executed', 'success');
        } catch (err) {
            if (typeof showToast === 'function') showToast('Macro execution failed', 'error');
        }
    };

    // ── Sub-tab switching ─────────────────────────────────────────────────

    window.switchBrowserTab = function(tabName) {
        localStorage.setItem(PTAB_KEY, tabName);
        var pageEl = document.getElementById('page-browser');
        if (!pageEl) return;
        pageEl.querySelectorAll('.page-tab').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.subtab === tabName);
        });
        pageEl.querySelectorAll('.page-panel').forEach(function(panel) {
            panel.style.display = panel.id === 'subtab-browser-' + tabName ? '' : 'none';
        });
        if (tabName === 'sessions') loadSessions();
        if (tabName === 'live') initLiveView();
    };

    // ── Page initializer ──────────────────────────────────────────────────

    window.initBrowserPage = function() {
        var savedTab = localStorage.getItem(PTAB_KEY) || 'sessions';
        switchBrowserTab(savedTab);
    };

})();
