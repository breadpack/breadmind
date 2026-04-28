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
type SubscribeRequest struct {
	ChannelIDs []string `json:"channel_ids"`
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
