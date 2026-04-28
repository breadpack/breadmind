// Package dispatch fans out a Redis-delivered envelope payload to all live
// connections subscribed to the envelope's channel_id.
package dispatch

import (
	"encoding/json"

	"github.com/breadpack/breadmind/rt-relay/internal/protocol"
	"github.com/breadpack/breadmind/rt-relay/internal/session"
)

// ToSubscribers decodes a JSON envelope and Sends the original bytes to every
// live Conn currently subscribed to the envelope's payload.channel_id.
//
// Skips silently when:
//   - reg is nil
//   - payload is not a valid envelope JSON
//   - inner payload has no channel_id field
//   - a subscribed connID is no longer registered (race with disconnect)
func ToSubscribers(payload []byte, subs *session.Subscription, reg *session.Registry) {
	if reg == nil {
		return
	}
	var env protocol.Envelope
	if err := json.Unmarshal(payload, &env); err != nil {
		return
	}
	var meta struct {
		ChannelID string `json:"channel_id"`
	}
	_ = json.Unmarshal(env.Payload, &meta)
	if meta.ChannelID == "" {
		return
	}
	for _, connID := range subs.Subscribers(meta.ChannelID) {
		c, ok := reg.Get(connID)
		if !ok {
			continue
		}
		_ = c.Send(payload)
	}
}
