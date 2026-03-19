// Plugins tab for BreadMind Settings
(function() {
    'use strict';

    async function fetchJSON(url, opts = {}) {
        const headers = { 'Content-Type': 'application/json' };
        const token = document.cookie.match(/session_token=([^;]+)/)?.[1];
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const resp = await fetch(url, { ...opts, headers: { ...headers, ...opts.headers } });
        if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
        return resp.json();
    }

    async function loadPlugins() {
        try {
            const data = await fetchJSON('/api/plugins');
            return data.plugins || [];
        } catch (e) {
            console.error('Failed to load plugins:', e);
            return [];
        }
    }

    async function searchMarketplace(query) {
        try {
            const data = await fetchJSON(`/api/marketplace/search?q=${encodeURIComponent(query)}`);
            return data.results || [];
        } catch (e) {
            console.error('Marketplace search failed:', e);
            return [];
        }
    }

    async function installPlugin(source) {
        return fetchJSON('/api/plugins/install', {
            method: 'POST',
            body: JSON.stringify({ source }),
        });
    }

    async function installFromMarketplace(name) {
        return fetchJSON(`/api/marketplace/install/${encodeURIComponent(name)}`, {
            method: 'POST',
        });
    }

    async function togglePlugin(name, enable) {
        const action = enable ? 'enable' : 'disable';
        return fetchJSON(`/api/plugins/${encodeURIComponent(name)}/${action}`, {
            method: 'POST',
        });
    }

    async function uninstallPlugin(name) {
        return fetchJSON(`/api/plugins/${encodeURIComponent(name)}`, {
            method: 'DELETE',
        });
    }

    function buildPluginsHTML(plugins, marketResults) {
        let html = '';

        // Install section
        html += `
        <div class="settings-section">
            <h3>📦 플러그인 설치</h3>
            <p style="color:var(--text-secondary);font-size:13px;margin-bottom:12px;">
                로컬 경로, Git URL, 또는 Claude Code 플러그인 디렉토리에서 설치할 수 있습니다.
            </p>
            <div style="display:flex;gap:8px;">
                <input type="text" id="plugin-install-source" placeholder="경로, Git URL, 또는 플러그인 이름..."
                    style="flex:1;padding:8px 12px;background:var(--glass-bg);border:1px solid var(--glass-border);border-radius:8px;color:var(--text-primary);font-size:13px;">
                <button onclick="window._installPlugin()"
                    style="padding:8px 16px;background:var(--accent);border:none;border-radius:8px;color:white;cursor:pointer;font-size:13px;white-space:nowrap;">
                    설치
                </button>
            </div>
        </div>`;

        // Installed plugins
        html += `
        <div class="settings-section">
            <h3>설치된 플러그인</h3>`;

        if (plugins.length === 0) {
            html += '<p style="color:var(--text-tertiary);font-size:13px;">설치된 플러그인이 없습니다.</p>';
        } else {
            for (const p of plugins) {
                const statusColor = p.enabled ? 'var(--success)' : 'var(--text-tertiary)';
                const statusText = p.enabled ? '활성' : '비활성';
                const toggleText = p.enabled ? '비활성화' : '활성화';
                html += `
                <div style="display:flex;align-items:center;justify-content:space-between;padding:12px;margin-bottom:8px;background:var(--glass-bg);border:1px solid var(--glass-border);border-radius:10px;">
                    <div style="flex:1;">
                        <div style="display:flex;align-items:center;gap:8px;">
                            <span style="font-weight:600;color:var(--text-primary);">${p.name}</span>
                            <span style="font-size:11px;color:var(--text-tertiary);">v${p.version}</span>
                            <span style="font-size:11px;padding:2px 8px;border-radius:10px;background:${statusColor}20;color:${statusColor};">${statusText}</span>
                        </div>
                        <div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">${p.description || ''}</div>
                        ${p.author ? `<div style="font-size:11px;color:var(--text-tertiary);margin-top:2px;">by ${p.author}</div>` : ''}
                    </div>
                    <div style="display:flex;gap:6px;">
                        <button onclick="window._togglePlugin('${p.name}', ${!p.enabled})"
                            style="padding:6px 12px;background:var(--glass-bg-hover);border:1px solid var(--glass-border);border-radius:6px;color:var(--text-primary);cursor:pointer;font-size:12px;">
                            ${toggleText}
                        </button>
                        <button onclick="window._uninstallPlugin('${p.name}')"
                            style="padding:6px 12px;background:rgba(248,113,113,0.1);border:1px solid rgba(248,113,113,0.3);border-radius:6px;color:var(--error);cursor:pointer;font-size:12px;">
                            삭제
                        </button>
                    </div>
                </div>`;
            }
        }
        html += '</div>';

        // Marketplace search
        html += `
        <div class="settings-section">
            <h3>🛒 마켓플레이스</h3>
            <p style="color:var(--text-secondary);font-size:13px;margin-bottom:12px;">
                커뮤니티 플러그인을 검색하고 설치할 수 있습니다.
            </p>
            <div style="display:flex;gap:8px;margin-bottom:12px;">
                <input type="text" id="marketplace-search-input" placeholder="플러그인 검색..."
                    style="flex:1;padding:8px 12px;background:var(--glass-bg);border:1px solid var(--glass-border);border-radius:8px;color:var(--text-primary);font-size:13px;"
                    onkeydown="if(event.key==='Enter')window._searchMarketplace()">
                <button onclick="window._searchMarketplace()"
                    style="padding:8px 16px;background:var(--glass-bg-hover);border:1px solid var(--glass-border);border-radius:8px;color:var(--text-primary);cursor:pointer;font-size:13px;">
                    검색
                </button>
            </div>
            <div id="marketplace-results">
                <p style="color:var(--text-tertiary);font-size:13px;">검색어를 입력하세요.</p>
            </div>
        </div>`;

        return html;
    }

    function buildMarketResultsHTML(results) {
        if (results.length === 0) {
            return '<p style="color:var(--text-tertiary);font-size:13px;">검색 결과가 없습니다.</p>';
        }
        let html = '';
        for (const r of results) {
            const tags = (r.tags || []).map(t =>
                `<span style="font-size:10px;padding:1px 6px;border-radius:8px;background:var(--accent)20;color:var(--accent-light);">${t}</span>`
            ).join(' ');
            html += `
            <div style="display:flex;align-items:center;justify-content:space-between;padding:12px;margin-bottom:8px;background:var(--glass-bg);border:1px solid var(--glass-border);border-radius:10px;">
                <div style="flex:1;">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-weight:600;color:var(--text-primary);">${r.name}</span>
                        <span style="font-size:11px;color:var(--text-tertiary);">v${r.version || '?'}</span>
                    </div>
                    <div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">${r.description || ''}</div>
                    <div style="display:flex;gap:4px;margin-top:4px;">${tags}</div>
                </div>
                <button onclick="window._installFromMarketplace('${r.name}')"
                    style="padding:6px 16px;background:var(--accent);border:none;border-radius:6px;color:white;cursor:pointer;font-size:12px;white-space:nowrap;">
                    설치
                </button>
            </div>`;
        }
        return html;
    }

    // Global functions for onclick handlers
    window._installPlugin = async function() {
        const input = document.getElementById('plugin-install-source');
        const source = input.value.trim();
        if (!source) return;
        try {
            await installPlugin(source);
            input.value = '';
            if (window.showToast) window.showToast('플러그인이 설치되었습니다.', 'success');
            window.initPluginsTab();
        } catch (e) {
            if (window.showToast) window.showToast('설치 실패: ' + e.message, 'error');
        }
    };

    window._togglePlugin = async function(name, enable) {
        try {
            await togglePlugin(name, enable);
            if (window.showToast) window.showToast(`${name} ${enable ? '활성화' : '비활성화'}됨`, 'success');
            window.initPluginsTab();
        } catch (e) {
            if (window.showToast) window.showToast('변경 실패: ' + e.message, 'error');
        }
    };

    window._uninstallPlugin = async function(name) {
        if (!confirm(`"${name}" 플러그인을 삭제하시겠습니까?`)) return;
        try {
            await uninstallPlugin(name);
            if (window.showToast) window.showToast(`${name} 삭제됨`, 'success');
            window.initPluginsTab();
        } catch (e) {
            if (window.showToast) window.showToast('삭제 실패: ' + e.message, 'error');
        }
    };

    window._searchMarketplace = async function() {
        const input = document.getElementById('marketplace-search-input');
        const query = input.value.trim();
        const container = document.getElementById('marketplace-results');
        if (!query) return;
        container.innerHTML = '<p style="color:var(--text-tertiary);font-size:13px;">검색 중...</p>';
        const results = await searchMarketplace(query);
        container.innerHTML = buildMarketResultsHTML(results);
    };

    window._installFromMarketplace = async function(name) {
        try {
            await installFromMarketplace(name);
            if (window.showToast) window.showToast(`${name} 설치됨`, 'success');
            window.initPluginsTab();
        } catch (e) {
            if (window.showToast) window.showToast('설치 실패: ' + e.message, 'error');
        }
    };

    window.initPluginsTab = async function() {
        const container = document.getElementById('settings-plugins');
        if (!container) return;
        container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-tertiary);">로딩 중...</div>';
        const plugins = await loadPlugins();
        container.innerHTML = buildPluginsHTML(plugins, []);
    };
})();
