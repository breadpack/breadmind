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

    // Curated popular plugins (always shown even without marketplace API)
    const POPULAR_PLUGINS = [
        {
            category: 'Coding Agents', icon: '💻',
            plugins: [
                { name: 'aider', description: 'AI pair programming in your terminal', author: 'paul-gauthier', stars: 25000, source: 'https://github.com/breadmind-plugins/aider-adapter', tags: ['coding', 'ai'] },
                { name: 'continue', description: 'Open-source AI code assistant for VS Code and JetBrains', author: 'continuedev', stars: 19000, source: 'https://github.com/breadmind-plugins/continue-adapter', tags: ['coding', 'ide'] },
                { name: 'cursor-rules', description: 'Cursor AI editor rules and templates', author: 'community', stars: 8500, source: 'https://github.com/breadmind-plugins/cursor-rules', tags: ['coding', 'cursor'] },
                { name: 'cline', description: 'Autonomous coding agent for VS Code', author: 'cline', stars: 15000, source: 'https://github.com/breadmind-plugins/cline-adapter', tags: ['coding', 'agent'] },
            ]
        },
        {
            category: 'Infrastructure', icon: '🏗️',
            plugins: [
                { name: 'terraform-helper', description: 'Terraform plan/apply automation with drift detection', author: 'breadmind', stars: 320, source: 'https://github.com/breadmind-plugins/terraform-helper', tags: ['iac', 'terraform'] },
                { name: 'ansible-runner', description: 'Run Ansible playbooks from BreadMind chat', author: 'community', stars: 180, source: 'https://github.com/breadmind-plugins/ansible-runner', tags: ['automation', 'ansible'] },
                { name: 'docker-compose', description: 'Docker Compose stack management and monitoring', author: 'breadmind', stars: 450, source: 'https://github.com/breadmind-plugins/docker-compose', tags: ['docker', 'containers'] },
                { name: 'helm-charts', description: 'Helm chart repository search and deploy', author: 'community', stars: 210, source: 'https://github.com/breadmind-plugins/helm-charts', tags: ['kubernetes', 'helm'] },
            ]
        },
        {
            category: 'Monitoring', icon: '📊',
            plugins: [
                { name: 'grafana-bridge', description: 'Query Grafana dashboards and alerts from chat', author: 'breadmind', stars: 560, source: 'https://github.com/breadmind-plugins/grafana-bridge', tags: ['monitoring', 'grafana'] },
                { name: 'prometheus-query', description: 'PromQL queries and alert management', author: 'community', stars: 340, source: 'https://github.com/breadmind-plugins/prometheus-query', tags: ['monitoring', 'prometheus'] },
                { name: 'uptime-kuma', description: 'Uptime Kuma status monitoring integration', author: 'community', stars: 280, source: 'https://github.com/breadmind-plugins/uptime-kuma', tags: ['monitoring', 'uptime'] },
            ]
        },
        {
            category: 'Security', icon: '🔒',
            plugins: [
                { name: 'trivy-scanner', description: 'Container image vulnerability scanning with Trivy', author: 'breadmind', stars: 420, source: 'https://github.com/breadmind-plugins/trivy-scanner', tags: ['security', 'scanning'] },
                { name: 'cert-manager', description: 'TLS certificate monitoring and renewal alerts', author: 'community', stars: 310, source: 'https://github.com/breadmind-plugins/cert-manager', tags: ['security', 'tls'] },
            ]
        },
        {
            category: 'DevOps', icon: '🚀',
            plugins: [
                { name: 'github-actions', description: 'GitHub Actions workflow management and monitoring', author: 'breadmind', stars: 680, source: 'https://github.com/breadmind-plugins/github-actions', tags: ['ci', 'github'] },
                { name: 'argocd', description: 'ArgoCD GitOps deployment management', author: 'community', stars: 290, source: 'https://github.com/breadmind-plugins/argocd', tags: ['gitops', 'argocd'] },
                { name: 'jenkins-bridge', description: 'Jenkins job triggering and build status', author: 'community', stars: 190, source: 'https://github.com/breadmind-plugins/jenkins-bridge', tags: ['ci', 'jenkins'] },
            ]
        },
        {
            category: 'Communication', icon: '💬',
            plugins: [
                { name: 'webhook-relay', description: 'Forward and transform webhooks between services', author: 'breadmind', stars: 230, source: 'https://github.com/breadmind-plugins/webhook-relay', tags: ['webhook', 'integration'] },
                { name: 'pagerduty', description: 'PagerDuty incident management integration', author: 'community', stars: 170, source: 'https://github.com/breadmind-plugins/pagerduty', tags: ['alerting', 'oncall'] },
            ]
        },
        {
            category: 'AI & LLM', icon: '🤖',
            plugins: [
                { name: 'ollama-models', description: 'Ollama model management and switching', author: 'breadmind', stars: 890, source: 'https://github.com/breadmind-plugins/ollama-models', tags: ['ai', 'ollama', 'local'] },
                { name: 'rag-toolkit', description: 'RAG pipeline tools for document Q&A', author: 'community', stars: 520, source: 'https://github.com/breadmind-plugins/rag-toolkit', tags: ['ai', 'rag'] },
                { name: 'prompt-library', description: 'Curated prompt templates for infrastructure tasks', author: 'breadmind', stars: 340, source: 'https://github.com/breadmind-plugins/prompt-library', tags: ['ai', 'prompts'] },
            ]
        },
    ];

    const PLUGIN_CATEGORIES = POPULAR_PLUGINS.map(c => ({ name: c.category, icon: c.icon }));

    function renderPluginCard(p, source) {
        const starsHtml = p.stars ? `<span style="color:#fbbf24;font-size:11px;">★ ${p.stars >= 1000 ? (p.stars/1000).toFixed(1)+'k' : p.stars}</span>` : '';
        return `<div class="server-card" onclick="showPluginDetail('${p.name}','${source}')" style="cursor:pointer;">
            <div class="server-name">${p.name}</div>
            <div class="server-desc">${(p.description || '').slice(0, 100)}</div>
            <div class="server-meta">
                <span class="server-source">${p.author || 'community'}</span>
                ${starsHtml}
            </div>
        </div>`;
    }

    window.loadPluginsFeatured = async function() {
        const container = document.getElementById('plugin-categories');
        if (!container) return;

        // Hide detail panel
        const detailPanel = document.getElementById('plugin-detail-panel');
        if (detailPanel) detailPanel.style.display = 'none';

        // Load installed plugins
        let installed = [];
        try {
            const data = await fetchJSON('/api/plugins');
            installed = data.plugins || [];
        } catch(e) { /* ignore */ }

        // Load marketplace (merge with curated)
        let marketResults = [];
        try {
            const data = await fetchJSON('/api/marketplace/search?q=');
            marketResults = data.results || [];
        } catch(e) { /* ignore */ }

        // Build category buttons
        let html = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px;">';
        for (const cat of PLUGIN_CATEGORIES) {
            html += `<button class="cat-btn" onclick="filterPluginCategory('${cat.name}')" data-pcat="${cat.name}">${cat.icon} ${cat.name}</button>`;
        }
        html += '</div>';

        // Show installed plugins section
        if (installed.length > 0) {
            html += `<div class="cat-section" data-pcat="Installed">`;
            html += `<h3 style="color:#e2e8f0;font-size:14px;margin-bottom:8px;">✅ 설치됨 (${installed.length})</h3>`;
            html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;max-width:100%;">';
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

        // Show popular/curated plugins by category
        for (const cat of POPULAR_PLUGINS) {
            // Merge marketplace results into curated list (avoid duplicates)
            const curated = [...cat.plugins];
            for (const mr of marketResults) {
                const tags = mr.tags || [];
                const catLower = cat.category.toLowerCase();
                if ((tags.some(t => t.toLowerCase().includes(catLower)) || (mr.type || '').toLowerCase().includes(catLower)) &&
                    !curated.find(c => c.name === mr.name)) {
                    curated.push(mr);
                }
            }

            html += `<div class="cat-section" data-pcat="${cat.category}">`;
            html += `<h3 style="color:#e2e8f0;font-size:14px;margin-bottom:8px;">${cat.icon} ${cat.category}</h3>`;
            html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;max-width:100%;">';
            for (const p of curated.slice(0, 4)) {
                html += renderPluginCard(p, 'popular');
            }
            html += '</div></div>';
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

        // Search curated first
        const queryLower = query.toLowerCase();
        let results = [];
        for (const cat of POPULAR_PLUGINS) {
            for (const p of cat.plugins) {
                if (p.name.toLowerCase().includes(queryLower) || (p.description || '').toLowerCase().includes(queryLower)) {
                    results.push({...p, _category: cat.category});
                }
            }
        }

        // Also search marketplace
        try {
            const data = await fetchJSON(`/api/marketplace/search?q=${encodeURIComponent(query)}`);
            const mr = data.results || [];
            for (const p of mr) {
                if (!results.find(r => r.name === p.name)) {
                    results.push(p);
                }
            }
        } catch(e) { /* ignore */ }

        if (results.length === 0) {
            resultsDiv.innerHTML = '<p style="color:#64748b;">검색 결과가 없습니다.</p>';
            return;
        }
        let html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;max-width:100%;">';
        for (const r of results) {
            html += renderPluginCard(r, 'popular');
        }
        html += '</div>';
        resultsDiv.innerHTML = html;
    };

    window.showPluginDetail = async function(name, source) {
        // Show detail panel (fixed overlay)
        const detailPanel = document.getElementById('plugin-detail-panel');
        if (detailPanel) detailPanel.style.display = '';

        const detail = document.getElementById('plugin-detail');

        if (source === 'installed') {
            try {
                const data = await fetchJSON('/api/plugins');
                const plugin = (data.plugins || []).find(p => p.name === name);
                if (!plugin) { detail.innerHTML = '<p style="color:#f87171;">플러그인을 찾을 수 없습니다.</p>'; return; }
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
                    </div>`;
            } catch(e) { detail.innerHTML = '<p style="color:#f87171;">로드 실패: ' + e.message + '</p>'; }
        } else {
            // Find from curated or marketplace
            let plugin = null;
            for (const cat of POPULAR_PLUGINS) {
                plugin = cat.plugins.find(p => p.name === name);
                if (plugin) break;
            }
            if (!plugin) {
                try {
                    const data = await fetchJSON(`/api/marketplace/search?q=${encodeURIComponent(name)}`);
                    plugin = (data.results || []).find(p => p.name === name);
                } catch(e) { /* ignore */ }
            }
            if (!plugin) { detail.innerHTML = '<p style="color:#64748b;">상세 정보를 찾을 수 없습니다.</p>'; return; }

            const tags = (plugin.tags || []).map(t =>
                `<span style="font-size:10px;padding:2px 6px;border-radius:8px;background:#1e293b;color:#60a5fa;">${t}</span>`
            ).join(' ');
            const starsHtml = plugin.stars ? `<span style="color:#fbbf24;font-size:12px;margin-left:8px;">★ ${plugin.stars >= 1000 ? (plugin.stars/1000).toFixed(1)+'k' : plugin.stars}</span>` : '';
            detail.innerHTML = `
                <div style="margin-bottom:16px;">
                    <h3 style="color:#e2e8f0;font-size:18px;margin-bottom:4px;">${plugin.name}</h3>
                    <span style="font-size:12px;color:#64748b;">v${plugin.version || 'latest'}</span>
                    ${starsHtml}
                </div>
                <p style="color:#94a3b8;font-size:13px;margin-bottom:12px;">${plugin.description || 'No description'}</p>
                ${tags ? `<div style="margin-bottom:16px;">${tags}</div>` : ''}
                ${plugin.author ? `<p style="color:#64748b;font-size:12px;margin-bottom:8px;">by ${plugin.author}</p>` : ''}
                ${plugin.source ? `<p style="color:#64748b;font-size:12px;margin-bottom:16px;">📦 ${plugin.source}</p>` : ''}
                <div style="display:flex;gap:8px;">
                    <button onclick="window._installPluginFromStore('${plugin.source || plugin.name}')"
                        style="padding:8px 20px;background:#3b82f6;border:none;border-radius:8px;color:white;cursor:pointer;font-size:13px;">
                        설치
                    </button>
                </div>`;
        }
    };

    window._installPluginFromStore = async function(source) {
        try {
            await fetchJSON('/api/plugins/install', { method: 'POST', body: JSON.stringify({ source }) });
            if (window.showToast) window.showToast('플러그인이 설치되었습니다.', 'success');
            window.loadPluginsFeatured();
        } catch(e) {
            if (window.showToast) window.showToast('설치 실패: ' + e.message, 'error');
        }
    };

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

    window._uninstallPluginFromStore = async function(name) {
        if (!confirm(`"${name}" 플러그인을 삭제하시겠습니까?`)) return;
        try {
            await fetchJSON(`/api/plugins/${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (window.showToast) window.showToast(`${name} 삭제됨`, 'success');
            document.getElementById('plugin-detail').innerHTML = '<p style="color:#64748b;">플러그인을 선택하면 상세 정보가 표시됩니다.</p>';
            document.getElementById('plugin-detail-panel').style.display = 'none';
            window.loadPluginsFeatured();
        } catch(e) {
            if (window.showToast) window.showToast('삭제 실패: ' + e.message, 'error');
        }
    };

    window.initPluginsTab = window.loadPluginsFeatured;
})();
