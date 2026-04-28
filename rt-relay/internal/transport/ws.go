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

// Handler serves the /ws WebSocket endpoint, authenticates the client via
// PASETO, and routes incoming protocol envelopes.
type Handler struct {
	verifier   *auth.Verifier
	registry   *session.Registry
	subs       *session.Subscription
	coreClient CoreClient
}

// NewHandler constructs a Handler from its dependencies.
func NewHandler(v *auth.Verifier, r *session.Registry, s *session.Subscription, c CoreClient) *Handler {
	return &Handler{verifier: v, registry: r, subs: s, coreClient: c}
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

	StartHeartbeat(ctx, 25*time.Second, func() error {
		return c.Ping(ctx)
	})

	for {
		_, payload, err := c.Read(ctx)
		if err != nil {
			return
		}
		h.handleClientMessage(ctx, conn, claims, payload)
	}
}

// handleClientMessage decodes a wire envelope and dispatches it to the right
// branch (subscribe / unsubscribe / ping). Unknown types are silently ignored.
func (h *Handler) handleClientMessage(ctx context.Context, conn session.Conn, claims *auth.Claims, payload []byte) {
	_ = ctx
	_ = claims
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
