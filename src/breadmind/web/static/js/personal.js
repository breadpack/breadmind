// src/breadmind/web/static/js/personal.js
/**
 * Personal Assistant Tab — Task/Event/Contact management UI
 */
(function() {
    'use strict';

    const API_BASE = '/api/personal';
    let currentView = 'tasks'; // 'tasks' | 'events' | 'contacts'

    // --- Init ---
    window.initPersonalTab = function() {
        const container = document.getElementById('personal-content');
        if (!container) return;

        // Only build HTML structure once
        if (!container.dataset.initialized) {
            container.innerHTML = buildPersonalHTML();
            attachPersonalEvents();
            container.dataset.initialized = 'true';
        }

        // Always refresh data when tab is activated
        loadView(currentView);
    };

    // Expose refresh function for WebSocket-triggered updates
    window.refreshPersonalTab = function() {
        const personalTab = document.getElementById('tab-personal');
        if (personalTab && personalTab.style.display !== 'none') {
            loadView(currentView);
        }
    };

    function buildPersonalHTML() {
        return `
        <div class="personal-header">
            <div class="personal-nav">
                <button class="personal-nav-btn active" data-view="tasks">📋 할 일</button>
                <button class="personal-nav-btn" data-view="events">📅 일정</button>
                <button class="personal-nav-btn" data-view="contacts">📇 연락처</button>
            </div>
            <div class="personal-actions">
                <button class="btn-primary" id="personal-add-btn">+ 추가</button>
            </div>
        </div>
        <div id="personal-view" class="personal-view"></div>
        <div id="personal-modal" class="modal hidden"></div>
        `;
    }

    function attachPersonalEvents() {
        document.querySelectorAll('.personal-nav-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.personal-nav-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                loadView(btn.dataset.view);
            });
        });
        document.getElementById('personal-add-btn').addEventListener('click', showAddModal);
    }

    // --- Views ---
    async function loadView(view) {
        currentView = view;
        const container = document.getElementById('personal-view');
        container.innerHTML = '<div class="loading">로딩 중...</div>';

        try {
            if (view === 'tasks') await renderTasks(container);
            else if (view === 'events') await renderEvents(container);
            else if (view === 'contacts') await renderContacts(container);
        } catch (e) {
            container.innerHTML = `<div class="error">로드 실패: ${e.message}</div>`;
        }
    }

    async function renderTasks(container) {
        const tasks = await fetchJSON(`${API_BASE}/tasks`);
        if (!tasks.length) {
            container.innerHTML = '<div class="empty-state">할 일이 없습니다. + 버튼으로 추가하세요.</div>';
            return;
        }

        // Group by status
        const groups = { pending: [], in_progress: [], done: [] };
        tasks.forEach(t => {
            const g = groups[t.status] || groups.pending;
            g.push(t);
        });

        let html = '<div class="task-board">';
        for (const [status, items] of Object.entries(groups)) {
            const label = { pending: '⬜ 대기', in_progress: '🔵 진행', done: '✅ 완료' }[status];
            html += `<div class="task-column">
                <h3 class="task-column-header">${label} (${items.length})</h3>
                <div class="task-list">`;
            items.forEach(t => {
                const due = t.due_at ? `<span class="task-due">${formatDate(t.due_at)}</span>` : '';
                const pri = t.priority !== 'medium' ? `<span class="task-priority task-priority-${t.priority}">${t.priority}</span>` : '';
                html += `<div class="task-card" data-id="${t.id}">
                    <div class="task-card-header">
                        <span class="task-title">${escapeHtml(t.title)}</span>
                        ${pri}
                    </div>
                    ${due}
                    <div class="task-card-actions">
                        ${status !== 'done' ? `<button class="btn-sm" onclick="personalAction('task-done','${t.id}')">완료</button>` : ''}
                        <button class="btn-sm btn-danger" onclick="personalAction('task-delete','${t.id}')">삭제</button>
                    </div>
                </div>`;
            });
            html += '</div></div>';
        }
        html += '</div>';
        container.innerHTML = html;
    }

    async function renderEvents(container) {
        const events = await fetchJSON(`${API_BASE}/events`);
        if (!events.length) {
            container.innerHTML = '<div class="empty-state">예정된 일정이 없습니다.</div>';
            return;
        }

        let html = '<div class="event-list">';
        events.forEach(e => {
            const time = e.all_day ? '종일' : `${formatTime(e.start_at)}~${formatTime(e.end_at)}`;
            const loc = e.location ? `<span class="event-location">📍 ${escapeHtml(e.location)}</span>` : '';
            html += `<div class="event-card">
                <div class="event-date">${formatDateShort(e.start_at)}</div>
                <div class="event-info">
                    <div class="event-title">${escapeHtml(e.title)}</div>
                    <div class="event-meta">${time} ${loc}</div>
                </div>
                <button class="btn-sm btn-danger" onclick="personalAction('event-delete','${e.id}')">삭제</button>
            </div>`;
        });
        html += '</div>';
        container.innerHTML = html;
    }

    async function renderContacts(container) {
        const contacts = await fetchJSON(`${API_BASE}/contacts`);
        if (!contacts.length) {
            container.innerHTML = '<div class="empty-state">연락처가 없습니다.</div>';
            return;
        }

        let html = '<div class="contact-list">';
        contacts.forEach(c => {
            html += `<div class="contact-card">
                <div class="contact-avatar">${c.name[0]}</div>
                <div class="contact-info">
                    <div class="contact-name">${escapeHtml(c.name)}</div>
                    ${c.email ? `<div class="contact-detail">📧 ${escapeHtml(c.email)}</div>` : ''}
                    ${c.phone ? `<div class="contact-detail">📱 ${escapeHtml(c.phone)}</div>` : ''}
                    ${c.organization ? `<div class="contact-detail">🏢 ${escapeHtml(c.organization)}</div>` : ''}
                </div>
            </div>`;
        });
        html += '</div>';
        container.innerHTML = html;
    }

    // --- Add Modal ---
    function showAddModal() {
        const modal = document.getElementById('personal-modal');
        let fields = '';

        if (currentView === 'tasks') {
            fields = `
                <h3>할 일 추가</h3>
                <input type="text" id="modal-title" placeholder="제목" class="modal-input" autofocus>
                <input type="datetime-local" id="modal-due" class="modal-input">
                <select id="modal-priority" class="modal-input">
                    <option value="medium">보통</option>
                    <option value="low">낮음</option>
                    <option value="high">높음</option>
                    <option value="urgent">긴급</option>
                </select>
            `;
        } else if (currentView === 'events') {
            fields = `
                <h3>일정 추가</h3>
                <input type="text" id="modal-title" placeholder="제목" class="modal-input" autofocus>
                <input type="datetime-local" id="modal-start" class="modal-input">
                <input type="datetime-local" id="modal-end" class="modal-input">
                <input type="text" id="modal-location" placeholder="장소" class="modal-input">
            `;
        } else {
            fields = `
                <h3>연락처 추가</h3>
                <input type="text" id="modal-name" placeholder="이름" class="modal-input" autofocus>
                <input type="email" id="modal-email" placeholder="이메일" class="modal-input">
                <input type="tel" id="modal-phone" placeholder="전화번호" class="modal-input">
                <input type="text" id="modal-org" placeholder="소속" class="modal-input">
            `;
        }

        modal.innerHTML = `
            <div class="modal-backdrop" onclick="closeModal()"></div>
            <div class="modal-content">
                ${fields}
                <div class="modal-actions">
                    <button class="btn-secondary" onclick="closeModal()">취소</button>
                    <button class="btn-primary" onclick="submitModal()">추가</button>
                </div>
            </div>
        `;
        modal.classList.remove('hidden');
    }

    window.closeModal = function() {
        document.getElementById('personal-modal').classList.add('hidden');
    };

    window.submitModal = async function() {
        // Validate required fields
        if (currentView === 'tasks') {
            const title = document.getElementById('modal-title');
            if (!title.value.trim()) {
                title.classList.add('invalid');
                showToast('제목을 입력하세요', 'warning');
                return;
            }
        } else if (currentView === 'events') {
            const title = document.getElementById('modal-title');
            const start = document.getElementById('modal-start');
            if (!title.value.trim()) {
                title.classList.add('invalid');
                showToast('제목을 입력하세요', 'warning');
                return;
            }
            if (!start.value) {
                start.classList.add('invalid');
                showToast('시작 시간을 선택하세요', 'warning');
                return;
            }
        } else { // contacts
            const name = document.getElementById('modal-name');
            if (!name.value.trim()) {
                name.classList.add('invalid');
                showToast('이름을 입력하세요', 'warning');
                return;
            }
        }

        // Clear previous validation
        document.querySelectorAll('.modal-input').forEach(i => i.classList.remove('invalid'));

        const btn = document.querySelector('#personal-modal .btn-primary');
        btnLoading(btn, '추가 중...');

        try {
            if (currentView === 'tasks') {
                await fetchJSON(`${API_BASE}/tasks`, {
                    method: 'POST',
                    body: JSON.stringify({
                        title: document.getElementById('modal-title').value,
                        due_at: document.getElementById('modal-due').value || null,
                        priority: document.getElementById('modal-priority').value,
                    }),
                });
            } else if (currentView === 'events') {
                const start = document.getElementById('modal-start').value;
                await fetchJSON(`${API_BASE}/events`, {
                    method: 'POST',
                    body: JSON.stringify({
                        title: document.getElementById('modal-title').value,
                        start_at: start ? new Date(start).toISOString() : null,
                        end_at: document.getElementById('modal-end').value ? new Date(document.getElementById('modal-end').value).toISOString() : null,
                        location: document.getElementById('modal-location').value || null,
                    }),
                });
            } else {
                await fetchJSON(`${API_BASE}/contacts`, {
                    method: 'POST',
                    body: JSON.stringify({
                        name: document.getElementById('modal-name').value,
                        email: document.getElementById('modal-email').value || null,
                        phone: document.getElementById('modal-phone').value || null,
                        organization: document.getElementById('modal-org').value || null,
                    }),
                });
            }
            closeModal();
            showToast('추가 완료!', 'success');
            loadView(currentView);
        } catch (e) {
            showToast('추가 실패: ' + e.message, 'error');
        } finally {
            btnReset(btn);
        }
    };

    // --- Actions ---
    window.personalAction = async function(action, id) {
        try {
            if (action === 'task-done') {
                await fetchJSON(`${API_BASE}/tasks/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'done' }) });
                showToast('할 일 완료!', 'success');
            } else if (action === 'task-delete') {
                if (!confirm('삭제하시겠습니까?')) return;
                await fetchJSON(`${API_BASE}/tasks/${id}`, { method: 'DELETE' });
                showToast('삭제되었습니다', 'success');
            } else if (action === 'event-delete') {
                if (!confirm('삭제하시겠습니까?')) return;
                await fetchJSON(`${API_BASE}/events/${id}`, { method: 'DELETE' });
                showToast('삭제되었습니다', 'success');
            }
            loadView(currentView);
        } catch (e) {
            showToast('작업 실패: ' + e.message, 'error');
        }
    };

    // --- Helpers ---
    async function fetchJSON(url, opts = {}) {
        const headers = { 'Content-Type': 'application/json' };
        const token = document.cookie.match(/session_token=([^;]+)/)?.[1];
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const resp = await fetch(url, { ...opts, headers: { ...headers, ...opts.headers } });
        if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
        return resp.json();
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }

    function formatDate(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        return `${d.getMonth()+1}/${d.getDate()} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
    }

    function formatDateShort(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        return `${d.getMonth()+1}/${d.getDate()}`;
    }

    function formatTime(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
    }

    // Auto-refresh when browser tab regains focus
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            const personalTab = document.getElementById('tab-personal');
            if (personalTab && personalTab.style.display !== 'none') {
                loadView(currentView);
            }
        }
    });
})();
