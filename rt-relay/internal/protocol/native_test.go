package protocol

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestEnvelope_RoundTrip(t *testing.T) {
	env := Envelope{
		Type:    "message_created",
		Payload: json.RawMessage(`{"channel_id":"c1","ts_seq":42}`),
	}
	b, err := json.Marshal(env)
	assert.NoError(t, err)

	var got Envelope
	assert.NoError(t, json.Unmarshal(b, &got))
	assert.Equal(t, "message_created", got.Type)
}

func TestSubscribeRequest_Parse(t *testing.T) {
	raw := `{"type":"subscribe","payload":{"channel_ids":["c1","c2"]}}`
	var env Envelope
	assert.NoError(t, json.Unmarshal([]byte(raw), &env))
	assert.Equal(t, "subscribe", env.Type)

	var req SubscribeRequest
	assert.NoError(t, json.Unmarshal(env.Payload, &req))
	assert.Equal(t, []string{"c1", "c2"}, req.ChannelIDs)
}

// TestSubscribeRequest_WithResume verifies the per-channel resume cursor
// parses and pairs positionally with ChannelIDs.
func TestSubscribeRequest_WithResume(t *testing.T) {
	raw := `{"channel_ids":["c1","c2"],"channel_resume":[100,200]}`
	var req SubscribeRequest
	assert.NoError(t, json.Unmarshal([]byte(raw), &req))
	assert.Equal(t, []string{"c1", "c2"}, req.ChannelIDs)
	assert.Equal(t, []int64{100, 200}, req.ChannelResume)
}

// TestSubscribeRequest_NoResume verifies that omitting channel_resume
// leaves the slice empty (live-only subscribe — the prior wire format).
func TestSubscribeRequest_NoResume(t *testing.T) {
	raw := `{"channel_ids":["c1"]}`
	var req SubscribeRequest
	assert.NoError(t, json.Unmarshal([]byte(raw), &req))
	assert.Equal(t, []string{"c1"}, req.ChannelIDs)
	assert.Empty(t, req.ChannelResume)
}

// TestBackfillPayload_Roundtrip verifies a backfill envelope preserves
// the inner event JSON byte-for-byte through a marshal/unmarshal cycle.
func TestBackfillPayload_Roundtrip(t *testing.T) {
	p := BackfillPayload{
		ChannelID: "c1",
		Event:     json.RawMessage(`{"id":"m1","type":"message_created"}`),
	}
	b, err := json.Marshal(p)
	assert.NoError(t, err)

	var got BackfillPayload
	assert.NoError(t, json.Unmarshal(b, &got))
	assert.Equal(t, "c1", got.ChannelID)
	assert.JSONEq(t, `{"id":"m1","type":"message_created"}`, string(got.Event))
}
