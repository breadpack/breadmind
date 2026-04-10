// src/breadmind/web/static/sdui/main.js
import { h, render as preactRender } from 'preact';
import { useState, useEffect, useRef } from 'preact/hooks';
import htm from 'htm';
import { render as renderSpec } from './renderer.js';
import { UIWebSocket } from './ws.js';
import { applyPatch } from './patch.js';

const html = htm.bind(h);

function buildWsUrl() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const params = new URLSearchParams(location.search);
  const token = params.get('token');
  const user = params.get('user');
  let query = '';
  if (token) query = `?token=${encodeURIComponent(token)}`;
  else if (user) query = `?user=${encodeURIComponent(user)}`;
  return `${protocol}//${location.host}/ws/ui${query}`;
}

function App() {
  const [spec, setSpec] = useState(null);
  const [error, setError] = useState(null);
  const wsRef = useRef(null);

  useEffect(() => {
    const ws = new UIWebSocket(buildWsUrl(), {
      onOpen: () => {
        setError(null);
        ws.send({ type: 'view_request', view_key: 'chat_view', params: {} });
      },
      onMessage: (msg) => {
        if (msg.type === 'spec_full') {
          setSpec(msg.spec);
        } else if (msg.type === 'spec_patch') {
          setSpec((prev) => (prev ? applyPatch(prev, msg.patch) : prev));
        } else if (msg.type === 'view_changed') {
          setSpec(msg.spec);
        } else if (msg.type === 'action_result') {
          // Phase 1: no-op; could surface in a toast later
          console.debug('action_result', msg.result);
        }
      },
    });
    wsRef.current = ws;
    return () => ws.close();
  }, []);

  const ctx = {
    dispatch: (action) => wsRef.current && wsRef.current.send({ type: 'action', action }),
    requestView: (view_key, params) => wsRef.current && wsRef.current.send({
      type: 'view_request',
      view_key,
      params: params || {},
    }),
  };

  if (error) return html`<div class="sdui-page"><div class="sdui-unknown">${error}</div></div>`;
  if (!spec) return html`<div class="sdui-page">Loading…</div>`;

  return renderSpec(spec.root, ctx);
}

preactRender(html`<${App} />`, document.getElementById('root'));
