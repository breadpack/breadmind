// src/breadmind/web/static/sdui/ws.js
export class UIWebSocket {
  constructor(url, handlers) {
    this.url = url;
    this.handlers = handlers;
    this.ws = null;
    this.reconnectDelay = 1000;
    this.closed = false;
    this.connect();
  }

  connect() {
    if (this.closed) return;
    this.ws = new WebSocket(this.url);
    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      if (this.handlers.onOpen) this.handlers.onOpen();
    };
    this.ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (this.handlers.onMessage) this.handlers.onMessage(msg);
      } catch (err) {
        console.error('ws parse error', err);
      }
    };
    this.ws.onclose = () => {
      if (this.closed) return;
      setTimeout(() => this.connect(), this.reconnectDelay);
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
    };
    this.ws.onerror = (err) => console.error('ws error', err);
  }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
      return true;
    }
    return false;
  }

  close() {
    this.closed = true;
    if (this.ws) this.ws.close();
  }
}
