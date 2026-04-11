// src/breadmind/web/static/js/connections.js
/**
 * Connections page — Integrations and Messenger sub-tabs
 */
(function() {
    'use strict';

    const PTAB_KEY = 'breadmind_ptab_connections';

    // ── Messenger helpers ──────────────────────────────────────────────────

    async function loadMessengerPanel() {
        const container = document.getElementById('messenger-connections-content');
        if (!container) return;
        container.innerHTML = '<div class="no-data">Loading messenger platforms...</div>';
        try {
            const resp = await fetch('/api/messenger/platforms');
            const data = await resp.json();
            const platforms = data.platforms || {};
            if (!Object.keys(platforms).length) {
                container.innerHTML = '<div class="no-data">No messenger platforms available.</div>';
                return;
            }
            const cards = Object.entries(platforms).map(([name, info]) => {
                const connected = info.connected || false;
                const icon = info.icon || '💬';
                const label = name.charAt(0).toUpperCase() + name.slice(1);
                const badge = connected
                    ? '<span class="wh-badge wh-badge-success">Connected</span>'
                    : '<span class="wh-badge wh-badge-muted">Disconnected</span>';
                const btn = connected
                    ? `<button class="wh-btn wh-btn-danger wh-btn-sm" onclick="disconnectMessenger('${name}')">Disconnect</button>`
                    : `<button class="wh-btn wh-btn-primary wh-btn-sm" onclick="connectMessenger('${name}')">Connect</button>`;
                return `
                    <div class="wh-card messenger-platform-card">
                        <div class="messenger-platform-icon">${icon}</div>
                        <div class="messenger-platform-info">
                            <div class="messenger-platform-name">${label}</div>
                            ${badge}
                        </div>
                        <div class="messenger-platform-action">${btn}</div>
                    </div>`;
            }).join('');
            container.innerHTML = `<div class="messenger-platforms-grid">${cards}</div>`;
        } catch (err) {
            container.innerHTML = '<div class="no-data">Failed to load messenger platforms.</div>';
        }
    }

    window.connectMessenger = async function(platform) {
        try {
            const resp = await fetch(`/api/messenger/wizard/start/${platform}`, { method: 'POST' });
            const data = await resp.json();
            showToast(data.message || `${platform} connection wizard started`, 'info');
            setTimeout(loadMessengerPanel, 1500);
        } catch (err) {
            showToast(`Failed to start ${platform} wizard`, 'error');
        }
    };

    window.disconnectMessenger = async function(platform) {
        const label = platform.charAt(0).toUpperCase() + platform.slice(1);
        if (!confirm(`Disconnect ${label}? This will stop all messages from this platform.`)) return;
        try {
            const resp = await fetch(`/api/messenger/disconnect/${platform}`, { method: 'POST' });
            const data = await resp.json();
            showToast(data.message || `${label} disconnected`, 'success');
            setTimeout(loadMessengerPanel, 500);
        } catch (err) {
            showToast(`Failed to disconnect ${platform}`, 'error');
        }
    };

    // ── Sub-tab switching ──────────────────────────────────────────────────

    function switchConnectionsTab(tabName) {
        localStorage.setItem(PTAB_KEY, tabName);
        document.querySelectorAll('#connections-content .page-tab').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.subtab === tabName);
        });
        document.querySelectorAll('#connections-content .connections-panel').forEach(panel => {
            panel.style.display = panel.id === `subtab-connections-${tabName}` ? '' : 'none';
        });
        if (tabName === 'messenger') {
            loadMessengerPanel();
        }
    }

    // ── Page initialiser ───────────────────────────────────────────────────

    window.initConnectionsPage = function() {
        const root = document.getElementById('connections-content');
        if (!root) return;

        const savedTab = localStorage.getItem(PTAB_KEY) || 'integrations';

        // Make container a flex column so panels stretch
        root.style.display = 'flex';
        root.style.flexDirection = 'column';
        root.style.flex = '1';
        root.style.overflow = 'hidden';

        root.innerHTML = `
            <div class="page-tabs">
                <button class="page-tab" data-subtab="integrations" onclick="switchConnectionsTab('integrations')">Integrations</button>
                <button class="page-tab" data-subtab="messenger" onclick="switchConnectionsTab('messenger')">Messenger</button>
            </div>

            <div class="connections-panel page-panel" id="subtab-connections-integrations">
                <div id="integrations-content"></div>
            </div>

            <div class="connections-panel page-panel" id="subtab-connections-messenger" style="display:none;">
                <div id="messenger-connections-content"></div>
            </div>`;

        // Activate saved tab
        switchConnectionsTab(savedTab);

        // Init integrations if that tab is active
        if (savedTab === 'integrations' && typeof initIntegrationsTab === 'function') {
            initIntegrationsTab();
        }
    };

    // ── Hook switchPageTab ─────────────────────────────────────────────────

    (function() {
        var _orig = window.switchPageTab;
        window.switchPageTab = function(pageId, tabName) {
            if (typeof _orig === 'function') _orig(pageId, tabName);
            if (pageId === 'connections') {
                window.initConnectionsPage();
            }
        };
    })();

})();
