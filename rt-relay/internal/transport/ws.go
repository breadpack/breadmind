package transport

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/coder/websocket"

	"github.com/breadpack/breadmind/rt-relay/internal/acl"
	"github.com/breadpack/breadmind/rt-relay/internal/auth"
	"github.com/breadpack/breadmind/rt-relay/internal/metrics"
	"github.com/breadpack/breadmind/rt-relay/internal/protocol"
	"github.com/breadpack/breadmind/rt-relay/internal/session"
)

// CoreClient is the narrow interface the WS handler needs from the BreadMind
// core: the ability to fetch missed events for a resume request, and the
// list of channels a user is permitted to observe (the per-connection ACL
// cache seed). The concrete implementation lives in package bus.
type CoreClient interface {
	BackfillSince(ctx context.Context, workspaceID, channelID string, sinceTsSeq int64, limit int) ([][]byte, error)
	VisibleChannels(ctx context.Context, workspaceID, userID string) ([]string, error)
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

	// Spec D5: fail-closed ACL fetch BEFORE upgrading. A missing core client
	// or any error from VisibleChannels short-circuits to 503 — the user gets
	// no WebSocket and therefore no ability to subscribe to anything they
	// cannot prove visibility of.
	if h.coreClient == nil {
		http.Error(w, "acl-unavailable", http.StatusServiceUnavailable)
		return
	}
	visible, err := h.coreClient.VisibleChannels(r.Context(), claims.WorkspaceID, claims.UserID)
	if err != nil {
		http.Error(w, "acl-unavailable", http.StatusServiceUnavailable)
		return
	}
	aclCache := acl.NewCacheFromSlice(visible)

	c, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
	if err != nil {
		return
	}
	defer c.Close(websocket.StatusInternalError, "closing")

	connID := claims.UserID + ":" + time.Now().UTC().Format(time.RFC3339Nano)
	conn := newWSConn(connID, claims.UserID, claims.WorkspaceID, c, aclCache)
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
		h.handleClientMessage(ctx, conn, claims, aclCache, payload)
	}
}

// handleClientMessage decodes a wire envelope and dispatches it to the right
// branch (subscribe / unsubscribe / ping / typing). Unknown types are silently
// ignored.
//
// aclCache is the per-connection visible-channels gate seeded by the
// connect-time VisibleChannels fetch. Subscribe rejects any channel not
// present in the cache. May be nil only for direct unit-test calls that
// don't exercise the Subscribe branch (e.g. typing-only tests); ServeHTTP
// always supplies a non-nil cache.
func (h *Handler) handleClientMessage(ctx context.Context, conn session.Conn, claims *auth.Claims, aclCache *acl.Cache, payload []byte) {
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
		// Per-channel resume: when ChannelResume[i] > 0, replay missed events
		// for ChannelIDs[i] BEFORE registering the subscription. This keeps
		// the wire ordering "history → ack → live": the client only starts
		// receiving live events after both the backfill replay completes
		// and the Subscribed ack is sent, since live fan-out only targets
		// connections registered in h.subs.
		//
		// ACL gate (spec D5): channels not in the per-connection visible set
		// are rejected with a TypeError envelope (code "acl_denied"); they are
		// neither backfilled nor subscribed. The Subscribed ack lists only
		// the channels that passed the gate.
		accepted := make([]string, 0, len(req.ChannelIDs))
		for i, ch := range req.ChannelIDs {
			if aclCache != nil && !aclCache.Has(ch) {
				errEnv, _ := json.Marshal(protocol.Envelope{
					Type: protocol.TypeError,
					Payload: mustMarshal(protocol.ErrorPayload{
						Code:    "acl_denied",
						Message: "not a member of channel " + ch,
					}),
				})
				_ = conn.Send(errEnv)
				continue
			}
			var since int64
			if i < len(req.ChannelResume) {
				since = req.ChannelResume[i]
			}
			if since > 0 && h.coreClient != nil {
				events, err := h.coreClient.BackfillSince(ctx, claims.WorkspaceID, ch, since, 500)
				if err == nil {
					for _, raw := range events {
						bp := protocol.BackfillPayload{
							ChannelID: ch,
							Event:     json.RawMessage(raw),
						}
						benv, _ := json.Marshal(protocol.Envelope{
							Type:    protocol.TypeBackfill,
							Payload: mustMarshal(bp),
						})
						_ = conn.Send(benv)
					}
				}
			}
			h.subs.Subscribe(conn.ID(), ch)
			accepted = append(accepted, ch)
		}
		ack, _ := json.Marshal(protocol.Envelope{
			Type:    protocol.TypeSubscribed,
			Payload: mustMarshal(protocol.SubscribedPayload{ChannelIDs: accepted}),
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

// envFactory implements acl.EnvelopeFactory. It serialises Revoked/Granted
// payloads into the wire envelope shape consumed by clients (Task 9, spec D7).
type envFactory struct{}

// Revoked builds a TypeChannelAccessRevoked envelope with the supplied reason.
func (envFactory) Revoked(channelID, reason string) []byte {
	p := protocol.ChannelAccessRevokedPayload{ChannelID: channelID, Reason: reason}
	b, _ := json.Marshal(protocol.Envelope{
		Type:    protocol.TypeChannelAccessRevoked,
		Payload: mustMarshal(p),
	})
	return b
}

// Granted builds a TypeChannelAccessGranted envelope.
func (envFactory) Granted(channelID string) []byte {
	p := protocol.ChannelAccessGrantedPayload{ChannelID: channelID}
	b, _ := json.Marshal(protocol.Envelope{
		Type:    protocol.TypeChannelAccessGranted,
		Payload: mustMarshal(p),
	})
	return b
}

// NewEnvelopeFactory returns an acl.EnvelopeFactory that produces wire
// envelopes for Revoked/Granted client events. Used by main.go to wire the
// ACL invalidation subscriber.
func NewEnvelopeFactory() acl.EnvelopeFactory { return envFactory{} }

// aclRegistry adapts *session.Registry to acl.ConnectionRegistry. session
// returns []session.Conn (interface), so the adapter narrows each entry by
// the public acl.ConnectionACL contract. Any future Conn impl satisfying that
// interface participates automatically.
type aclRegistry struct{ inner *session.Registry }

// NewACLRegistry returns an acl.ConnectionRegistry view of the given session
// registry. Used by main.go to wire the ACL invalidation subscriber.
func NewACLRegistry(reg *session.Registry) acl.ConnectionRegistry {
	return &aclRegistry{inner: reg}
}

func (r *aclRegistry) ConnsByUser(userID string) []acl.ConnectionACL {
	conns := r.inner.ConnsByUser(userID)
	out := make([]acl.ConnectionACL, 0, len(conns))
	for _, c := range conns {
		if a, ok := c.(acl.ConnectionACL); ok {
			out = append(out, a)
		}
	}
	return out
}

// Compile-time assertions: wsConn must satisfy acl.ConnectionACL (Task 9
// fan-out target) and session.UserScopedConn (per-user registry index).
var (
	_ acl.ConnectionACL      = (*wsConn)(nil)
	_ session.UserScopedConn = (*wsConn)(nil)
)
