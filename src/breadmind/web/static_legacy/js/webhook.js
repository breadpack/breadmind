(function() {
    'use strict';

    const API = '/api/webhook';
    let _whTab = 'rules';  // rules | pipelines | yaml
    let _rules = [];
    let _pipelines = [];

    // ── Helpers ──────────────────────────────────────────────────────────

    function esc(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    async function apiFetch(path, opts = {}) {
        const headers = { 'Content-Type': 'application/json' };
        const token = document.cookie.match(/session_token=([^;]+)/)?.[1];
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const resp = await fetch(`${API}${path}`, { ...opts, headers });
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(body.error || `HTTP ${resp.status}`);
        }
        const ct = resp.headers.get('content-type') || '';
        if (ct.includes('yaml') || ct.includes('text/plain')) return resp.text();
        return resp.json();
    }

    // ── Data Loading ────────────────────────────────────────────────────

    async function loadRules() {
        try {
            const data = await apiFetch('/rules');
            _rules = data.rules || [];
        } catch { _rules = []; }
    }

    async function loadPipelines() {
        try {
            const data = await apiFetch('/pipelines');
            _pipelines = data.pipelines || [];
        } catch { _pipelines = []; }
    }

    // ── Init ────────────────────────────────────────────────────────────

    window.initWebhookTab = async function() {
        await Promise.all([loadRules(), loadPipelines()]);
        render();
    };

    // ── Render ───────────────────────────────────────────────────────────

    function render() {
        const container = document.getElementById('webhook-content');
        if (!container) return;

        let html = '';
        // Tab bar
        html += `<div class="wh-tabs">
            <button class="wh-tab ${_whTab === 'rules' ? 'active' : ''}" onclick="whSwitchTab('rules')">Rules <span class="wh-count">${_rules.length}</span></button>
            <button class="wh-tab ${_whTab === 'pipelines' ? 'active' : ''}" onclick="whSwitchTab('pipelines')">Pipelines <span class="wh-count">${_pipelines.length}</span></button>
            <button class="wh-tab ${_whTab === 'yaml' ? 'active' : ''}" onclick="whSwitchTab('yaml')">YAML</button>
        </div>`;

        if (_whTab === 'rules') html += renderRulesTab();
        else if (_whTab === 'pipelines') html += renderPipelinesTab();
        else html += renderYamlTab();

        container.innerHTML = html;
    }

    window.whSwitchTab = function(tab) {
        _whTab = tab;
        render();
        // Re-attach YAML export after rendering
        if (tab === 'yaml') loadYamlExport();
    };

    // ── Rules Tab ────────────────────────────────────────────────────────

    function renderRulesTab() {
        let html = `<div class="webhook-header">
            <h3>Webhook Rules</h3>
            <div class="webhook-header-actions">
                <button class="wh-btn wh-btn-primary" onclick="whShowRuleModal()">+ New Rule</button>
            </div>
        </div>`;

        if (_rules.length === 0) {
            html += `<div class="wh-empty"><div class="wh-empty-icon">&#128268;</div>No rules defined yet.<br>Create a rule to match incoming webhooks to pipelines.</div>`;
            return html;
        }

        html += '<div class="wh-list">';
        const sorted = [..._rules].sort((a, b) => a.priority - b.priority);
        for (const r of sorted) {
            const pName = _pipelines.find(p => p.id === r.pipeline_id)?.name || r.pipeline_id;
            html += `<div class="wh-card">
                <div class="wh-card-header">
                    <div class="wh-card-title">
                        <span class="wh-priority">${r.priority}</span>
                        ${esc(r.name)}
                        <span class="wh-badge ${r.enabled ? 'enabled' : 'disabled'}"><span class="wh-badge-dot"></span>${r.enabled ? 'Active' : 'Off'}</span>
                    </div>
                    <div class="wh-card-actions">
                        <button class="wh-card-btn test" onclick="whTestRule('${r.id}')">Test</button>
                        <button class="wh-card-btn" onclick="whEditRule('${r.id}')">Edit</button>
                        <button class="wh-card-btn danger" onclick="whDeleteRule('${r.id}','${esc(r.name)}')">Delete</button>
                    </div>
                </div>
                <div class="wh-card-meta">
                    <span>Endpoint: <strong>${esc(r.endpoint_id)}</strong></span>
                    <span>Pipeline: <strong>${esc(pName)}</strong></span>
                </div>
                <div class="wh-card-condition">${esc(r.condition)}</div>
                <div id="test-result-${r.id}"></div>
            </div>`;
        }
        html += '</div>';
        return html;
    }

    // ── Pipelines Tab ────────────────────────────────────────────────────

    function renderPipelinesTab() {
        let html = `<div class="webhook-header">
            <h3>Pipelines</h3>
            <div class="webhook-header-actions">
                <button class="wh-btn wh-btn-primary" onclick="whShowPipelineModal()">+ New Pipeline</button>
            </div>
        </div>`;

        if (_pipelines.length === 0) {
            html += `<div class="wh-empty"><div class="wh-empty-icon">&#9881;</div>No pipelines defined yet.<br>Create a pipeline to define action sequences.</div>`;
            return html;
        }

        html += '<div class="wh-list">';
        for (const p of _pipelines) {
            const ruleCount = _rules.filter(r => r.pipeline_id === p.id).length;
            html += `<div class="wh-card">
                <div class="wh-card-header">
                    <div class="wh-card-title">
                        ${esc(p.name)}
                        <span class="wh-badge ${p.enabled ? 'enabled' : 'disabled'}"><span class="wh-badge-dot"></span>${p.enabled ? 'Active' : 'Off'}</span>
                    </div>
                    <div class="wh-card-actions">
                        <button class="wh-card-btn" onclick="whEditPipeline('${p.id}')">Edit</button>
                        <button class="wh-card-btn danger" onclick="whDeletePipeline('${p.id}','${esc(p.name)}')">Delete</button>
                    </div>
                </div>
                <div class="wh-card-meta">
                    <span>${ruleCount} rule${ruleCount !== 1 ? 's' : ''} linked</span>
                    <span>${p.actions.length} action${p.actions.length !== 1 ? 's' : ''}</span>
                    ${p.description ? `<span>${esc(p.description)}</span>` : ''}
                </div>
                ${renderActionChips(p.actions)}
            </div>`;
        }
        html += '</div>';
        return html;
    }

    function renderActionChips(actions) {
        if (!actions || actions.length === 0) return '';
        const typeLabels = {
            send_to_agent: 'Agent',
            call_tool: 'Tool',
            http_request: 'HTTP',
            notify: 'Notify',
            transform: 'Transform',
        };
        let html = '<div class="wh-pipeline-actions">';
        actions.forEach((a, i) => {
            if (i > 0) html += '<span class="wh-pipeline-arrow">&#8594;</span>';
            html += `<span class="wh-action-chip" data-type="${a.action_type}">${typeLabels[a.action_type] || a.action_type}</span>`;
        });
        html += '</div>';
        return html;
    }

    // ── YAML Tab ─────────────────────────────────────────────────────────

    function renderYamlTab() {
        return `<div class="webhook-header">
            <h3>YAML Import / Export</h3>
        </div>
        <div class="wh-yaml-container">
            <textarea class="wh-yaml-editor" id="wh-yaml-editor" placeholder="rules:\n  - name: ...\npipelines:\n  - name: ..."></textarea>
            <div class="wh-yaml-actions">
                <button class="wh-btn wh-btn-secondary" onclick="whYamlExport()">Export Current</button>
                <button class="wh-btn wh-btn-primary" onclick="whYamlImport()">Import</button>
            </div>
        </div>`;
    }

    async function loadYamlExport() {
        try {
            const yaml = await apiFetch('/export');
            const el = document.getElementById('wh-yaml-editor');
            if (el) el.value = yaml;
        } catch {}
    }

    window.whYamlExport = async function() {
        try {
            const yaml = await apiFetch('/export');
            const el = document.getElementById('wh-yaml-editor');
            if (el) el.value = yaml;
            if (typeof showToast === 'function') showToast('YAML exported', 'success');
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
        }
    };

    window.whYamlImport = async function() {
        const el = document.getElementById('wh-yaml-editor');
        if (!el || !el.value.trim()) {
            if (typeof showToast === 'function') showToast('YAML is empty', 'warning');
            return;
        }
        try {
            const data = await apiFetch('/import', {
                method: 'POST',
                body: el.value,
                headers: { 'Content-Type': 'text/plain' },
            });
            const counts = data.imported || {};
            if (typeof showToast === 'function') showToast(`Imported ${counts.rules || 0} rules, ${counts.pipelines || 0} pipelines`, 'success');
            await Promise.all([loadRules(), loadPipelines()]);
            render();
            if (_whTab === 'yaml') loadYamlExport();
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
        }
    };

    // ── Rule CRUD ────────────────────────────────────────────────────────

    window.whShowRuleModal = function(editId) {
        const rule = editId ? _rules.find(r => r.id === editId) : null;
        const title = rule ? 'Edit Rule' : 'New Rule';

        let pipeOpts = _pipelines.map(p =>
            `<option value="${p.id}" ${rule && rule.pipeline_id === p.id ? 'selected' : ''}>${esc(p.name)}</option>`
        ).join('');

        const html = `<div class="wh-modal-overlay visible" id="wh-modal" onclick="if(event.target===this)whCloseModal()">
            <div class="wh-modal">
                <div class="wh-modal-header">
                    <h4>${title}</h4>
                    <button class="wh-modal-close" onclick="whCloseModal()">&times;</button>
                </div>
                <div class="wh-modal-body">
                    <div class="wh-field">
                        <label class="wh-field-label">Name</label>
                        <input class="wh-input" id="wh-rule-name" value="${esc(rule?.name || '')}" placeholder="e.g. PR opened -> review" />
                    </div>
                    <div class="wh-field">
                        <label class="wh-field-label">Endpoint ID</label>
                        <input class="wh-input" id="wh-rule-endpoint" value="${esc(rule?.endpoint_id || '')}" placeholder="e.g. github-pr" />
                    </div>
                    <div class="wh-field">
                        <label class="wh-field-label">Condition</label>
                        <textarea class="wh-textarea" id="wh-rule-condition" rows="3" placeholder="payload.get('action') == 'opened'">${esc(rule?.condition || '')}</textarea>
                        <span class="wh-field-hint">Python expression. Available variables: payload, headers</span>
                    </div>
                    <div style="display:flex;gap:12px;">
                        <div class="wh-field" style="flex:1;">
                            <label class="wh-field-label">Priority</label>
                            <input class="wh-input" id="wh-rule-priority" type="number" min="0" value="${rule?.priority ?? 0}" />
                            <span class="wh-field-hint">Lower = evaluated first</span>
                        </div>
                        <div class="wh-field" style="flex:2;">
                            <label class="wh-field-label">Pipeline</label>
                            <select class="wh-select" id="wh-rule-pipeline">
                                <option value="">-- Select pipeline --</option>
                                ${pipeOpts}
                            </select>
                        </div>
                    </div>
                    <div class="wh-checkbox-row">
                        <input type="checkbox" id="wh-rule-enabled" ${rule?.enabled !== false ? 'checked' : ''} />
                        <label for="wh-rule-enabled">Enabled</label>
                    </div>
                </div>
                <div class="wh-modal-footer">
                    <button class="wh-btn wh-btn-secondary" onclick="whCloseModal()">Cancel</button>
                    <button class="wh-btn wh-btn-primary" onclick="whSaveRule('${editId || ''}')">${rule ? 'Save' : 'Create'}</button>
                </div>
            </div>
        </div>`;

        document.body.insertAdjacentHTML('beforeend', html);
    };

    window.whEditRule = function(id) { whShowRuleModal(id); };

    window.whCloseModal = function() {
        const m = document.getElementById('wh-modal');
        if (m) m.remove();
    };

    window.whSaveRule = async function(editId) {
        const name = document.getElementById('wh-rule-name').value.trim();
        const endpoint_id = document.getElementById('wh-rule-endpoint').value.trim();
        const condition = document.getElementById('wh-rule-condition').value.trim();
        const priority = parseInt(document.getElementById('wh-rule-priority').value, 10) || 0;
        const pipeline_id = document.getElementById('wh-rule-pipeline').value;
        const enabled = document.getElementById('wh-rule-enabled').checked;

        if (!name || !endpoint_id || !condition || !pipeline_id) {
            if (typeof showToast === 'function') showToast('Please fill all required fields', 'warning');
            return;
        }

        const body = JSON.stringify({ name, endpoint_id, condition, priority, pipeline_id, enabled });

        try {
            if (editId) {
                await apiFetch(`/rules/${editId}`, { method: 'PUT', body });
            } else {
                await apiFetch('/rules', { method: 'POST', body });
            }
            if (typeof showToast === 'function') showToast(editId ? 'Rule updated' : 'Rule created', 'success');
            whCloseModal();
            await loadRules();
            render();
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
        }
    };

    window.whDeleteRule = async function(id, name) {
        if (!confirm(`Delete rule "${name}"?`)) return;
        try {
            await apiFetch(`/rules/${id}`, { method: 'DELETE' });
            if (typeof showToast === 'function') showToast('Rule deleted', 'success');
            await loadRules();
            render();
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
        }
    };

    // ── Rule Dry-Run Test ────────────────────────────────────────────────

    window.whTestRule = function(ruleId) {
        const rule = _rules.find(r => r.id === ruleId);
        if (!rule) return;

        const html = `<div class="wh-modal-overlay visible" id="wh-modal" onclick="if(event.target===this)whCloseModal()">
            <div class="wh-modal">
                <div class="wh-modal-header">
                    <h4>Test Rule: ${esc(rule.name)}</h4>
                    <button class="wh-modal-close" onclick="whCloseModal()">&times;</button>
                </div>
                <div class="wh-modal-body">
                    <div class="wh-card-condition" style="margin:0;">${esc(rule.condition)}</div>
                    <div class="wh-field">
                        <label class="wh-field-label">Test Payload (JSON)</label>
                        <textarea class="wh-textarea" id="wh-test-payload" rows="6" style="min-height:100px;" placeholder='{"action": "opened", "pull_request": {"labels": []}}'>{}</textarea>
                    </div>
                    <div class="wh-field">
                        <label class="wh-field-label">Test Headers (JSON)</label>
                        <textarea class="wh-textarea" id="wh-test-headers" rows="3" placeholder='{"X-Event-Type": "push"}'>{}</textarea>
                    </div>
                    <div id="wh-test-result"></div>
                </div>
                <div class="wh-modal-footer">
                    <button class="wh-btn wh-btn-secondary" onclick="whCloseModal()">Close</button>
                    <button class="wh-btn wh-btn-primary" onclick="whRunTest('${ruleId}')">Run Test</button>
                </div>
            </div>
        </div>`;

        document.body.insertAdjacentHTML('beforeend', html);
    };

    window.whRunTest = async function(ruleId) {
        const resultEl = document.getElementById('wh-test-result');
        if (!resultEl) return;

        let payload, headers;
        try {
            payload = JSON.parse(document.getElementById('wh-test-payload').value || '{}');
            headers = JSON.parse(document.getElementById('wh-test-headers').value || '{}');
        } catch (e) {
            resultEl.innerHTML = `<div class="wh-test-result error">Invalid JSON: ${esc(e.message)}</div>`;
            return;
        }

        try {
            const data = await apiFetch(`/rules/${ruleId}/test`, {
                method: 'POST',
                body: JSON.stringify({ payload, headers }),
            });

            if (data.error) {
                resultEl.innerHTML = `<div class="wh-test-result error">Error: ${esc(data.error)}</div>`;
            } else if (data.matched) {
                resultEl.innerHTML = `<div class="wh-test-result matched">&#10003; Condition matched</div>`;
            } else {
                resultEl.innerHTML = `<div class="wh-test-result not-matched">&#10007; Condition did not match</div>`;
            }
        } catch (e) {
            resultEl.innerHTML = `<div class="wh-test-result error">${esc(e.message)}</div>`;
        }
    };

    // ── Pipeline CRUD ────────────────────────────────────────────────────

    let _editActions = [];

    window.whShowPipelineModal = function(editId) {
        const pipeline = editId ? _pipelines.find(p => p.id === editId) : null;
        const title = pipeline ? 'Edit Pipeline' : 'New Pipeline';
        _editActions = pipeline ? JSON.parse(JSON.stringify(pipeline.actions)) : [];

        const html = `<div class="wh-modal-overlay visible" id="wh-modal" onclick="if(event.target===this)whCloseModal()">
            <div class="wh-modal">
                <div class="wh-modal-header">
                    <h4>${title}</h4>
                    <button class="wh-modal-close" onclick="whCloseModal()">&times;</button>
                </div>
                <div class="wh-modal-body">
                    <div class="wh-field">
                        <label class="wh-field-label">Name</label>
                        <input class="wh-input" id="wh-pipe-name" value="${esc(pipeline?.name || '')}" placeholder="e.g. pr-review-pipeline" />
                    </div>
                    <div class="wh-field">
                        <label class="wh-field-label">Description</label>
                        <input class="wh-input" id="wh-pipe-desc" value="${esc(pipeline?.description || '')}" placeholder="Optional description" />
                    </div>
                    <div class="wh-checkbox-row">
                        <input type="checkbox" id="wh-pipe-enabled" ${pipeline?.enabled !== false ? 'checked' : ''} />
                        <label for="wh-pipe-enabled">Enabled</label>
                    </div>
                    <div class="wh-field">
                        <label class="wh-field-label">Actions</label>
                        <div id="wh-pipe-actions-list"></div>
                        <button class="wh-btn wh-btn-ghost" onclick="whAddAction()" style="margin-top:6px;">+ Add Action</button>
                    </div>
                </div>
                <div class="wh-modal-footer">
                    <button class="wh-btn wh-btn-secondary" onclick="whCloseModal()">Cancel</button>
                    <button class="wh-btn wh-btn-primary" onclick="whSavePipeline('${editId || ''}')">${pipeline ? 'Save' : 'Create'}</button>
                </div>
            </div>
        </div>`;

        document.body.insertAdjacentHTML('beforeend', html);
        renderActionsList();
    };

    window.whEditPipeline = function(id) { whShowPipelineModal(id); };

    function renderActionsList() {
        const container = document.getElementById('wh-pipe-actions-list');
        if (!container) return;

        if (_editActions.length === 0) {
            container.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;padding:8px 0;">No actions yet. Click "+ Add Action" below.</div>';
            return;
        }

        const typeLabels = {
            send_to_agent: 'Agent',
            call_tool: 'Tool',
            http_request: 'HTTP',
            notify: 'Notify',
            transform: 'Transform',
        };

        let html = '<div class="wh-action-list">';
        _editActions.forEach((a, i) => {
            const configPreview = a.config ? JSON.stringify(a.config).slice(0, 60) : '';
            html += `<div class="wh-action-item">
                <span class="wh-action-item-index">${i + 1}</span>
                <div class="wh-action-item-body">
                    <span class="wh-action-item-type">${typeLabels[a.action_type] || a.action_type}</span>
                    <div class="wh-action-item-detail">${esc(configPreview)}${configPreview.length >= 60 ? '...' : ''}</div>
                </div>
                <div class="wh-action-item-actions">
                    <button class="wh-action-item-btn" onclick="whEditAction(${i})">Edit</button>
                    ${i > 0 ? `<button class="wh-action-item-btn" onclick="whMoveAction(${i},-1)">&#9650;</button>` : ''}
                    ${i < _editActions.length - 1 ? `<button class="wh-action-item-btn" onclick="whMoveAction(${i},1)">&#9660;</button>` : ''}
                    <button class="wh-action-item-btn remove" onclick="whRemoveAction(${i})">&#10005;</button>
                </div>
            </div>`;
        });
        html += '</div>';
        container.innerHTML = html;
    }

    window.whAddAction = function() {
        _editActions.push({
            action_type: 'send_to_agent',
            config: {},
            on_failure: 'stop',
            max_retries: 0,
            capture_response: false,
            response_variable: '',
            timeout: 30,
        });
        renderActionsList();
        whEditAction(_editActions.length - 1);
    };

    window.whRemoveAction = function(idx) {
        _editActions.splice(idx, 1);
        renderActionsList();
    };

    window.whMoveAction = function(idx, dir) {
        const target = idx + dir;
        if (target < 0 || target >= _editActions.length) return;
        [_editActions[idx], _editActions[target]] = [_editActions[target], _editActions[idx]];
        renderActionsList();
    };

    // ── Action Editor Sub-Modal ──────────────────────────────────────────

    window.whEditAction = function(idx) {
        const a = _editActions[idx];
        if (!a) return;
        const configStr = a.config ? JSON.stringify(a.config, null, 2) : '{}';

        const html = `<div class="wh-modal-overlay visible" id="wh-action-modal" style="z-index:1001;" onclick="if(event.target===this)whCloseActionModal()">
            <div class="wh-modal" style="width:480px;">
                <div class="wh-modal-header">
                    <h4>Action #${idx + 1}</h4>
                    <button class="wh-modal-close" onclick="whCloseActionModal()">&times;</button>
                </div>
                <div class="wh-modal-body">
                    <div class="wh-field">
                        <label class="wh-field-label">Action Type</label>
                        <select class="wh-select" id="wh-act-type">
                            <option value="send_to_agent" ${a.action_type === 'send_to_agent' ? 'selected' : ''}>Send to Agent</option>
                            <option value="call_tool" ${a.action_type === 'call_tool' ? 'selected' : ''}>Call Tool</option>
                            <option value="http_request" ${a.action_type === 'http_request' ? 'selected' : ''}>HTTP Request</option>
                            <option value="notify" ${a.action_type === 'notify' ? 'selected' : ''}>Notify</option>
                            <option value="transform" ${a.action_type === 'transform' ? 'selected' : ''}>Transform</option>
                        </select>
                    </div>
                    <div class="wh-field">
                        <label class="wh-field-label">Config (JSON)</label>
                        <textarea class="wh-textarea" id="wh-act-config" rows="5" style="min-height:80px;">${esc(configStr)}</textarea>
                        <span class="wh-field-hint">Template vars: {payload.xxx}, {steps.varname}, {secrets.xxx}</span>
                    </div>
                    <div style="display:flex;gap:12px;">
                        <div class="wh-field" style="flex:1;">
                            <label class="wh-field-label">On Failure</label>
                            <select class="wh-select" id="wh-act-failure">
                                <option value="stop" ${a.on_failure === 'stop' ? 'selected' : ''}>Stop</option>
                                <option value="continue" ${a.on_failure === 'continue' ? 'selected' : ''}>Continue</option>
                                <option value="retry" ${a.on_failure === 'retry' ? 'selected' : ''}>Retry</option>
                                <option value="fallback" ${a.on_failure === 'fallback' ? 'selected' : ''}>Fallback</option>
                            </select>
                        </div>
                        <div class="wh-field" style="flex:1;">
                            <label class="wh-field-label">Max Retries</label>
                            <input class="wh-input" id="wh-act-retries" type="number" min="0" value="${a.max_retries || 0}" />
                        </div>
                        <div class="wh-field" style="flex:1;">
                            <label class="wh-field-label">Timeout (s)</label>
                            <input class="wh-input" id="wh-act-timeout" type="number" min="1" value="${a.timeout || 30}" />
                        </div>
                    </div>
                    <div class="wh-checkbox-row">
                        <input type="checkbox" id="wh-act-capture" ${a.capture_response ? 'checked' : ''} onchange="document.getElementById('wh-act-varname').style.display=this.checked?'':'none'" />
                        <label for="wh-act-capture">Capture response</label>
                    </div>
                    <div class="wh-field" id="wh-act-varname" style="${a.capture_response ? '' : 'display:none'}">
                        <label class="wh-field-label">Response Variable</label>
                        <input class="wh-input" id="wh-act-resvar" value="${esc(a.response_variable || '')}" placeholder="e.g. review_result" />
                    </div>
                </div>
                <div class="wh-modal-footer">
                    <button class="wh-btn wh-btn-secondary" onclick="whCloseActionModal()">Cancel</button>
                    <button class="wh-btn wh-btn-primary" onclick="whSaveAction(${idx})">Done</button>
                </div>
            </div>
        </div>`;

        document.body.insertAdjacentHTML('beforeend', html);
    };

    window.whCloseActionModal = function() {
        const m = document.getElementById('wh-action-modal');
        if (m) m.remove();
    };

    window.whSaveAction = function(idx) {
        const action = _editActions[idx];
        if (!action) return;

        action.action_type = document.getElementById('wh-act-type').value;
        try {
            action.config = JSON.parse(document.getElementById('wh-act-config').value || '{}');
        } catch {
            if (typeof showToast === 'function') showToast('Invalid config JSON', 'error');
            return;
        }
        action.on_failure = document.getElementById('wh-act-failure').value;
        action.max_retries = parseInt(document.getElementById('wh-act-retries').value, 10) || 0;
        action.timeout = parseInt(document.getElementById('wh-act-timeout').value, 10) || 30;
        action.capture_response = document.getElementById('wh-act-capture').checked;
        action.response_variable = document.getElementById('wh-act-resvar')?.value || '';

        whCloseActionModal();
        renderActionsList();
    };

    // ── Pipeline Save ────────────────────────────────────────────────────

    window.whSavePipeline = async function(editId) {
        const name = document.getElementById('wh-pipe-name').value.trim();
        const description = document.getElementById('wh-pipe-desc').value.trim();
        const enabled = document.getElementById('wh-pipe-enabled').checked;

        if (!name) {
            if (typeof showToast === 'function') showToast('Pipeline name is required', 'warning');
            return;
        }

        const body = JSON.stringify({ name, description, enabled, actions: _editActions });

        try {
            if (editId) {
                await apiFetch(`/pipelines/${editId}`, { method: 'PUT', body });
            } else {
                await apiFetch('/pipelines', { method: 'POST', body });
            }
            if (typeof showToast === 'function') showToast(editId ? 'Pipeline updated' : 'Pipeline created', 'success');
            whCloseModal();
            await loadPipelines();
            render();
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
        }
    };

    window.whDeletePipeline = async function(id, name) {
        const linkedRules = _rules.filter(r => r.pipeline_id === id);
        let msg = `Delete pipeline "${name}"?`;
        if (linkedRules.length > 0) {
            msg += `\n\nWarning: ${linkedRules.length} rule(s) are linked to this pipeline.`;
        }
        if (!confirm(msg)) return;
        try {
            await apiFetch(`/pipelines/${id}`, { method: 'DELETE' });
            if (typeof showToast === 'function') showToast('Pipeline deleted', 'success');
            await loadPipelines();
            render();
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
        }
    };

})();
