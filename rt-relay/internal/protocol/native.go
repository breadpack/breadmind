// Package protocol defines the JSON wire format for rt-relay WebSocket messages.
package protocol

import "encoding/json"

// Server → client event type constants.
const (
	TypeMessageCreated  = "message_created"
	TypeMessageUpdated  = "message_updated"
	TypeMessageDeleted  = "message_deleted"
	TypeReactionAdded   = "reaction_added"
	TypeReactionRemoved = "reaction_removed"
	TypePresenceChanged = "presence_changed"
	TypeTyping          = "typing"
	TypeTypingStopped   = "typing_stopped"
	TypeSubscribed      = "subscribed"
	TypeError           = "error"

	// Backfill replays a single historical envelope to the client during a
	// resume of an existing subscription. Streamed strictly before the
	// matching Subscribed ack so the client sees history → ack → live.
	TypeBackfill = "backfill"
	// ChannelAccessRevoked notifies the client that a channel previously
	// visible to this user is no longer accessible (membership/role change).
	TypeChannelAccessRevoked = "channel_access_revoked"
	// ChannelAccessGranted notifies the client that a new channel became
	// visible to this user.
	TypeChannelAccessGranted = "channel_access_granted"

	// Client → server command type constants.
	TypeSubscribe   = "subscribe"
	TypeUnsubscribe = "unsubscribe"
	TypePing        = "ping"
	TypePong        = "pong"
)

// Envelope is the outer wrapper for all WebSocket messages in both directions.
type Envelope struct {
	Type    string          `json:"type"`
	Payload json.RawMessage `json:"payload,omitempty"`
}

// SubscribeRequest is the payload for a client subscribe command.
//
// ChannelResume, when present, supplies a per-channel resume cursor that
// pairs positionally with ChannelIDs: ChannelResume[i] applies to
// ChannelIDs[i]. Index i is treated as "no resume" (live updates only) when
// either the slice is shorter than i+1 or ChannelResume[i] is zero.
//
// Note: zero is reserved as the no-resume sentinel — clients wanting full
// history-from-snapshot must omit the slice entry (or send an empty slice)
// rather than pass 0. Outbox ts_seq starts at 1 by schema invariant, so
// 0 is never a legitimate first-seen cursor.
type SubscribeRequest struct {
	ChannelIDs    []string `json:"channel_ids"`
	ChannelResume []int64  `json:"channel_resume,omitempty"`
}

// UnsubscribeRequest is the payload for a client unsubscribe command.
type UnsubscribeRequest struct {
	ChannelIDs []string `json:"channel_ids"`
}

// TypingRequest is the payload for a client typing command.
type TypingRequest struct {
	ChannelID string `json:"channel_id"`
}

// ErrorPayload is the payload for an error event sent to the client.
type ErrorPayload struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

// SubscribedPayload is the payload for a subscribed confirmation event.
type SubscribedPayload struct {
	ChannelIDs []string `json:"channel_ids"`
}

// PresenceChangedPayload is the payload for a presence_changed event.
type PresenceChangedPayload struct {
	UserID string `json:"user_id"`
	Status string `json:"status"`
}

// TypingPayload is the payload for server-side typing / typing_stopped events.
type TypingPayload struct {
	ChannelID string `json:"channel_id"`
	UserID    string `json:"user_id"`
}

// BackfillPayload wraps a single historical envelope replayed to the client
// in response to a resume request. Event is the original raw event JSON
// (e.g. a message_created envelope) preserved verbatim so the client can
// dispatch it through the same handler used for live events.
type BackfillPayload struct {
	ChannelID string          `json:"channel_id"`
	Event     json.RawMessage `json:"event"`
}

// ChannelAccessRevokedPayload is sent when a user loses visibility of a
// channel they were previously subscribed to (e.g. removed from a private
// channel). The client should drop any local state for this channel and
// stop expecting further events.
type ChannelAccessRevokedPayload struct {
	ChannelID string `json:"channel_id"`
	Reason    string `json:"reason,omitempty"`
}

// ChannelAccessGrantedPayload is sent when a user gains visibility of a
// new channel. The client may choose to subscribe to it.
type ChannelAccessGrantedPayload struct {
	ChannelID string `json:"channel_id"`
}
