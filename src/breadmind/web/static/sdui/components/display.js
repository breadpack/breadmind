// src/breadmind/web/static/sdui/components/display.js
import { html } from '../renderer.js';

function text(c) {
  return html`<p class="sdui-text" id=${c.id}>${c.props.value || ''}</p>`;
}

function heading(c) {
  const level = c.props.level || 2;
  const cls = `sdui-heading sdui-heading--h${level}`;
  const tag = `h${level}`;
  return html`<${tag} class=${cls} id=${c.id}>${c.props.value || ''}</${tag}>`;
}

function markdown(c) {
  // Phase 1: render as pre-formatted text. Real markdown parsing deferred.
  return html`<pre class="sdui-markdown" id=${c.id}>${c.props.value || ''}</pre>`;
}

function code(c) {
  return html`<pre class="sdui-code" id=${c.id}><code>${c.props.value || ''}</code></pre>`;
}

function badge(c) {
  const tone = c.props.tone || 'neutral';
  return html`<span class=${`sdui-badge sdui-badge--${tone}`} id=${c.id}>${c.props.value || ''}</span>`;
}

function progress(c) {
  const pct = Math.max(0, Math.min(100, c.props.value || 0));
  return html`<div class="sdui-progress" id=${c.id} style="background:var(--bg-2);border-radius:6px;overflow:hidden;height:8px">
    <div style=${`width:${pct}%;background:var(--accent);height:100%`}></div>
  </div>`;
}

function stat(c) {
  return html`<div class="sdui-stat" id=${c.id}>
    <div style="font-size:24px;font-weight:600">${c.props.value}</div>
    <div style="color:var(--fg-muted);font-size:12px">${c.props.label}</div>
  </div>`;
}

function divider(c) {
  return html`<hr class="sdui-divider" id=${c.id} style="border:0;border-top:1px solid var(--border)"/>`;
}

export default { text, heading, markdown, code, badge, progress, stat, divider };
