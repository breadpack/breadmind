package transport

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/coder/websocket"

	"github.com/breadpack/breadmind/rt-relay/internal/auth"
	"github.com/breadpack/breadmind/rt-relay/internal/metrics"
	"github.com/breadpack/breadmind/rt-relay/internal/protocol"
	"github.com/breadpack/breadmind/rt-relay/internal/session"
)

// CoreClient is the narrow interface the WS handler needs from the BreadMind
// core: the ability to fetch missed events for a connection's resume request.
// The concrete implementation lives in package bus.
type CoreClient interface {
	BackfillSince(ctx context.Context, workspaceID, channelID string, sinceTsSeq int64, limit int) ([][]byte, error)
}

// TypingTracker records that a user is currently typing in a channel. The
// concrete implementation lives in package typing.
type TypingTracker interface {
	Mark(ctx context.Context, channelID, userID string) error
}

// Handler serves the /ws WebSocket endpoint, authenticates the client via
// PASETO, and routes incoming protocol envelopes.
type Handler struct {
	verifier        *auth.Verifier
	registry        *session.Registry
	subs            *session.Subscription
	coreClient      CoreClient
	typingTracker   TypingTracker
	heartbeatPeriod time.Duration
	idleTimeout     time.Duration
}

// NewHandler constructs a Handler from its dependencies.
//
// heartbeatPeriod controls the interval at which the server pings the client
// to keep NAT/intermediary connections alive (typically tens of seconds).
//
// idleTimeout bounds how long a single Read may block before the connection
// is torn down. The websocket library closes the connection when the per-Read
// context deadlines, so this acts as an "application-level activity required"
// floor: the client must send some app-level envelope (Ping, Subscribe, etc.)
// at least this often, otherwise the server will disconnect.
//
// WebSocket protocol-level pong responses to server pings do NOT count as
// activity for this purpose — only client-initiated application envelopes
// reset the deadline. A client that only answers protocol pings will be
// disconnected every idleTimeout seconds.
//
// Pass 0 to disable the per-Read timeout entirely; a genuinely silent client
// will then hold a goroutine until TCP keep-alive trips, which can be many
// minutes.
//
// tt is the typing tracker — when a client sends a TypeTyping envelope, the
// handler calls tt.Mark(ctx, channelID, userID). May be nil for tests; the
// branch is no-op when tracker is nil.
func NewHandler(
	v *auth.Verifier, r *session.Registry, s *session.Subscription, c CoreClient,
	tt TypingTracker,
	heartbeatPeriod, idleTimeout time.Duration,
) *Handler {
	return &Handler{
		verifier:        v,
		registry:        r,
		subs:            s,
		coreClient:      c,
		typingTracker:   tt,
		heartbeatPeriod: heartbeatPeriod,
		idleTimeout:     idleTimeout,
	}
}

// ServeHTTP implements http.Handler. It accepts WebSocket upgrades on /ws,
// verifies the PASETO supplied via ?token= or Authorization: Bearer <token>,
// registers the connection, and starts the read loop and heartbeat.
func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/ws" {
		http.NotFound(w, r)
		return
	}
	tok := r.URL.Query().Get("token")
	if tok == "" {
		tok = bearerFromHeader(r.Header.Get("Authorization"))
	}
	claims, err := h.verifier.Verify(tok)
	if err != nil {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	c, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
	if err != nil {
		return
	}
	defer c.Close(websocket.StatusInternalError, "closing")

	connID := claims.UserID + ":" + time.Now().UTC().Format(time.RFC3339Nano)
	conn := newWSConn(connID, c)
	h.registry.Add(connID, conn)
	metrics.ActiveConnections.Inc()
	defer metrics.ActiveConnections.Dec()
	defer func() {
		h.subs.RemoveAll(connID)
		h.registry.Remove(connID)
	}()

	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()

	StartHeartbeat(ctx, h.heartbeatPeriod, func() error {
		return c.Ping(ctx)
	})

	for {
		var readCtx context.Context = ctx
		var readCancel context.CancelFunc = func() {}
		if h.idleTimeout > 0 {
			readCtx, readCancel = context.WithTimeout(ctx, h.idleTimeout)
		}
		_, payload, err := c.Read(readCtx)
		readCancel()
		if err != nil {
			return
		}
		h.handleClientMessage(ctx, conn, claims, payload)
	}
}

// handleClientMessage decodes a wire envelope and dispatches it to the right
// branch (subscribe / unsubscribe / ping / typing). Unknown types are silently
// ignored.
func (h *Handler) handleClientMessage(ctx context.Context, conn session.Conn, claims *auth.Claims, payload []byte) {
	var env protocol.Envelope
	if err := json.Unmarshal(payload, &env); err != nil {
		return
	}
	switch env.Type {
	case protocol.TypeSubscribe:
		var req protocol.SubscribeRequest
		if err := json.Unmarshal(env.Payload, &req); err != nil {
			return
		}
		for _, ch := range req.ChannelIDs {
			h.subs.Subscribe(conn.ID(), ch)
		}
		ack, _ := json.Marshal(protocol.Envelope{
			Type:    protocol.TypeSubscribed,
			Payload: mustMarshal(protocol.SubscribedPayload{ChannelIDs: req.ChannelIDs}),
		})
		_ = conn.Send(ack)
	case protocol.TypeUnsubscribe:
		var req protocol.UnsubscribeRequest
		if err := json.Unmarshal(env.Payload, &req); err != nil {
			return
		}
		for _, ch := range req.ChannelIDs {
			h.subs.Unsubscribe(conn.ID(), ch)
		}
	case protocol.TypePing:
		ack, _ := json.Marshal(protocol.Envelope{Type: protocol.TypePong})
		_ = conn.Send(ack)
	case protocol.TypeTyping:
		var req protocol.TypingRequest
		if err := json.Unmarshal(env.Payload, &req); err != nil {
			return
		}
		if req.ChannelID == "" {
			return
		}
		if h.typingTracker == nil {
			return
		}
		_ = h.typingTracker.Mark(ctx, req.ChannelID, claims.UserID)
	}
}

func mustMarshal(v any) json.RawMessage {
	b, _ := json.Marshal(v)
	return b
}

func bearerFromHeader(h string) string {
	const p = "Bearer "
	if len(h) > len(p) && h[:len(p)] == p {
		return h[len(p):]
	}
	return ""
}
