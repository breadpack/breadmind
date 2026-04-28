package dispatch_test

import (
	"encoding/json"
	"sync"
	"testing"

	"github.com/breadpack/breadmind/rt-relay/internal/dispatch"
	"github.com/breadpack/breadmind/rt-relay/internal/protocol"
	"github.com/breadpack/breadmind/rt-relay/internal/session"
	"github.com/stretchr/testify/assert"
)

// mockConn satisfies session.Conn and records sent payloads.
type mockConn struct {
	id   string
	mu   sync.Mutex
	sent [][]byte
}

func (m *mockConn) ID() string   { return m.id }
func (m *mockConn) Close() error { return nil }
func (m *mockConn) Send(p []byte) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sent = append(m.sent, append([]byte(nil), p...))
	return nil
}

func envelopeWith(t *testing.T, channelID string) []byte {
	t.Helper()
	inner := map[string]string{"channel_id": channelID, "message_id": "m1"}
	payload, _ := json.Marshal(inner)
	env := protocol.Envelope{Type: protocol.TypeMessageCreated, Payload: payload}
	out, _ := json.Marshal(env)
	return out
}

func TestToSubscribers_FanOut(t *testing.T) {
	reg := session.NewRegistry()
	subs := session.NewSubscription()
	a := &mockConn{id: "a"}
	b := &mockConn{id: "b"}
	reg.Add(a.ID(), a)
	reg.Add(b.ID(), b)
	subs.Subscribe("a", "ch1")
	subs.Subscribe("b", "ch1")

	payload := envelopeWith(t, "ch1")
	dispatch.ToSubscribers(payload, subs, reg)

	assert.Equal(t, 1, len(a.sent))
	assert.Equal(t, 1, len(b.sent))
	assert.Equal(t, payload, a.sent[0])
}

func TestToSubscribers_InvalidEnvelope_Skips(t *testing.T) {
	reg := session.NewRegistry()
	subs := session.NewSubscription()
	a := &mockConn{id: "a"}
	reg.Add(a.ID(), a)
	subs.Subscribe("a", "ch1")

	dispatch.ToSubscribers([]byte("not-json"), subs, reg)
	assert.Equal(t, 0, len(a.sent))
}

func TestToSubscribers_MissingChannelID_Skips(t *testing.T) {
	reg := session.NewRegistry()
	subs := session.NewSubscription()
	a := &mockConn{id: "a"}
	reg.Add(a.ID(), a)
	subs.Subscribe("a", "ch1")

	inner, _ := json.Marshal(map[string]string{"message_id": "m1"})
	env, _ := json.Marshal(protocol.Envelope{Type: protocol.TypeMessageCreated, Payload: inner})
	dispatch.ToSubscribers(env, subs, reg)
	assert.Equal(t, 0, len(a.sent))
}

func TestToSubscribers_UnknownConn_Skips(t *testing.T) {
	reg := session.NewRegistry()
	subs := session.NewSubscription()
	// "ghost" is in subscription but NOT registry — race-with-disconnect path.
	subs.Subscribe("ghost", "ch1")

	payload := envelopeWith(t, "ch1")
	// Should not panic — ghost conn is silently skipped.
	dispatch.ToSubscribers(payload, subs, reg)
}
