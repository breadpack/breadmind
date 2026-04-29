package acl

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/redis/go-redis/v9"
)

// Kind discriminates the granularity of an ACL invalidation event.
//
//   - KindB ("B-granular") targets a single (user, channel, op) tuple. The
//     subscriber updates the per-connection cache in place via Add or Remove
//     and emits a single Revoked or Granted envelope when the cache state
//     actually changed.
//   - KindA ("A-granular") targets a single user with no channel scope. The
//     subscriber refetches the full visible set via VisibleFetcher and applies
//     the diff via Cache.Replace, emitting one envelope per added/removed id.
//
// See spec D6 (granularity) + D7 (client envelopes) for the contract.
type Kind int

const (
	KindB Kind = iota // per-(user, channel)
	KindA             // per-user
)

// Event is a parsed ACL invalidation event lifted off a Redis pub/sub message.
type Event struct {
	Kind      Kind
	UserID    string
	ChannelID string // KindB only
	Op        string // KindB only: "add" or "remove"
}

// ParseInvalidation parses a Redis pub/sub channel name into an Event.
//
// Accepted shapes:
//   - acl:invalidate:user:<uid>                       → KindA
//   - acl:invalidate:user:<uid>:channel:<cid>:add     → KindB
//   - acl:invalidate:user:<uid>:channel:<cid>:remove  → KindB
//
// Any other shape returns an error and should be ignored by the caller.
func ParseInvalidation(channel string) (Event, error) {
	parts := strings.Split(channel, ":")
	if len(parts) < 4 || parts[0] != "acl" || parts[1] != "invalidate" || parts[2] != "user" {
		return Event{}, fmt.Errorf("invalid acl invalidation channel: %s", channel)
	}
	if len(parts) == 4 {
		if parts[3] == "" {
			return Event{}, errors.New("malformed acl invalidation channel: empty user id")
		}
		return Event{Kind: KindA, UserID: parts[3]}, nil
	}
	if len(parts) == 7 && parts[4] == "channel" {
		op := parts[6]
		if op != "add" && op != "remove" {
			return Event{}, fmt.Errorf("invalid op: %s", op)
		}
		if parts[3] == "" || parts[5] == "" {
			return Event{}, errors.New("malformed acl invalidation channel: empty user or channel id")
		}
		return Event{Kind: KindB, UserID: parts[3], ChannelID: parts[5], Op: op}, nil
	}
	return Event{}, errors.New("malformed acl invalidation channel: " + channel)
}

// Handler processes parsed Events. Implementations dispatch to per-user
// connections via the session.Registry.
type Handler interface {
	HandleEvent(ctx context.Context, ev Event)
}

// Subscribe runs a PSUBSCRIBE goroutine on `acl:invalidate:*` and dispatches
// parsed events to handler. It returns a cancel function that stops the
// goroutine and closes the Redis subscription.
//
// The goroutine exits on (a) the returned cancel being invoked, (b) the
// parent ctx being cancelled, or (c) the Redis channel closing (e.g. on
// connection loss). Malformed pub/sub channel names are silently dropped.
func Subscribe(ctx context.Context, rdb *redis.Client, handler Handler) func() {
	sub := rdb.PSubscribe(ctx, "acl:invalidate:*")
	cctx, cancel := context.WithCancel(ctx)
	go func() {
		defer sub.Close()
		ch := sub.Channel()
		for {
			select {
			case <-cctx.Done():
				return
			case msg, ok := <-ch:
				if !ok {
					return
				}
				ev, err := ParseInvalidation(msg.Channel)
				if err != nil {
					continue
				}
				handler.HandleEvent(cctx, ev)
			}
		}
	}()
	return cancel
}

// ConnectionACL is the narrow interface the handler needs to update a
// connection's ACL set and emit envelopes. wsConn satisfies it.
type ConnectionACL interface {
	ID() string
	UserID() string
	WorkspaceID() string
	ACL() *Cache
	Send(envelope []byte) error
}

// ConnectionRegistry yields connections by user id.
type ConnectionRegistry interface {
	ConnsByUser(userID string) []ConnectionACL
}

// VisibleFetcher refetches the user's full visible set (used for KindA).
type VisibleFetcher interface {
	VisibleChannels(ctx context.Context, workspaceID, userID string) ([]string, error)
}

// EnvelopeFactory builds Revoked/Granted envelopes. Pass-through to protocol package.
type EnvelopeFactory interface {
	Revoked(channelID, reason string) []byte
	Granted(channelID string) []byte
}

// connectionsHandler wires Events into per-connection cache mutations and
// outbound client envelopes.
//
// Design note: workspace ID is read per-conn (c.WorkspaceID()) rather than
// passed as a single relay-wide value, so the handler is multi-workspace
// correct. A user with active sessions in two workspaces — already
// representable by two PASETO tokens carrying different `wid` claims — gets
// its KindA refetch issued against each session's own workspace, not a
// single hard-coded one.
type connectionsHandler struct {
	reg     ConnectionRegistry
	visible VisibleFetcher
	envs    EnvelopeFactory
}

// NewConnectionsHandler builds a Handler that updates per-connection ACL
// caches and pushes Revoked/Granted envelopes in response to invalidation
// events. reg returns the live connections for a user; visible is used to
// refetch the full visible set for KindA events; envs builds the outbound
// envelopes.
func NewConnectionsHandler(reg ConnectionRegistry, visible VisibleFetcher, envs EnvelopeFactory) Handler {
	return &connectionsHandler{reg: reg, visible: visible, envs: envs}
}

func (h *connectionsHandler) HandleEvent(ctx context.Context, ev Event) {
	conns := h.reg.ConnsByUser(ev.UserID)
	if len(conns) == 0 {
		return
	}
	switch ev.Kind {
	case KindB:
		for _, c := range conns {
			switch ev.Op {
			case "remove":
				if c.ACL().Remove(ev.ChannelID) {
					_ = c.Send(h.envs.Revoked(ev.ChannelID, "acl_revoked"))
				}
			case "add":
				if c.ACL().Add(ev.ChannelID) {
					_ = c.Send(h.envs.Granted(ev.ChannelID))
				}
			}
		}
	case KindA:
		for _, c := range conns {
			ids, err := h.visible.VisibleChannels(ctx, c.WorkspaceID(), ev.UserID)
			if err != nil {
				continue
			}
			added, removed := c.ACL().Replace(ids)
			for _, id := range added {
				_ = c.Send(h.envs.Granted(id))
			}
			for _, id := range removed {
				_ = c.Send(h.envs.Revoked(id, "acl_revoked"))
			}
		}
	}
}
