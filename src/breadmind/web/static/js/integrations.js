// src/breadmind/web/static/js/integrations.js
/**
 * Integration Hub — unified service connection management
 */
(function() {
    'use strict';

    const API_BASE = '/api/integrations';

    // Listen for OAuth callback from popup window
    window.addEventListener('message', (event) => {
        if (event.data && event.data.type === 'oauth_complete') {
            showToast(
                event.data.success ? `${event.data.provider} 연결 완료!` : `${event.data.provider} 인증 실패`,
                event.data.success ? 'success' : 'error'
            );
            // Refresh integration list
            const container = document.getElementById('integrations-content');
            if (container) loadIntegrations(container);

            // Show usage guide on success
            if (event.data.success) {
                setTimeout(() => showServiceUsageGuide(event.data.provider), 1000);
            }
        }
    });

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
        const guides = {
            notion: {
                title: 'Notion 연결',
                guide: '1. <a href="https://www.notion.so/my-integrations" target="_blank">Notion Integrations</a> 페이지 방문\n2. "+ New integration" 클릭\n3. 이름 입력 후 "Submit"\n4. "Internal Integration Secret" 복사\n5. 연결할 데이터베이스에서 ··· → Connections → 방금 만든 Integration 추가',
                fields: `
                    <input type="password" id="cred-api-key" placeholder="Internal Integration Secret" class="modal-input" required>
                    <input type="text" id="cred-database-id" placeholder="Database ID (URL에서 복사)" class="modal-input">
                    <p class="field-hint">Database ID: Notion URL에서 notion.so/ 뒤의 32자리 문자열</p>
                `,
            },
            jira: {
                title: 'Jira 연결',
                guide: '1. <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank">Atlassian API Tokens</a> 페이지 방문\n2. "Create API token" 클릭\n3. 토큰 복사',
                fields: `
                    <input type="url" id="cred-base-url" placeholder="https://yourteam.atlassian.net" class="modal-input" required>
                    <input type="email" id="cred-email" placeholder="Atlassian 계정 이메일" class="modal-input" required>
                    <input type="password" id="cred-api-token" placeholder="API Token" class="modal-input" required>
                    <input type="text" id="cred-project-key" placeholder="프로젝트 키 (Jira 보드 URL에서 확인)" class="modal-input">
                    <p class="field-hint">프로젝트 키: Jira 보드에서 이슈 번호 앞 영문자 (예: PROJ-123 → PROJ)</p>
                `,
            },
            github: {
                title: 'GitHub Issues 연결',
                guide: '1. <a href="https://github.com/settings/tokens/new" target="_blank">GitHub Token 생성</a> 페이지 방문\n2. "Generate new token (classic)" 선택\n3. Scopes: <code>repo</code> 체크\n4. "Generate token" 클릭 후 복사',
                fields: `
                    <input type="password" id="cred-token" placeholder="ghp_xxxx..." class="modal-input" required>
                    <input type="text" id="cred-owner" placeholder="Owner (예: username 또는 org-name)" class="modal-input" required>
                    <input type="text" id="cred-repo" placeholder="Repository (예: my-project)" class="modal-input" required>
                    <p class="field-hint">GitHub URL에서 확인: github.com/<strong>owner</strong>/<strong>repo</strong></p>
                `,
            },
        };

        const config = guides[serviceId] || { title: `${serviceId} 연결`, guide: '', fields: `<input type="password" id="cred-token" placeholder="API Token" class="modal-input" required>` };

        const modal = document.getElementById('personal-modal') || document.createElement('div');
        modal.id = 'personal-modal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-backdrop" onclick="closeModal()"></div>
            <div class="modal-content" style="max-width:520px">
                <h3>${config.title}</h3>
                ${config.guide ? `<div class="setup-guide"><h4>\ud83d\udcd6 설정 가이드</h4><div class="guide-steps">${config.guide.replace(/\n/g, '<br>')}</div></div>` : ''}
                <div class="setup-fields">${config.fields}</div>
                <div class="modal-actions">
                    <button class="btn-secondary" onclick="closeModal()">취소</button>
                    <button class="btn-primary" id="connect-btn" onclick="submitCredentials('${serviceId}')">연결 확인</button>
                </div>
            </div>`;
        if (!modal.parentNode) document.body.appendChild(modal);
    }

    function showServiceUsageGuide(provider) {
        const guides = {
            google: {
                name: 'Google 서비스',
                actions: [
                    '\ud83d\udcac 채팅: "이번 주 일정 보여줘"',
                    '\ud83d\udcac 채팅: "드라이브에서 보고서 찾아줘"',
                    '\ud83d\udcac 채팅: "김철수 연락처 알려줘"',
                    '\ud83d\udccb 비서 탭에서 동기화된 항목 확인',
                ],
            },
            microsoft: {
                name: 'Microsoft 서비스',
                actions: [
                    '\ud83d\udcac 채팅: "Outlook 일정 확인해줘"',
                    '\ud83d\udcac 채팅: "OneDrive 파일 검색해줘"',
                    '\ud83d\udccb 비서 탭에서 일정 확인',
                ],
            },
            notion: {
                name: 'Notion',
                actions: [
                    '\ud83d\udcac 채팅: "Notion에서 할 일 가져와줘"',
                    '\ud83d\udcac 채팅: "Notion에 새 페이지 만들어줘"',
                    '\ud83d\udccb 비서 탭 \u2192 할 일에서 Notion 항목 확인',
                ],
            },
            jira: {
                name: 'Jira',
                actions: [
                    '\ud83d\udcac 채팅: "Jira 이슈 목록 보여줘"',
                    '\ud83d\udcac 채팅: "새 Jira 이슈 만들어줘"',
                    '\ud83d\udccb 비서 탭 \u2192 할 일에서 Jira 이슈 확인',
                ],
            },
            github: {
                name: 'GitHub Issues',
                actions: [
                    '\ud83d\udcac 채팅: "GitHub 이슈 목록 보여줘"',
                    '\ud83d\udcac 채팅: "새 이슈 만들어줘"',
                    '\ud83d\udccb 비서 탭 \u2192 할 일에서 GitHub 이슈 확인',
                ],
            },
        };

        const guide = guides[provider] || { name: provider, actions: ['채팅에서 자연어로 요청하세요'] };

        const modal = document.getElementById('personal-modal') || document.createElement('div');
        modal.id = 'personal-modal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-backdrop" onclick="closeModal()"></div>
            <div class="modal-content">
                <h3>\u2705 ${guide.name} 연결 완료!</h3>
                <p class="guide-text">이제 다음을 할 수 있습니다:</p>
                <ul class="guide-list">${guide.actions.map(a => `<li>${a}</li>`).join('')}</ul>
                <div class="modal-actions">
                    <button class="btn-secondary" onclick="closeModal()">닫기</button>
                    <button class="btn-primary" onclick="closeModal(); switchTab('personal');">비서 탭으로 이동</button>
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
