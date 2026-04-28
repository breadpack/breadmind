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
