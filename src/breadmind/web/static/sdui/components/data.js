// src/breadmind/web/static/sdui/components/data.js
import { html } from '../renderer.js';

function table(c) {
  const { columns = [], rows = [] } = c.props;
  return html`<table class="sdui-table" id=${c.id} style="width:100%;border-collapse:collapse">
    <thead><tr>${columns.map(col => html`<th style="text-align:left;padding:8px;border-bottom:1px solid var(--border)">${col}</th>`)}</tr></thead>
    <tbody>${rows.map(row => html`<tr>${row.map(cell => html`<td style="padding:8px;border-bottom:1px solid var(--border)">${cell}</td>`)}</tr>`)}</tbody>
  </table>`;
}

function list(c, render, ctx) {
  return html`<div class="sdui-list" id=${c.id} style="display:flex;flex-direction:column;gap:8px;border:1px solid var(--border);border-radius:10px;padding:12px;background:var(--bg-2)">${c.children.map(ch => render(ch, ctx))}</div>`;
}

function tree(c, render, ctx) {
  return html`<ul class="sdui-tree" id=${c.id} style="list-style:none;padding-left:16px">${c.children.map(ch => html`<li>${render(ch, ctx)}</li>`)}</ul>`;
}

function timeline(c, render, ctx) {
  return html`<ol class="sdui-timeline" id=${c.id} style="list-style:none;padding:0">${c.children.map(ch => html`<li style="padding:8px 0 8px 16px;border-left:2px solid var(--border);margin-left:4px">${render(ch, ctx)}</li>`)}</ol>`;
}

function kv(c) {
  const items = c.props.items || [];
  return html`<dl class="sdui-kv" id=${c.id} style="display:grid;grid-template-columns:auto 1fr;gap:4px 16px;margin:0">
    ${items.map(({ key, value }) => html`<dt style="color:var(--fg-muted)">${key}</dt><dd style="margin:0">${value}</dd>`)}
  </dl>`;
}

export default { table, list, tree, timeline, kv };
