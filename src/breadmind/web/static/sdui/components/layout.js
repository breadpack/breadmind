// src/breadmind/web/static/sdui/components/layout.js
import { html } from '../renderer.js';

function page(c, render, ctx) {
  return html`<div class="sdui-page" id=${c.id}>${c.children.map(ch => render(ch, ctx))}</div>`;
}

function stack(c, render, ctx) {
  const gap = c.props.gap || 'md';
  return html`<div class=${`sdui-stack sdui-stack--${gap}`} id=${c.id}>${c.children.map(ch => render(ch, ctx))}</div>`;
}

function grid(c, render, ctx) {
  const cols = c.props.cols || 2;
  const style = `display:grid;grid-template-columns:repeat(${cols},1fr);gap:var(--gap-md)`;
  return html`<div style=${style} id=${c.id}>${c.children.map(ch => render(ch, ctx))}</div>`;
}

function split(c, render, ctx) {
  return html`<div style="display:flex;gap:var(--gap-md)" id=${c.id}>${c.children.map(ch => html`<div style="flex:1">${render(ch, ctx)}</div>`)}</div>`;
}

function tabs(c, render, ctx) {
  return html`<div class="sdui-tabs" id=${c.id}>${c.children.map(ch => render(ch, ctx))}</div>`;
}

export default { page, stack, grid, split, tabs };
