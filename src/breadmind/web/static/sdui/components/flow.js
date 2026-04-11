// src/breadmind/web/static/sdui/components/flow.js
import { html } from '../renderer.js';

/**
 * dag_view: layered DAG visualization with minimal topological layout.
 * Props:
 *   - nodes: [{ id, label, status }]
 *   - edges: [{ from, to }]
 */
function dag_view(c) {
  const { nodes = [], edges = [] } = c.props;
  if (nodes.length === 0) {
    return html`<div class="sdui-dag-view" id=${c.id}>
      <div style="color:var(--fg-muted);text-align:center;padding:24px">단계 없음</div>
    </div>`;
  }

  // Compute topological layers
  const incoming = {};
  nodes.forEach(n => { incoming[n.id] = 0; });
  edges.forEach(e => { if (incoming[e.to] !== undefined) incoming[e.to] += 1; });

  const layers = [];
  const visited = new Set();
  let frontier = nodes.filter(n => (incoming[n.id] || 0) === 0);
  while (frontier.length > 0) {
    layers.push(frontier);
    frontier.forEach(n => visited.add(n.id));
    const next = [];
    nodes.forEach(n => {
      if (visited.has(n.id)) return;
      const deps = edges.filter(e => e.to === n.id).map(e => e.from);
      if (deps.every(d => visited.has(d))) next.push(n);
    });
    if (next.length === 0) break;
    frontier = next;
  }

  // Any unvisited nodes (e.g., due to cycles) go in a final layer
  const unvisited = nodes.filter(n => !visited.has(n.id));
  if (unvisited.length > 0) layers.push(unvisited);

  return html`<div class="sdui-dag-view" id=${c.id}>
    ${layers.map(layer => html`
      <div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap">
        ${layer.map(node => html`
          <div style=${`padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:${_statusColor(node.status)};color:#fff;min-width:120px;text-align:center`}>
            <div style="font-weight:600">${node.label}</div>
            <div style="font-size:11px;opacity:0.8">${node.status}</div>
          </div>
        `)}
      </div>
    `)}
  </div>`;
}

function _statusColor(status) {
  return {
    pending: '#475569',
    queued: '#64748b',
    running: '#3b82f6',
    completed: '#10b981',
    failed: '#ef4444',
    skipped: '#94a3b8',
  }[status] || '#475569';
}

/**
 * step_card: single step detail card.
 * Props: step_id, title, status, tool, attempt, error, result
 */
function step_card(c) {
  const p = c.props;
  return html`<div class="sdui-step-card" id=${c.id}>
    <div class="sdui-step-card__title">${p.title || p.step_id}</div>
    <div class="sdui-step-card__meta">
      <span>status: ${p.status || 'unknown'}</span>
      ${p.tool ? html` · <span>tool: ${p.tool}</span>` : null}
      ${p.attempt ? html` · <span>attempt: ${p.attempt}</span>` : null}
    </div>
    ${p.error ? html`<div style="margin-top:8px;color:var(--danger);font-size:12px;white-space:pre-wrap">${p.error}</div>` : null}
  </div>`;
}

/**
 * log_stream: append-only log line viewer.
 * Props: lines: string[]
 */
function log_stream(c) {
  const lines = c.props.lines || [];
  return html`<div class="sdui-log-stream" id=${c.id} style="font-family:monospace;font-size:12px;background:#000;color:#0f0;padding:8px;border-radius:6px;max-height:240px;overflow:auto;white-space:pre">
    ${lines.length === 0
      ? html`<div style="color:#666">(로그 없음)</div>`
      : lines.map(line => html`<div>${line}</div>`)}
  </div>`;
}

/**
 * recovery_panel: displays recovery attempts for a failed step.
 * Props: attempts: [{ attempt, strategy, outcome, delay }]
 */
function recovery_panel(c) {
  const attempts = c.props.attempts || [];
  return html`<div class="sdui-recovery-panel" id=${c.id} style="border:1px solid var(--warning);padding:12px;border-radius:8px;background:var(--bg-2)">
    <div style="font-weight:600;margin-bottom:8px;color:var(--warning)">복구 시도</div>
    ${attempts.length === 0
      ? html`<div style="color:var(--fg-muted);font-size:12px">없음</div>`
      : attempts.map(a => html`
        <div style="font-size:12px;margin-bottom:4px">
          <strong>#${a.attempt}</strong> ${a.strategy} — ${a.outcome || '진행 중'}
          ${a.delay ? html` <span style="color:var(--fg-muted)">(delay: ${a.delay}s)</span>` : null}
        </div>
      `)}
  </div>`;
}

export default { dag_view, step_card, log_stream, recovery_panel };
