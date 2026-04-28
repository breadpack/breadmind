package transport

import (
	"context"
	"sync"
	"time"

	"github.com/coder/websocket"
)

// wsConn adapts a coder/websocket connection to the session.Conn interface.
type wsConn struct {
	id string
	c  *websocket.Conn
	mu sync.Mutex
}

// newWSConn wraps c with the given connection id.
func newWSConn(id string, c *websocket.Conn) *wsConn {
	return &wsConn{id: id, c: c}
}

// ID returns the unique connection identifier.
func (w *wsConn) ID() string { return w.id }

// Send writes payload as a single text frame. Concurrent calls are serialised
// via the per-connection mutex (websocket.Conn requires writes be serialised).
func (w *wsConn) Send(payload []byte) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	return w.c.Write(ctx, websocket.MessageText, payload)
}

// Close shuts the connection with a normal-closure status code.
func (w *wsConn) Close() error {
	return w.c.Close(websocket.StatusNormalClosure, "close")
}
