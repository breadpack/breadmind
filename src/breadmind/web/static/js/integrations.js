// src/breadmind/web/static/js/integrations.js
/**
 * Integration Hub — unified service connection management
 */
(function() {
    'use strict';

    const API_BASE = '/api/integrations';

    window.initIntegrationsTab = function() {
        const container = document.getElementById('integrations-content');
        if (!container) return;
        loadIntegrations(container);
    };

    async function loadIntegrations(container) {
        container.innerHTML = '<div class="loading">로딩 중...</div>';
        try {
            const [services, summary] = await Promise.all([
                fetchJSON(`${API_BASE}/services`),
                fetchJSON(`${API_BASE}/summary`),
            ]);
            container.innerHTML = buildIntegrationsHTML(services, summary);
            attachIntegrationEvents();
        } catch (e) {
            container.innerHTML = `<div class="error">로드 실패: ${e.message}</div>`;
        }
    }

    function buildIntegrationsHTML(services, summary) {
        const categories = {
            productivity: { label: '📋 생산성', services: [] },
            files: { label: '📁 파일', services: [] },
            contacts: { label: '📇 연락처', services: [] },
            messenger: { label: '💬 메신저', services: [] },
        };

        services.forEach(s => {
            const cat = categories[s.category] || categories.productivity;
            cat.services.push(s);
        });

        let html = `
        <div class="integration-summary">
            <div class="summary-stat">
                <span class="summary-number">${summary.connected}</span>
                <span class="summary-label">연결됨</span>
            </div>
            <div class="summary-stat">
                <span class="summary-number">${summary.total - summary.connected}</span>
                <span class="summary-label">미연결</span>
            </div>
        </div>
        `;

        for (const [catId, cat] of Object.entries(categories)) {
            html += `<div class="integration-category">
                <h3>${cat.label}</h3>
                <div class="integration-grid">`;
            cat.services.forEach(s => {
                const statusClass = s.connected ? 'connected' : 'disconnected';
                const statusText = s.connected ? '연결됨' : '미연결';
                const actionBtn = s.connected
                    ? `<button class="btn-sm btn-danger" onclick="disconnectService('${s.id}')">연결 해제</button>`
                    : `<button class="btn-sm btn-primary" onclick="connectService('${s.id}','${s.auth_type}')">연결</button>`;

                html += `<div class="integration-card ${statusClass}">
                    <div class="integration-card-header">
                        <span class="integration-name">${s.name}</span>
                        <span class="integration-status ${statusClass}">${statusText}</span>
                    </div>
                    <div class="integration-card-actions">${actionBtn}</div>
                </div>`;
            });
            html += '</div></div>';
        }
        return html;
    }

    function attachIntegrationEvents() {}

    window.connectService = async function(serviceId, authType) {
        if (authType === 'oauth') {
            // Get OAuth URL and redirect
            try {
                const data = await fetchJSON(`${API_BASE}/services/${serviceId}`);
                if (data.connect_url) {
                    const resp = await fetchJSON(data.connect_url);
                    if (resp.auth_url) {
                        window.open(resp.auth_url, '_blank', 'width=600,height=700');
                    }
                }
            } catch (e) {
                showToast('OAuth 연결 실패: ' + e.message, 'error');
            }
        } else {
            // Show credential input modal
            showCredentialModal(serviceId, authType);
        }
    };

    window.disconnectService = async function(serviceId) {
        if (!confirm(`${serviceId} 연결을 해제하시겠습니까?`)) return;
        try {
            await fetchJSON(`${API_BASE}/services/${serviceId}/disconnect`, { method: 'DELETE' });
            showToast('연결이 해제되었습니다', 'success');
            const container = document.getElementById('integrations-content');
            loadIntegrations(container);
        } catch (e) {
            showToast('해제 실패: ' + e.message, 'error');
        }
    };

    function showCredentialModal(serviceId, authType) {
        let fields = '';
        if (serviceId === 'notion') {
            fields = `<input type="password" id="cred-api-key" placeholder="Notion API Key" class="modal-input">
                      <input type="text" id="cred-database-id" placeholder="Database ID" class="modal-input">`;
        } else if (serviceId === 'jira') {
            fields = `<input type="url" id="cred-base-url" placeholder="Jira URL (https://xxx.atlassian.net)" class="modal-input">
                      <input type="email" id="cred-email" placeholder="이메일" class="modal-input">
                      <input type="password" id="cred-api-token" placeholder="API Token" class="modal-input">
                      <input type="text" id="cred-project-key" placeholder="프로젝트 키 (예: PROJ)" class="modal-input">`;
        } else if (serviceId === 'github') {
            fields = `<input type="password" id="cred-token" placeholder="GitHub Personal Access Token" class="modal-input">
                      <input type="text" id="cred-owner" placeholder="Owner (예: username)" class="modal-input">
                      <input type="text" id="cred-repo" placeholder="Repository (예: my-repo)" class="modal-input">`;
        } else {
            fields = `<input type="password" id="cred-token" placeholder="API Token" class="modal-input">`;
        }

        const modal = document.getElementById('personal-modal') || document.createElement('div');
        modal.id = 'personal-modal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-backdrop" onclick="closeModal()"></div>
            <div class="modal-content">
                <h3>${serviceId} 연결</h3>
                ${fields}
                <div class="modal-actions">
                    <button class="btn-secondary" onclick="closeModal()">취소</button>
                    <button class="btn-primary" onclick="submitCredentials('${serviceId}')">연결</button>
                </div>
            </div>`;
        if (!modal.parentNode) document.body.appendChild(modal);
    }

    window.submitCredentials = async function(serviceId) {
        const body = {};
        document.querySelectorAll('#personal-modal .modal-input').forEach(input => {
            const key = input.id.replace('cred-', '').replace(/-/g, '_');
            if (input.value) body[key] = input.value;
        });

        try {
            await fetchJSON(`${API_BASE}/services/${serviceId}/connect`, {
                method: 'POST',
                body: JSON.stringify(body),
            });
            closeModal();
            showToast('연결되었습니다!', 'success');
            const container = document.getElementById('integrations-content');
            loadIntegrations(container);
        } catch (e) {
            showToast('연결 실패: ' + e.message, 'error');
        }
    };

    async function fetchJSON(url, opts = {}) {
        const headers = { 'Content-Type': 'application/json' };
        const token = document.cookie.match(/session_token=([^;]+)/)?.[1];
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const resp = await fetch(url, { ...opts, headers: { ...headers, ...opts.headers } });
        if (!resp.ok) throw new Error(`${resp.status}`);
        return resp.json();
    }
})();
