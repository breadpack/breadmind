/**
 * BreadMind Chat Module
 *
 * Handles WebSocket streaming, message rendering, tool indicators,
 * approval dialogs, and session management. Works with both v1
 * (non-streaming response) and v2 (StreamEvent) backends.
 */
class ChatApp {
    constructor() {
        this.ws = null;
        this.sessionId = 'default';
        this.messageContainer = null;
        this.inputField = null;
        this.sendButton = null;
        this.statusDot = null;
        this.statusText = null;
        this.statusBar = null;
        this.isStreaming = false;
        this.currentStreamBubble = null;
        this.currentStreamText = '';
        this.currentToolIndicator = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 3000;
        this.reconnectTimer = null;
    }

    /**
     * Initialize the chat app, bind DOM elements and connect.
     */
    init() {
        this.messageContainer = document.getElementById('messages');
        this.inputField = document.getElementById('messageInput');
        this.sendButton = document.getElementById('sendBtn');
        this.statusDot = document.getElementById('statusDot');
        this.statusText = document.getElementById('statusText');
        this.statusBar = document.getElementById('statusBar');

        // Bind input events
        this.inputField.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.send(this.inputField.value);
            }
        });
        this.sendButton.addEventListener('click', () => {
            this.send(this.inputField.value);
        });

        // Restore session
        const saved = localStorage.getItem('breadmind_session');
        if (saved) this.sessionId = saved;

        this.connect();
        this.loadSessions();
    }

    // ── WebSocket Connection ───────────────────────────────────────

    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${location.host}/ws/chat`);

        this.ws.onopen = () => {
            this.reconnectAttempts = 0;
            this._setConnectionStatus(true);
            this._removeReconnectOverlay();
            // Restore session on reconnect
            if (this.sessionId && this.sessionId !== 'default') {
                this.ws.send(JSON.stringify({
                    type: 'switch_session',
                    session_id: this.sessionId,
                }));
            }
        };

        this.ws.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                this.handleMessage(data);
            } catch (err) {
                console.error('Failed to parse WebSocket message:', err);
            }
        };

        this.ws.onclose = () => {
            this._setConnectionStatus(false);
            this._scheduleReconnect();
        };

        this.ws.onerror = () => {
            this._setConnectionStatus(false);
        };
    }

    _setConnectionStatus(connected) {
        if (this.statusDot) {
            this.statusDot.className = connected ? 'dot connected' : 'dot disconnected';
        }
        if (this.statusText) {
            this.statusText.textContent = connected ? 'Connected' : 'Disconnected';
        }
    }

    _scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            this._showReconnectOverlay('Connection lost. Please refresh the page.');
            return;
        }
        this.reconnectAttempts++;
        this._showReconnectOverlay(
            `Reconnecting... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`
        );
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(() => this.connect(), this.reconnectDelay);
    }

    _showReconnectOverlay(text) {
        let overlay = document.getElementById('reconnectOverlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'reconnectOverlay';
            overlay.className = 'reconnect-overlay';
            const chatArea = document.querySelector('.chat-area');
            if (chatArea) {
                chatArea.style.position = 'relative';
                chatArea.prepend(overlay);
            }
        }
        overlay.textContent = text;
    }

    _removeReconnectOverlay() {
        const overlay = document.getElementById('reconnectOverlay');
        if (overlay) overlay.remove();
    }

    // ── Message Sending ────────────────────────────────────────────

    send(text) {
        if (!text || !text.trim()) return;
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

        // Process quick actions if available
        if (typeof processQuickAction === 'function') {
            const processed = processQuickAction(text);
            if (processed) text = processed;
        }

        this.addUserMessage(text);
        this.ws.send(JSON.stringify({
            message: text.trim(),
            user: 'web_user',
            stream: true,
            session_id: this.sessionId,
        }));
        this.inputField.value = '';
        this.sendButton.disabled = true;
        this.sendButton.textContent = '...';
        this.createStreamBubble();
    }

    // ── StreamEvent Handler ────────────────────────────────────────

    handleMessage(data) {
        switch (data.type) {
            // ── v2 StreamEvent types ──
            case 'text':
                this.appendToStream(data.data);
                break;

            case 'tool_start':
                this.showToolIndicator(data.data);
                break;

            case 'tool_end':
                this.updateToolIndicator(data.data);
                break;

            case 'compact':
                // Compact event: context was truncated, no UI action needed
                break;

            case 'done':
                this.finalizeStream(data.data);
                break;

            case 'error':
                this._removeThinking();
                this.showError(typeof data.data === 'string' ? data.data : (data.message || 'Unknown error'));
                this._enableInput();
                break;

            // ── v1 legacy types ──
            case 'response':
                this._removeThinking();
                this._finishCurrentStream();
                this.addBotMessage(data.message);
                this._enableInput();
                this.loadSessions();
                // Auto-refresh personal tab
                if (typeof refreshPersonalTab === 'function') {
                    const resp = data.message || '';
                    const isPersonal = /할 일|일정|리마인더|Task|Event/i.test(resp);
                    if (isPersonal) setTimeout(() => refreshPersonalTab(), 500);
                }
                break;

            case 'progress':
                if (data.status === 'approval_request') {
                    this._removeThinking();
                    try {
                        const info = JSON.parse(data.detail);
                        this._showLegacyApproval(info.approval_id, info.tool, info.args);
                    } catch (e) {
                        console.error('Failed to parse approval_request:', e);
                    }
                } else {
                    this._showThinking(data.status, data.detail);
                }
                break;

            case 'session_history':
                this.messageContainer.innerHTML = '';
                if (data.messages && data.messages.length > 0) {
                    data.messages.forEach(m => {
                        if (m.role === 'user') this.addUserMessage(m.content, true);
                        else this.addBotMessage(m.content);
                    });
                } else {
                    this.addBotMessage('Start a new conversation!');
                }
                break;

            case 'session_created':
                this.sessionId = data.session_id;
                localStorage.setItem('breadmind_session', data.session_id);
                this.messageContainer.innerHTML = '';
                this.addBotMessage('New session started.');
                this.loadSessions();
                break;

            case 'notification':
                this.addBotMessage(data.message);
                break;

            case 'monitoring_event':
                if (data.event && data.event.type === 'behavior_prompt_updated') {
                    const el = document.getElementById('prompt-behavior');
                    if (el) el.value = data.event.prompt;
                    if (typeof showToast === 'function') {
                        showToast('Behavior prompt auto-improved: ' + (data.event.reason || ''), 'info');
                    }
                }
                if (typeof addMonitoringEvent === 'function') {
                    addMonitoringEvent(data.event);
                }
                break;

            case 'update_available':
                if (typeof showUpdateBanner === 'function' && data.event) {
                    showUpdateBanner(data.event.current, data.event.latest, '');
                }
                break;

            case 'messenger_connected':
                this.addBotMessage((data.event && data.event.platform || 'Messenger') + ' connected!');
                if (typeof showToast === 'function') {
                    showToast((data.event && data.event.platform || 'Messenger') + ' connected!', 'success');
                }
                break;

            case 'approval_requested':
                this.showApprovalDialog(data.data);
                break;

            default:
                // Handle coding job events
                if (data.type && data.type.startsWith('coding_job_')) {
                    if (typeof handleCodingJobEvent === 'function') {
                        handleCodingJobEvent(data);
                    }
                }
                break;
        }
    }

    // ── UI Rendering ───────────────────────────────────────────────

    addUserMessage(text, isHistory) {
        const div = document.createElement('div');
        div.className = 'message user';
        const time = new Date().toLocaleTimeString();
        const escaped = this._escapeHtml(text);
        const html = escaped.replace(
            /(https?:\/\/[^\s<]+)/g,
            '<a href="$1" target="_blank" style="color:#93c5fd;">$1</a>'
        );
        div.innerHTML = `<div class="bubble">${html}</div><div class="meta">You &middot; ${time}</div>`;
        this.messageContainer.appendChild(div);
        if (!isHistory) this._scrollToBottom();
    }

    addBotMessage(text) {
        if (!text || !text.trim()) return;
        const div = document.createElement('div');
        div.className = 'message bot';
        const time = new Date().toLocaleTimeString();
        const html = this.renderMarkdown(text);
        div.innerHTML = `<div class="bubble">${html}</div><div class="meta">BreadMind &middot; ${time}</div>`;
        this._enhanceCodeBlocks(div);
        this.messageContainer.appendChild(div);
        this._scrollToBottom();
    }

    createStreamBubble() {
        this._removeThinking();
        this.isStreaming = true;
        this.currentStreamText = '';

        const div = document.createElement('div');
        div.className = 'message bot';
        div.id = 'stream-message';

        const bubble = document.createElement('div');
        bubble.className = 'bubble streaming';
        bubble.innerHTML = '<div class="typing-indicator"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>';
        div.appendChild(bubble);

        const meta = document.createElement('div');
        meta.className = 'meta';
        meta.textContent = 'BreadMind';
        div.appendChild(meta);

        this.currentStreamBubble = bubble;
        this.messageContainer.appendChild(div);
        this._scrollToBottom();
    }

    appendToStream(chunk) {
        if (!chunk) return;

        if (!this.currentStreamBubble) {
            this.createStreamBubble();
        }

        // Remove typing indicator on first chunk
        const typing = this.currentStreamBubble.querySelector('.typing-indicator');
        if (typing) typing.remove();

        this.currentStreamText += chunk;
        this.currentStreamBubble.innerHTML = this.renderMarkdown(this.currentStreamText);
        this.currentStreamBubble.classList.add('streaming');
        this._scrollToBottom();
    }

    finalizeStream(data) {
        if (this.currentStreamBubble) {
            this.currentStreamBubble.classList.remove('streaming');
            // Re-render final markdown and enhance code blocks
            if (this.currentStreamText) {
                this.currentStreamBubble.innerHTML = this.renderMarkdown(this.currentStreamText);
                this._enhanceCodeBlocks(this.currentStreamBubble.closest('.message'));
            }

            // Add time meta
            const msg = this.currentStreamBubble.closest('.message');
            if (msg) {
                const meta = msg.querySelector('.meta');
                const time = new Date().toLocaleTimeString();
                if (meta) meta.textContent = `BreadMind \u00B7 ${time}`;
            }
        }

        this.isStreaming = false;
        this.currentStreamBubble = null;
        this.currentStreamText = '';
        this.currentToolIndicator = null;

        this._enableInput();
        this.loadSessions();

        // Update status bar
        if (data && this.statusBar) {
            this._updateStatusBar(data);
        }
    }

    _finishCurrentStream() {
        if (this.currentStreamBubble) {
            this.currentStreamBubble.classList.remove('streaming');
            if (!this.currentStreamText) {
                // Empty stream bubble - remove it
                const msg = this.currentStreamBubble.closest('.message');
                if (msg) msg.remove();
            }
        }
        this.isStreaming = false;
        this.currentStreamBubble = null;
        this.currentStreamText = '';
        this.currentToolIndicator = null;
    }

    // ── Tool Execution Visualization ───────────────────────────────

    showToolIndicator(data) {
        if (!data || !data.tools) return;

        const indicator = document.createElement('div');
        indicator.className = 'tool-indicator';
        indicator.id = 'current-tool-indicator';
        indicator.innerHTML = `
            <span class="spinner"></span>
            <span>Running: </span>
            <span class="tool-names">${this._escapeHtml(data.tools.join(', '))}</span>
        `;

        // Insert inside the stream message or at the end
        const streamMsg = document.getElementById('stream-message');
        if (streamMsg) {
            const meta = streamMsg.querySelector('.meta');
            streamMsg.insertBefore(indicator, meta);
        } else {
            this.messageContainer.appendChild(indicator);
        }

        this.currentToolIndicator = indicator;
        this._scrollToBottom();
    }

    updateToolIndicator(data) {
        if (!this.currentToolIndicator) return;

        const results = (data && data.results) || [];
        const container = document.createElement('div');

        results.forEach(r => {
            const details = document.createElement('details');
            details.className = 'tool-result';

            const summary = document.createElement('summary');
            if (!r.success) summary.classList.add('failed');
            const icon = r.success ? '\u2713' : '\u2717';
            summary.innerHTML = `${icon} ${this._escapeHtml(r.name)}`;
            details.appendChild(summary);

            container.appendChild(details);
        });

        this.currentToolIndicator.replaceWith(container);
        this.currentToolIndicator = null;
        this._scrollToBottom();
    }

    // ── Approval Dialog ────────────────────────────────────────────

    showApprovalDialog(data) {
        if (!data) return;
        const requestId = data.request_id || data.approval_id || '';
        const toolName = data.tool || data.tool_name || 'unknown';
        const reason = data.reason || 'Approval required for this action';
        const args = data.args || data.arguments || {};

        const div = document.createElement('div');
        div.className = 'approval-dialog';
        div.id = `approval-${requestId}`;
        div.innerHTML = `
            <div class="approval-header">
                \u26A0\uFE0F Approval required: ${this._escapeHtml(toolName)}
            </div>
            <div class="approval-reason">${this._escapeHtml(reason)}</div>
            ${Object.keys(args).length > 0 ? `<div style="font-size:11px;color:#64748b;margin-bottom:8px;font-family:monospace;">${this._escapeHtml(JSON.stringify(args, null, 2))}</div>` : ''}
            <div class="approval-actions">
                <button class="btn-approve" data-id="${this._escapeHtml(requestId)}">Approve</button>
                <button class="btn-deny" data-id="${this._escapeHtml(requestId)}">Deny</button>
            </div>
        `;

        // Bind buttons
        div.querySelector('.btn-approve').addEventListener('click', () => {
            this._sendApprovalResponse(requestId, true, div);
        });
        div.querySelector('.btn-deny').addEventListener('click', () => {
            this._sendApprovalResponse(requestId, false, div);
        });

        // Insert in stream message or at the end
        const streamMsg = document.getElementById('stream-message');
        if (streamMsg) {
            const meta = streamMsg.querySelector('.meta');
            streamMsg.insertBefore(div, meta);
        } else {
            this.messageContainer.appendChild(div);
        }
        this._scrollToBottom();
    }

    _sendApprovalResponse(requestId, approved, dialogEl) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'approval_response',
                request_id: requestId,
                approved: approved,
            }));
        }

        // Also try the REST endpoint (v1 compatibility)
        const action = approved ? 'approve' : 'deny';
        fetch(`/api/approvals/${requestId}/${action}`, { method: 'POST' }).catch(() => {});

        // Update UI
        const actions = dialogEl.querySelector('.approval-actions');
        if (actions) {
            actions.innerHTML = `<span style="color:${approved ? '#86efac' : '#fca5a5'};font-size:12px;">${approved ? '\u2705 Approved' : '\u274C Denied'}</span>`;
        }
    }

    // ── Legacy v1 Compatibility ────────────────────────────────────

    _showThinking(status, detail) {
        let label = '\uD83D\uDCAD Thinking...';
        if (status === 'tool_call' && detail) {
            label = '\uD83D\uDD27 ' + detail;
        } else if (status === 'thinking') {
            label = '\uD83D\uDCAD Thinking...';
        }
        const el = document.getElementById('thinking-msg');
        if (el) {
            el.querySelector('.label').textContent = label;
        } else {
            const div = document.createElement('div');
            div.className = 'message bot';
            div.id = 'thinking-msg';
            div.innerHTML = '<div class="thinking-indicator"><div class="dots"><span></span><span></span><span></span></div><span class="label">' + this._escapeHtml(label) + '</span></div>';
            this.messageContainer.appendChild(div);
        }
        this._scrollToBottom();
    }

    _removeThinking() {
        const el = document.getElementById('thinking-msg');
        if (el) el.remove();
    }

    _showLegacyApproval(approvalId, toolName, args) {
        this.showApprovalDialog({
            approval_id: approvalId,
            tool: toolName,
            args: args,
        });
    }

    // ── Markdown Rendering (Vanilla) ───────────────────────────────

    renderMarkdown(text) {
        if (!text) return '';

        // If marked.js is loaded (CDN in index.html), use it
        if (typeof marked !== 'undefined') {
            try {
                return marked.parse(text);
            } catch (e) {
                // Fallback to simple renderer
            }
        }

        // Simple vanilla markdown renderer
        let html = this._escapeHtml(text);

        // Code blocks: ```lang\n...\n```
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
            const langAttr = lang ? ` data-lang="${lang}"` : '';
            return `<pre${langAttr}><code>${code}</code></pre>`;
        });

        // Inline code: `code`
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Bold: **text**
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

        // Italic: *text*
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        // Headers: # text
        html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

        // Links: [text](url)
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

        // Unordered list items: - item
        html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

        // Blockquotes: > text
        html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

        // Line breaks
        html = html.replace(/\n/g, '<br>');

        return html;
    }

    // ── Session Management ─────────────────────────────────────────

    async loadSessions() {
        try {
            const resp = await fetch('/api/sessions');
            const data = await resp.json();
            const list = document.getElementById('sessionList');
            if (!list) return;

            if (!data.sessions || data.sessions.length === 0) {
                list.innerHTML = '<div class="tool-item" style="color:#64748b;font-size:11px;">No sessions yet</div>';
                return;
            }

            list.innerHTML = data.sessions.map(s => {
                const sid = s.session_id.replace('web:', '');
                const isActive = sid === this.sessionId;
                const title = s.title || 'Untitled';
                const time = new Date(s.last_active).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                return `<div class="tool-item" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;${isActive ? 'background:#334155;border-radius:4px;' : ''}" data-session="${sid}">
                    <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;${isActive ? 'color:#60a5fa;' : ''}">${this._escapeHtml(title)}</span>
                    <span style="font-size:10px;color:#64748b;margin-left:4px;flex-shrink:0;">${time}</span>
                    <span class="session-delete" data-delete-session="${sid}" title="Delete" style="margin-left:4px;color:#64748b;font-size:12px;cursor:pointer;opacity:0.5;flex-shrink:0;">\u2715</span>
                </div>`;
            }).join('');

            // Bind click handlers
            list.querySelectorAll('[data-session]').forEach(el => {
                el.addEventListener('click', (e) => {
                    if (e.target.dataset.deleteSession) return;
                    this.switchSession(el.dataset.session);
                });
            });
            list.querySelectorAll('[data-delete-session]').forEach(el => {
                el.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.deleteSession(el.dataset.deleteSession);
                });
            });
        } catch (e) {
            // Silently fail
        }
    }

    switchSession(sessionId) {
        this.sessionId = sessionId;
        localStorage.setItem('breadmind_session', sessionId);
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'switch_session',
                session_id: sessionId,
            }));
        }
        this.loadSessions();
    }

    newSession() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'new_session' }));
        }
    }

    async deleteSession(sessionId) {
        try {
            await fetch('/api/sessions/' + sessionId, { method: 'DELETE' });
            if (this.sessionId === sessionId) {
                this.newSession();
            }
            this.loadSessions();
        } catch (e) {
            // Silently fail
        }
    }

    async clearAllSessions() {
        if (!confirm('Delete all sessions?')) return;
        try {
            const resp = await fetch('/api/sessions');
            const data = await resp.json();
            for (const s of (data.sessions || [])) {
                const sid = s.session_id.replace('web:', '');
                await fetch('/api/sessions/' + sid, { method: 'DELETE' });
            }
            this.newSession();
            this.loadSessions();
        } catch (e) {
            // Silently fail
        }
    }

    // ── Error Display ──────────────────────────────────────────────

    showError(message) {
        this._finishCurrentStream();
        const div = document.createElement('div');
        div.className = 'message bot';
        const time = new Date().toLocaleTimeString();
        div.innerHTML = `<div class="bubble" style="border-color:#ef4444;color:#fca5a5;">\u26A0\uFE0F ${this._escapeHtml(message)}</div><div class="meta">Error &middot; ${time}</div>`;
        this.messageContainer.appendChild(div);
        this._scrollToBottom();
    }

    // ── Status Bar ─────────────────────────────────────────────────

    _updateStatusBar(data) {
        if (!this.statusBar) return;
        const items = [];
        items.push(`<span class="status-item"><span class="label">Session:</span> <span class="value">${this._escapeHtml(this.sessionId)}</span></span>`);
        if (data.tokens !== undefined) {
            items.push(`<span class="status-item"><span class="label">Tokens:</span> <span class="value">${data.tokens.toLocaleString()}</span></span>`);
        }
        if (data.tool_calls !== undefined) {
            items.push(`<span class="status-item"><span class="label">Tools:</span> <span class="value">${data.tool_calls}</span></span>`);
        }
        if (data.cost) {
            items.push(`<span class="status-item"><span class="label">Cost:</span> <span class="value">${this._escapeHtml(data.cost)}</span></span>`);
        }
        this.statusBar.innerHTML = items.join('');
    }

    // ── Utility ────────────────────────────────────────────────────

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    _scrollToBottom() {
        this.messageContainer.scrollTop = this.messageContainer.scrollHeight;
    }

    _enableInput() {
        this.sendButton.disabled = false;
        this.sendButton.textContent = 'Send';
    }

    _enhanceCodeBlocks(container) {
        if (!container) return;
        container.querySelectorAll('pre code').forEach(block => {
            const pre = block.closest('pre');
            if (!pre) return;
            const lang = (block.className.match(/language-(\w+)/) || [])[1] || '';
            if (lang) pre.setAttribute('data-lang', lang);

            // Add copy button
            if (!pre.querySelector('.copy-btn')) {
                const btn = document.createElement('button');
                btn.className = 'copy-btn';
                btn.textContent = 'Copy';
                btn.addEventListener('click', () => {
                    navigator.clipboard.writeText(block.textContent);
                    btn.textContent = 'Copied!';
                    setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
                });
                pre.style.position = 'relative';
                pre.appendChild(btn);
            }
        });

        // Render mermaid diagrams if available
        if (typeof mermaid !== 'undefined') {
            container.querySelectorAll('pre code.language-mermaid').forEach(block => {
                const mermaidDiv = document.createElement('div');
                mermaidDiv.className = 'mermaid';
                mermaidDiv.textContent = block.textContent;
                block.closest('pre').replaceWith(mermaidDiv);
            });
            try {
                mermaid.run({ nodes: container.querySelectorAll('.mermaid') });
            } catch (e) {
                // Silently fail
            }
        }
    }
}

// ── Global instance & backward-compatible functions ────────────────

const chatApp = new ChatApp();

// Expose global functions for inline onclick handlers in index.html
function sendMessage() { chatApp.send(chatApp.inputField.value); }
function newSession() { chatApp.newSession(); }
function switchSession(id) { chatApp.switchSession(id); }
function deleteSession(id) { chatApp.deleteSession(id); }
function clearAllSessions() { chatApp.clearAllSessions(); }
function loadSessions() { chatApp.loadSessions(); }
function addMessage(text, type) {
    if (type === 'user') chatApp.addUserMessage(text);
    else chatApp.addBotMessage(text);
}
function escapeHtml(t) { return chatApp._escapeHtml(t); }
function showThinking(status, detail) { chatApp._showThinking(status, detail); }
function removeThinking() { chatApp._removeThinking(); }
function showApprovalCard(id, tool, args) { chatApp._showLegacyApproval(id, tool, args); }
function chatApproval(id, action) {
    const approved = action === 'approve';
    const el = document.getElementById('approval-' + id);
    if (el) {
        const actions = el.querySelector('.approval-actions') || el.querySelector('.approval-btns');
        if (actions) {
            actions.innerHTML = '<span style="color:' + (approved ? '#86efac' : '#fca5a5') + ';font-size:12px;">' + (approved ? '\u2705 Approved' : '\u274C Denied') + '</span>';
        }
    }
    fetch('/api/approvals/' + id + '/' + action, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (action === 'approve' && data.followup) {
                addMessage(data.followup, 'bot');
            } else if (action === 'approve' && data.result && data.result.output) {
                addMessage(data.result.output, 'bot');
            }
        })
        .catch(err => {
            console.error('Approval failed:', err);
            if (el) {
                const actions = el.querySelector('.approval-actions') || el.querySelector('.approval-btns');
                if (actions) actions.innerHTML = '<span style="color:#fca5a5;font-size:12px;">\u26A0\uFE0F Error</span>';
            }
        });
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    chatApp.init();
});
