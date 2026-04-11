// src/breadmind/web/static/sdui/components/layout.js
import { html } from '../renderer.js';

function _variantClass(prefix, variant) {
  return variant ? `${prefix} ${prefix}--${variant}` : prefix;
}

function page(c, render, ctx) {
  const variant = c.props.variant;
  const cls = _variantClass('sdui-page', variant);
  return html`<div class=${cls} id=${c.id}>${c.children.map(ch => render(ch, ctx))}</div>`;
}

function stack(c, render, ctx) {
  const gap = c.props.gap || 'md';
  const variant = c.props.variant;
  const base = `sdui-stack sdui-stack--${gap}`;
  const cls = variant ? `${base} sdui-stack--${variant}` : base;
  return html`<div class=${cls} id=${c.id}>${c.children.map(ch => render(ch, ctx))}</div>`;
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
  // Render labelled tab pills with click-to-switch.
  // Each child stack/section becomes a tab panel; we read its first heading
  // (if any) as the tab label, falling back to the child's id.
  const panels = c.children.map((child, idx) => {
    let label = null;
    for (const grandchild of (child.children || [])) {
      if (grandchild.type === 'heading') {
        label = grandchild.props.value;
        break;
      }
    }
    return { idx, label: label || child.id || `Tab ${idx + 1}`, child };
  });

  // Active tab index is stored on the DOM element via data attribute and
  // mutated by hand (no Preact state to keep this stateless renderer simple).
  // Initial state: default_active prop (default 0).
  const initialActive = (c.props && c.props.default_active != null) ? c.props.default_active : 0;
  const tabsId = c.id;
  const onTabClick = (i) => (ev) => {
    ev.preventDefault();
    const root = document.getElementById(tabsId);
    if (!root) return;
    root.querySelectorAll('.sdui-tab-pill').forEach((el, j) => {
      el.classList.toggle('sdui-tab-pill--active', j === i);
    });
    root.querySelectorAll('.sdui-tab-panel').forEach((el, j) => {
      el.style.display = j === i ? '' : 'none';
    });
  };

  return html`<div class="sdui-tabs" id=${tabsId}>
    <div class="sdui-tabs__bar">
      ${panels.map(({ idx, label }) => html`
        <button type="button"
                class=${`sdui-tab-pill ${idx === initialActive ? 'sdui-tab-pill--active' : ''}`}
                onClick=${onTabClick(idx)}>${label}</button>
      `)}
    </div>
    <div class="sdui-tabs__panels">
      ${panels.map(({ idx, child }) => html`
        <div class="sdui-tab-panel" style=${idx === initialActive ? '' : 'display:none'}>
          ${render(child, ctx)}
        </div>
      `)}
    </div>
  </div>`;
}

export default { page, stack, grid, split, tabs };
