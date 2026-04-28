package transport

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"aidanwoods.dev/go-paseto"
	"github.com/coder/websocket"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/breadpack/breadmind/rt-relay/internal/auth"
	"github.com/breadpack/breadmind/rt-relay/internal/protocol"
	"github.com/breadpack/breadmind/rt-relay/internal/session"
)

// 32 raw bytes / 64 hex chars — matches the pattern in internal/auth/paseto_test.go.
const testKeyHex = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

// loadTestKey returns the v4 symmetric key plus its raw bytes.
func loadTestKey(t *testing.T) (paseto.V4SymmetricKey, []byte) {
	t.Helper()
	raw, err := hex.DecodeString(testKeyHex)
	require.NoError(t, err)
	key, err := paseto.V4SymmetricKeyFromBytes(raw)
	require.NoError(t, err)
	return key, raw
}

// mintTestToken issues an access PASETO with the claim names the Verifier
// expects (`wid`, `uid`, `kind=access`, optional `role`).
func mintTestToken(t *testing.T, key paseto.V4SymmetricKey, exp time.Time) string {
	t.Helper()
	tok := paseto.NewToken()
	tok.SetExpiration(exp)
	tok.SetString("wid", "ws-test")
	tok.SetString("uid", "user-test")
	tok.SetString("role", "member")
	tok.SetString("kind", "access")
	return tok.V4Encrypt(key, nil)
}

// newTestServer wires up a Handler against fresh registry/subscription state
// and returns the httptest server plus those collaborators for assertions.
func newTestServer(t *testing.T) (*httptest.Server, *auth.Verifier, *session.Registry, *session.Subscription) {
	t.Helper()
	_, raw := loadTestKey(t)
	v, err := auth.NewVerifier(raw)
	require.NoError(t, err)
	reg := session.NewRegistry()
	subs := session.NewSubscription()
	h := NewHandler(v, reg, subs, nil, nil, 25*time.Second, 60*time.Second)
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	return srv, v, reg, subs
}

func wsURL(httpURL string) string {
	return strings.Replace(httpURL, "http://", "ws://", 1) + "/ws"
}

func TestWS_RejectsInvalidToken(t *testing.T) {
	srv, _, _, _ := newTestServer(t)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	url := wsURL(srv.URL) + "?token=not-a-valid-paseto"
	_, resp, err := websocket.Dial(ctx, url, nil)
	if err == nil {
		t.Fatal("expected dial to fail with invalid token")
	}
	if resp != nil {
		assert.Equal(t, 401, resp.StatusCode)
	}
}

func TestWS_RejectsMissingToken(t *testing.T) {
	srv, _, _, _ := newTestServer(t)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	_, resp, err := websocket.Dial(ctx, wsURL(srv.URL), nil)
	if err == nil {
		t.Fatal("expected dial to fail without token")
	}
	if resp != nil {
		assert.Equal(t, 401, resp.StatusCode)
	}
}

func TestWS_AcceptsValidToken(t *testing.T) {
	srv, _, reg, _ := newTestServer(t)
	key, _ := loadTestKey(t)
	tok := mintTestToken(t, key, time.Now().Add(time.Hour))

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(srv.URL)+"?token="+tok, nil)
	require.NoError(t, err)
	defer c.Close(websocket.StatusNormalClosure, "")

	assert.Eventually(t, func() bool {
		return reg.Count() == 1
	}, time.Second, 10*time.Millisecond)
}

func TestWS_AcceptsBearerHeader(t *testing.T) {
	srv, _, reg, _ := newTestServer(t)
	key, _ := loadTestKey(t)
	tok := mintTestToken(t, key, time.Now().Add(time.Hour))

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	opts := &websocket.DialOptions{
		HTTPHeader: map[string][]string{
			"Authorization": {"Bearer " + tok},
		},
	}
	c, _, err := websocket.Dial(ctx, wsURL(srv.URL), opts)
	require.NoError(t, err)
	defer c.Close(websocket.StatusNormalClosure, "")

	assert.Eventually(t, func() bool {
		return reg.Count() == 1
	}, time.Second, 10*time.Millisecond)
}

func TestWS_SubscribeAndAck(t *testing.T) {
	srv, _, _, subs := newTestServer(t)
	key, _ := loadTestKey(t)
	tok := mintTestToken(t, key, time.Now().Add(time.Hour))

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(srv.URL)+"?token="+tok, nil)
	require.NoError(t, err)
	defer c.Close(websocket.StatusNormalClosure, "")

	req := protocol.Envelope{
		Type:    protocol.TypeSubscribe,
		Payload: mustMarshal(protocol.SubscribeRequest{ChannelIDs: []string{"ch-1", "ch-2"}}),
	}
	body, err := json.Marshal(req)
	require.NoError(t, err)
	require.NoError(t, c.Write(ctx, websocket.MessageText, body))

	_, raw, err := c.Read(ctx)
	require.NoError(t, err)

	var env protocol.Envelope
	require.NoError(t, json.Unmarshal(raw, &env))
	assert.Equal(t, protocol.TypeSubscribed, env.Type)

	var ack protocol.SubscribedPayload
	require.NoError(t, json.Unmarshal(env.Payload, &ack))
	assert.ElementsMatch(t, []string{"ch-1", "ch-2"}, ack.ChannelIDs)

	assert.Eventually(t, func() bool {
		return len(subs.Subscribers("ch-1")) == 1 && len(subs.Subscribers("ch-2")) == 1
	}, time.Second, 10*time.Millisecond)
}

func TestWS_PingPong(t *testing.T) {
	srv, _, _, _ := newTestServer(t)
	key, _ := loadTestKey(t)
	tok := mintTestToken(t, key, time.Now().Add(time.Hour))

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(srv.URL)+"?token="+tok, nil)
	require.NoError(t, err)
	defer c.Close(websocket.StatusNormalClosure, "")

	body, err := json.Marshal(protocol.Envelope{Type: protocol.TypePing})
	require.NoError(t, err)
	require.NoError(t, c.Write(ctx, websocket.MessageText, body))

	_, raw, err := c.Read(ctx)
	require.NoError(t, err)
	var env protocol.Envelope
	require.NoError(t, json.Unmarshal(raw, &env))
	assert.Equal(t, protocol.TypePong, env.Type)
}

func TestWS_DisconnectCleansRegistry(t *testing.T) {
	srv, _, reg, subs := newTestServer(t)
	key, _ := loadTestKey(t)
	tok := mintTestToken(t, key, time.Now().Add(time.Hour))

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(srv.URL)+"?token="+tok, nil)
	require.NoError(t, err)

	// subscribe so we can verify RemoveAll cleans subscriptions too
	body, _ := json.Marshal(protocol.Envelope{
		Type:    protocol.TypeSubscribe,
		Payload: mustMarshal(protocol.SubscribeRequest{ChannelIDs: []string{"ch-bye"}}),
	})
	require.NoError(t, c.Write(ctx, websocket.MessageText, body))
	_, _, err = c.Read(ctx) // ack
	require.NoError(t, err)

	require.NoError(t, c.Close(websocket.StatusNormalClosure, ""))

	assert.Eventually(t, func() bool {
		return reg.Count() == 0 && len(subs.Subscribers("ch-bye")) == 0
	}, time.Second, 10*time.Millisecond)
}

func TestBearerFromHeader(t *testing.T) {
	assert.Equal(t, "abc", bearerFromHeader("Bearer abc"))
	assert.Equal(t, "", bearerFromHeader(""))
	assert.Equal(t, "", bearerFromHeader("Bearer "))
	assert.Equal(t, "", bearerFromHeader("Token abc"))
}

// --- A-3: TypeTyping client→server branch ---

type recordingTypingTracker struct {
	mu    sync.Mutex
	marks []struct{ ChannelID, UserID string }
}

func (r *recordingTypingTracker) Mark(_ context.Context, channelID, userID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.marks = append(r.marks, struct{ ChannelID, UserID string }{channelID, userID})
	return nil
}

type fakeTypingConn struct {
	id   string
	mu   sync.Mutex
	sent [][]byte
}

func (f *fakeTypingConn) ID() string   { return f.id }
func (f *fakeTypingConn) Close() error { return nil }
func (f *fakeTypingConn) Send(p []byte) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.sent = append(f.sent, append([]byte(nil), p...))
	return nil
}

func TestHandleClientMessage_Typing_MarksTracker(t *testing.T) {
	tt := &recordingTypingTracker{}
	h := &Handler{typingTracker: tt}
	conn := &fakeTypingConn{id: "c1"}

	payload, _ := json.Marshal(protocol.TypingRequest{ChannelID: "ch-1"})
	env, _ := json.Marshal(protocol.Envelope{Type: protocol.TypeTyping, Payload: payload})

	h.handleClientMessage(context.Background(), conn, &auth.Claims{UserID: "u-9"}, env)

	assert.Equal(t, 1, len(tt.marks))
	assert.Equal(t, "ch-1", tt.marks[0].ChannelID)
	assert.Equal(t, "u-9", tt.marks[0].UserID)
}

func TestHandleClientMessage_Typing_EmptyChannel_Skips(t *testing.T) {
	tt := &recordingTypingTracker{}
	h := &Handler{typingTracker: tt}
	conn := &fakeTypingConn{id: "c1"}

	payload, _ := json.Marshal(protocol.TypingRequest{ChannelID: ""})
	env, _ := json.Marshal(protocol.Envelope{Type: protocol.TypeTyping, Payload: payload})

	h.handleClientMessage(context.Background(), conn, &auth.Claims{UserID: "u-9"}, env)

	assert.Equal(t, 0, len(tt.marks))
}

func TestHandleClientMessage_Typing_NilTracker_NoPanic(t *testing.T) {
	// Defensive: when typingTracker isn't wired, the branch must not crash.
	h := &Handler{typingTracker: nil}
	conn := &fakeTypingConn{id: "c1"}

	payload, _ := json.Marshal(protocol.TypingRequest{ChannelID: "ch-1"})
	env, _ := json.Marshal(protocol.Envelope{Type: protocol.TypeTyping, Payload: payload})

	// Should not panic.
	h.handleClientMessage(context.Background(), conn, &auth.Claims{UserID: "u-9"}, env)
}
