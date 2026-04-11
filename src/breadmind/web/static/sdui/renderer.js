// src/breadmind/web/static/sdui/renderer.js
import { h } from 'preact';
import htm from 'htm';
import COMPONENT_REGISTRY from './components/index.js';

export const html = htm.bind(h);

export function render(component, ctx) {
  if (!component || typeof component !== 'object') return null;
  const fn = COMPONENT_REGISTRY[component.type];
  if (!fn) {
    return html`<div class="sdui-unknown">Unknown component: ${component.type}</div>`;
  }
  return fn(component, render, ctx);
}
