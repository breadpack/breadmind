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

    // Featured categories with plugin recommendations
    const PLUGIN_CATEGORIES = [
        { name: 'Coding Agents', icon: '💻', description: 'AI 코딩 어시스턴트 연동' },
        { name: 'Infrastructure', icon: '🏗️', description: '인프라 관리 도구 확장' },
        { name: 'Monitoring', icon: '📊', description: '모니터링 및 알림' },
        { name: 'Security', icon: '🔒', description: '보안 도구 및 스캐너' },
        { name: 'DevOps', icon: '🚀', description: 'CI/CD 및 배포' },
        { name: 'Communication', icon: '💬', description: '메신저 및 알림 확장' },
        { name: 'Storage', icon: '📁', description: '파일 및 데이터 관리' },
        { name: 'AI & LLM', icon: '🤖', description: 'AI 모델 및 도구' },
    ];

    window.loadPluginsFeatured = async function() {
        const container = document.getElementById('plugin-categories');
        if (!container) return;

        // Load installed plugins
        let installed = [];
        try {
            const data = await fetchJSON('/api/plugins');
            installed = data.plugins || [];
        } catch(e) { /* ignore */ }

        // Load marketplace
        let featured = [];
        try {
            const data = await fetchJSON('/api/marketplace/search?q=');
            featured = data.results || [];
        } catch(e) { /* ignore */ }

        // Build category buttons
        let html = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px;">';
        for (const cat of PLUGIN_CATEGORIES) {
            html += `<button class="cat-btn" onclick="filterPluginCategory('${cat.name}')" data-pcat="${cat.name}">${cat.icon} ${cat.name}</button>`;
        }
        html += '</div>';

        // Show installed as "Recommended" if any
        if (installed.length > 0) {
            html += `<div class="cat-section" data-pcat="Installed">`;
            html += `<h3 style="color:#e2e8f0;font-size:14px;margin-bottom:8px;">✅ 설치됨 (${installed.length})</h3>`;
            html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;">';
            for (const p of installed) {
                const statusDot = p.enabled ? '🟢' : '⚪';
                html += `<div class="server-card" onclick="showPluginDetail('${p.name}','installed')" style="cursor:pointer;">
                    <div class="server-name">${statusDot} ${p.name}</div>
                    <div class="server-desc">${p.description || ''}</div>
                    <div class="server-meta"><span class="server-source">v${p.version || '?'}</span></div>
                </div>`;
            }
            html += '</div></div>';
        }

        // Show featured/marketplace by category
        if (featured.length > 0) {
            // Group by tags
            const grouped = {};
            for (const cat of PLUGIN_CATEGORIES) {
                grouped[cat.name] = [];
            }
            for (const p of featured) {
                const tags = p.tags || [];
                let matched = false;
                for (const cat of PLUGIN_CATEGORIES) {
                    const catLower = cat.name.toLowerCase();
                    if (tags.some(t => t.toLowerCase().includes(catLower)) ||
                        (p.type || '').toLowerCase().includes(catLower) ||
                        (p.description || '').toLowerCase().includes(catLower)) {
                        grouped[cat.name].push(p);
                        matched = true;
                    }
                }
                if (!matched && grouped['Infrastructure']) {
                    grouped['Infrastructure'].push(p);
                }
            }

            for (const cat of PLUGIN_CATEGORIES) {
                const plugins = grouped[cat.name];
                if (plugins && plugins.length > 0) {
                    html += `<div class="cat-section" data-pcat="${cat.name}">`;
                    html += `<h3 style="color:#e2e8f0;font-size:14px;margin-bottom:8px;">${cat.icon} ${cat.name}</h3>`;
                    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;">';
                    for (const p of plugins.slice(0, 4)) {
                        html += `<div class="server-card" onclick="showPluginDetail('${p.name}','marketplace')" style="cursor:pointer;">
                            <div class="server-name">${p.name}</div>
                            <div class="server-desc">${(p.description || '').slice(0, 100)}</div>
                            <div class="server-meta">
                                <span class="server-source">${p.author || 'community'}</span>
                                ${p.stars ? `<span style="color:#fbbf24;font-size:11px;">★${p.stars}</span>` : ''}
                            </div>
                        </div>`;
                    }
                    html += '</div></div>';
                }
            }
        }

        if (!installed.length && !featured.length) {
            html += `<div style="text-align:center;padding:40px;color:#64748b;">
                <p style="font-size:16px;margin-bottom:8px;">📦 플러그인이 없습니다</p>
                <p style="font-size:13px;">검색하거나 로컬/Git URL로 설치하세요.</p>
            </div>`;
        }

        container.innerHTML = html;
    };

    window.loadPluginsInstalled = async function() {
        const container = document.getElementById('plugin-installed');
        if (!container) return;
        try {
            const data = await fetchJSON('/api/plugins');
            const plugins = data.plugins || [];
            if (plugins.length === 0) {
                container.innerHTML = '<p style="color:#64748b;text-align:center;padding:20px;">설치된 플러그인이 없습니다.</p>';
                return;
            }
            let html = '';
            for (const p of plugins) {
                const statusDot = p.enabled ? '🟢' : '⚪';
                html += `<div class="server-card" onclick="showPluginDetail('${p.name}','installed')" style="cursor:pointer;margin-bottom:8px;">
                    <div class="server-name">${statusDot} ${p.name} <span style="color:#64748b;font-size:11px;">v${p.version || '?'}</span></div>
                    <div class="server-desc">${p.description || ''}</div>
                    ${p.author ? `<div style="font-size:11px;color:#64748b;margin-top:4px;">by ${p.author}</div>` : ''}
                </div>`;
            }
            container.innerHTML = html;
        } catch(e) {
            container.innerHTML = '<p style="color:#f87171;">로드 실패: ' + e.message + '</p>';
        }
    };

    window.pluginToggle = function(view, btn) {
        document.querySelectorAll('#tab-plugins .store-toggle button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('plugin-categories').style.display = view === 'browse' ? '' : 'none';
        document.getElementById('plugin-results').style.display = 'none';
        document.getElementById('plugin-installed').style.display = view === 'installed' ? '' : 'none';
        if (view === 'installed') window.loadPluginsInstalled();
    };

    window.filterPluginCategory = function(name) {
        const btns = document.querySelectorAll('#plugin-categories .cat-btn');
        const sections = document.querySelectorAll('#plugin-categories .cat-section');
        const clicked = document.querySelector(`#plugin-categories .cat-btn[data-pcat="${name}"]`);

        if (clicked && clicked.classList.contains('active')) {
            btns.forEach(b => b.classList.remove('active'));
            sections.forEach(s => s.style.display = '');
        } else {
            btns.forEach(b => b.classList.remove('active'));
            if (clicked) clicked.classList.add('active');
            sections.forEach(s => {
                s.style.display = s.dataset.pcat === name || s.dataset.pcat === 'Installed' ? '' : 'none';
            });
        }
    };

    window.searchPlugins = async function() {
        const input = document.getElementById('plugin-search-input');
        const query = input.value.trim();
        if (!query) {
            document.getElementById('plugin-categories').style.display = '';
            document.getElementById('plugin-results').style.display = 'none';
            return;
        }

        document.getElementById('plugin-categories').style.display = 'none';
        const resultsDiv = document.getElementById('plugin-results');
        resultsDiv.style.display = '';
        resultsDiv.innerHTML = '<p style="color:#64748b;">검색 중...</p>';

        try {
            const data = await fetchJSON(`/api/marketplace/search?q=${encodeURIComponent(query)}`);
            const results = data.results || [];
            if (results.length === 0) {
                resultsDiv.innerHTML = '<p style="color:#64748b;">검색 결과가 없습니다.</p>';
                return;
            }
            let html = '';
            for (const r of results) {
                html += `<div class="server-card" onclick="showPluginDetail('${r.name}','marketplace')" style="cursor:pointer;margin-bottom:8px;">
                    <div class="server-name">${r.name}</div>
                    <div class="server-desc">${(r.description || '').slice(0, 100)}</div>
                    <div class="server-meta">
                        <span class="server-source">${r.author || 'community'}</span>
                        ${r.stars ? `<span style="color:#fbbf24;font-size:11px;">★${r.stars}</span>` : ''}
                    </div>
                </div>`;
            }
            resultsDiv.innerHTML = html;
        } catch(e) {
            resultsDiv.innerHTML = '<p style="color:#f87171;">검색 실패: ' + e.message + '</p>';
        }
    };

    window.showPluginDetail = async function(name, source) {
        const detail = document.getElementById('plugin-detail');
        if (source === 'installed') {
            // Show installed plugin detail
            try {
                const data = await fetchJSON('/api/plugins');
                const plugin = (data.plugins || []).find(p => p.name === name);
                if (!plugin) {
                    detail.innerHTML = '<p style="color:#f87171;">플러그인을 찾을 수 없습니다.</p>';
                    return;
                }
                const statusText = plugin.enabled ? '활성' : '비활성';
                const statusColor = plugin.enabled ? '#34d399' : '#94a3b8';
                detail.innerHTML = `
                    <div style="margin-bottom:16px;">
                        <h3 style="color:#e2e8f0;font-size:18px;margin-bottom:4px;">${plugin.name}</h3>
                        <span style="font-size:12px;padding:2px 8px;border-radius:10px;background:${statusColor}20;color:${statusColor};">${statusText}</span>
                        <span style="font-size:12px;color:#64748b;margin-left:8px;">v${plugin.version || '?'}</span>
                    </div>
                    <p style="color:#94a3b8;font-size:13px;margin-bottom:16px;">${plugin.description || 'No description'}</p>
                    ${plugin.author ? `<p style="color:#64748b;font-size:12px;margin-bottom:16px;">by ${plugin.author}</p>` : ''}
                    <div style="display:flex;gap:8px;">
                        <button onclick="window._togglePluginFromStore('${name}', ${!plugin.enabled})"
                            style="padding:8px 16px;background:#3b82f6;border:none;border-radius:8px;color:white;cursor:pointer;font-size:13px;">
                            ${plugin.enabled ? '비활성화' : '활성화'}
                        </button>
                        <button onclick="window._uninstallPluginFromStore('${name}')"
                            style="padding:8px 16px;background:#450a0a;border:1px solid #7f1d1d;border-radius:8px;color:#fca5a5;cursor:pointer;font-size:13px;">
                            삭제
                        </button>
                    </div>
                `;
            } catch(e) {
                detail.innerHTML = '<p style="color:#f87171;">로드 실패: ' + e.message + '</p>';
            }
        } else {
            // Show marketplace plugin detail
            try {
                const data = await fetchJSON(`/api/marketplace/search?q=${encodeURIComponent(name)}`);
                const plugin = (data.results || []).find(p => p.name === name);
                if (!plugin) {
                    detail.innerHTML = '<p style="color:#64748b;">상세 정보를 찾을 수 없습니다.</p>';
                    return;
                }
                const tags = (plugin.tags || []).map(t =>
                    `<span style="font-size:10px;padding:2px 6px;border-radius:8px;background:#1e293b;color:#60a5fa;">${t}</span>`
                ).join(' ');
                detail.innerHTML = `
                    <div style="margin-bottom:16px;">
                        <h3 style="color:#e2e8f0;font-size:18px;margin-bottom:4px;">${plugin.name}</h3>
                        <span style="font-size:12px;color:#64748b;">v${plugin.version || '?'}</span>
                        ${plugin.stars ? `<span style="color:#fbbf24;font-size:12px;margin-left:8px;">★ ${plugin.stars}</span>` : ''}
                        ${plugin.downloads ? `<span style="color:#64748b;font-size:12px;margin-left:8px;">↓ ${plugin.downloads}</span>` : ''}
                    </div>
                    <p style="color:#94a3b8;font-size:13px;margin-bottom:12px;">${plugin.description || 'No description'}</p>
                    <div style="margin-bottom:16px;">${tags}</div>
                    ${plugin.source ? `<p style="color:#64748b;font-size:12px;margin-bottom:16px;">📦 ${plugin.source}</p>` : ''}
                    <div style="display:flex;gap:8px;">
                        <button onclick="window._installPluginFromStore('${plugin.source || plugin.name}')"
                            style="padding:8px 20px;background:#3b82f6;border:none;border-radius:8px;color:white;cursor:pointer;font-size:13px;">
                            설치
                        </button>
                    </div>
                `;
            } catch(e) {
                detail.innerHTML = '<p style="color:#f87171;">로드 실패: ' + e.message + '</p>';
            }
        }
    };

    // Install from store
    window._installPluginFromStore = async function(source) {
        try {
            await fetchJSON('/api/plugins/install', { method: 'POST', body: JSON.stringify({ source }) });
            if (window.showToast) window.showToast('플러그인이 설치되었습니다.', 'success');
            window.loadPluginsFeatured();
        } catch(e) {
            if (window.showToast) window.showToast('설치 실패: ' + e.message, 'error');
        }
    };

    // Install from local/git input
    window._installPluginManual = async function() {
        const input = document.getElementById('plugin-manual-install');
        const source = input ? input.value.trim() : '';
        if (!source) return;
        try {
            await fetchJSON('/api/plugins/install', { method: 'POST', body: JSON.stringify({ source }) });
            if (window.showToast) window.showToast('플러그인이 설치되었습니다.', 'success');
            input.value = '';
            window.loadPluginsFeatured();
        } catch(e) {
            if (window.showToast) window.showToast('설치 실패: ' + e.message, 'error');
        }
    };

    // Toggle enable/disable
    window._togglePluginFromStore = async function(name, enable) {
        try {
            const action = enable ? 'enable' : 'disable';
            await fetchJSON(`/api/plugins/${encodeURIComponent(name)}/${action}`, { method: 'POST' });
            if (window.showToast) window.showToast(`${name} ${enable ? '활성화' : '비활성화'}됨`, 'success');
            window.loadPluginsFeatured();
            window.showPluginDetail(name, 'installed');
        } catch(e) {
            if (window.showToast) window.showToast('변경 실패: ' + e.message, 'error');
        }
    };

    // Uninstall
    window._uninstallPluginFromStore = async function(name) {
        if (!confirm(`"${name}" 플러그인을 삭제하시겠습니까?`)) return;
        try {
            await fetchJSON(`/api/plugins/${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (window.showToast) window.showToast(`${name} 삭제됨`, 'success');
            document.getElementById('plugin-detail').innerHTML = '<p style="color:#64748b;">플러그인을 선택하면 상세 정보가 표시됩니다.</p>';
            window.loadPluginsFeatured();
        } catch(e) {
            if (window.showToast) window.showToast('삭제 실패: ' + e.message, 'error');
        }
    };

    // Alias for legacy references
    window.initPluginsTab = window.loadPluginsFeatured;
})();
