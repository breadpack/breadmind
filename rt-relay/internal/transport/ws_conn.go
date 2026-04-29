package transport

import (
	"context"
	"sync"
	"time"

	"github.com/coder/websocket"

	"github.com/breadpack/breadmind/rt-relay/internal/acl"
)

// wsConn adapts a coder/websocket connection to the session.Conn interface.
//
// Each connection carries a per-connection ACL cache holding the channel IDs
// the authenticated user is permitted to observe at connect time. The cache
// is consulted as a fail-closed gate by Subscribe and is updated by Redis
// invalidation events (Task 9).
//
// userID + workspaceID are populated from the verified PASETO claims at
// register time. They are required by the ACL invalidation subscriber so the
// per-user fan-out (Task 9 KindA refetch / KindB cache mutation) can target
// the right connections — multi-workspace correctness is preserved by reading
// the workspace ID from each conn rather than a single relay-wide value.
type wsConn struct {
	id          string
	userID      string
	workspaceID string
	c           *websocket.Conn
	mu          sync.Mutex
	acl         *acl.Cache
}

// newWSConn wraps c with the given connection id and per-connection ACL
// cache. The acl argument must be non-nil — callers fail-closed BEFORE
// constructing the connection on missing ACL data. userID + workspaceID
// come from the PASETO claims of the verified token.
func newWSConn(id, userID, workspaceID string, c *websocket.Conn, aclCache *acl.Cache) *wsConn {
	return &wsConn{
		id:          id,
		userID:      userID,
		workspaceID: workspaceID,
		c:           c,
		acl:         aclCache,
	}
}

// ID returns the unique connection identifier.
func (w *wsConn) ID() string { return w.id }

// UserID returns the authenticated user id this connection belongs to.
func (w *wsConn) UserID() string { return w.userID }

// WorkspaceID returns the workspace id from the verified PASETO claims.
func (w *wsConn) WorkspaceID() string { return w.workspaceID }

// ACL returns the per-connection visible-channels cache.
func (w *wsConn) ACL() *acl.Cache { return w.acl }

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
