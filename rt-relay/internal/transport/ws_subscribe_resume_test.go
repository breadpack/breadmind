package transport

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/breadpack/breadmind/rt-relay/internal/auth"
	"github.com/breadpack/breadmind/rt-relay/internal/protocol"
	"github.com/breadpack/breadmind/rt-relay/internal/session"
)

// stubCoreClient is a minimal in-memory CoreClient implementation for the
// transport tests. It satisfies the full transport.CoreClient interface
// (BackfillSince + VisibleChannels). visible maps userID → permitted
// channel IDs; an unknown user yields an empty slice (which translates to
// fail-closed: every Subscribe rejected).
//
// visibleErr, when non-nil, makes VisibleChannels return an error (used to
// exercise the ServeHTTP fail-closed 503 path).
type stubCoreClient struct {
	mu         sync.Mutex
	calls      []backfillCall
	rows       map[string][][]byte
	visible    map[string][]string
	visibleErr error
}

type backfillCall struct {
	workspaceID string
	channelID   string
	sinceTsSeq  int64
	limit       int
}

func (s *stubCoreClient) BackfillSince(ctx context.Context, workspaceID, channelID string, sinceTsSeq int64, limit int) ([][]byte, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, backfillCall{
		workspaceID: workspaceID,
		channelID:   channelID,
		sinceTsSeq:  sinceTsSeq,
		limit:       limit,
	})
	if rows, ok := s.rows[channelID]; ok {
		return rows, nil
	}
	return nil, nil
}

func (s *stubCoreClient) VisibleChannels(_ context.Context, _ string, userID string) ([]string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.visibleErr != nil {
		return nil, s.visibleErr
	}
	if ids, ok := s.visible[userID]; ok {
		return ids, nil
	}
	return nil, nil
}

func (s *stubCoreClient) snapshotCalls() []backfillCall {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]backfillCall, len(s.calls))
	copy(out, s.calls)
	return out
}

// newResumeTestServer wires a Handler with the supplied stub CoreClient and
// otherwise mirrors newTestServer (same key, same registry/subscription
// fresh state). Returns the server plus the registry/subs for assertions.
func newResumeTestServer(t *testing.T, core CoreClient) (*httptest.Server, *session.Registry, *session.Subscription) {
	t.Helper()
	_, raw := loadTestKey(t)
	v, err := auth.NewVerifier(raw)
	require.NoError(t, err)
	reg := session.NewRegistry()
	subs := session.NewSubscription()
	h := NewHandler(v, reg, subs, core, nil, 25*time.Second, 60*time.Second)
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	return srv, reg, subs
}

// TestHandler_SubscribeWithResume_StreamsBackfillBeforeSubscribed verifies
// that when a Subscribe envelope carries a non-zero per-channel resume
// cursor, the handler:
//  1. invokes coreClient.BackfillSince(ws, ch, since, limit) once per
//     resuming channel,
//  2. emits one TypeBackfill envelope per replayed event, and
//  3. emits the TypeSubscribed ack strictly AFTER all backfill envelopes.
func TestHandler_SubscribeWithResume_StreamsBackfillBeforeSubscribed(t *testing.T) {
	backfillEvent := json.RawMessage(`{"id":"m1","type":"message_created","channel_id":"ch-1","ts_seq":50}`)
	core := &stubCoreClient{
		rows: map[string][][]byte{
			"ch-1": {[]byte(backfillEvent), []byte(backfillEvent)},
		},
		visible: map[string][]string{
			"user-test": {"ch-1"},
		},
	}

	srv, _, subs := newResumeTestServer(t, core)
	key, _ := loadTestKey(t)
	tok := mintTestToken(t, key, time.Now().Add(time.Hour))

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(srv.URL)+"?token="+tok, nil)
	require.NoError(t, err)
	defer c.Close(websocket.StatusNormalClosure, "")

	subReq := protocol.SubscribeRequest{
		ChannelIDs:    []string{"ch-1"},
		ChannelResume: []int64{42},
	}
	envBytes, err := json.Marshal(protocol.Envelope{
		Type:    protocol.TypeSubscribe,
		Payload: mustMarshal(subReq),
	})
	require.NoError(t, err)
	require.NoError(t, c.Write(ctx, websocket.MessageText, envBytes))

	// Expect: 2 backfill envelopes followed by 1 subscribed ack, in order.
	seen := make([]string, 0, 3)
	var lastBackfill protocol.BackfillPayload
	for i := 0; i < 3; i++ {
		_, raw, err := c.Read(ctx)
		require.NoError(t, err, "read frame %d", i)
		var env protocol.Envelope
		require.NoError(t, json.Unmarshal(raw, &env), "decode frame %d", i)
		seen = append(seen, env.Type)
		if env.Type == protocol.TypeBackfill {
			require.NoError(t, json.Unmarshal(env.Payload, &lastBackfill))
		}
	}
	expected := []string{
		protocol.TypeBackfill,
		protocol.TypeBackfill,
		protocol.TypeSubscribed,
	}
	assert.Equal(t, expected, seen, "expected backfill * 2 → subscribed ordering")
	assert.Equal(t, "ch-1", lastBackfill.ChannelID)
	assert.JSONEq(t, string(backfillEvent), string(lastBackfill.Event))

	// Subscription registered after backfill replay.
	assert.Eventually(t, func() bool {
		return len(subs.Subscribers("ch-1")) == 1
	}, time.Second, 10*time.Millisecond)

	// Exactly one BackfillSince call with the right args.
	calls := core.snapshotCalls()
	require.Len(t, calls, 1)
	assert.Equal(t, "ws-test", calls[0].workspaceID)
	assert.Equal(t, "ch-1", calls[0].channelID)
	assert.Equal(t, int64(42), calls[0].sinceTsSeq)
	assert.Equal(t, 500, calls[0].limit)
}

// TestHandler_SubscribeWithoutResume_SkipsBackfill verifies that an empty
// or zero ChannelResume slice yields no BackfillSince call and emits the
// Subscribed ack as the very first frame (matching pre-resume behaviour).
func TestHandler_SubscribeWithoutResume_SkipsBackfill(t *testing.T) {
	core := &stubCoreClient{
		visible: map[string][]string{"user-test": {"ch-1"}},
	}
	srv, _, _ := newResumeTestServer(t, core)
	key, _ := loadTestKey(t)
	tok := mintTestToken(t, key, time.Now().Add(time.Hour))

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(srv.URL)+"?token="+tok, nil)
	require.NoError(t, err)
	defer c.Close(websocket.StatusNormalClosure, "")

	envBytes, err := json.Marshal(protocol.Envelope{
		Type:    protocol.TypeSubscribe,
		Payload: mustMarshal(protocol.SubscribeRequest{ChannelIDs: []string{"ch-1"}}),
	})
	require.NoError(t, err)
	require.NoError(t, c.Write(ctx, websocket.MessageText, envBytes))

	_, raw, err := c.Read(ctx)
	require.NoError(t, err)
	var env protocol.Envelope
	require.NoError(t, json.Unmarshal(raw, &env))
	assert.Equal(t, protocol.TypeSubscribed, env.Type, "first frame must be the ack when no resume cursor")

	assert.Empty(t, core.snapshotCalls(), "no BackfillSince calls expected without resume cursor")
}

// TestHandler_SubscribeWithResume_ZeroCursor_SkipsBackfill verifies that an
// explicit zero in ChannelResume[i] is treated the same as "no resume" for
// that channel — i.e. no BackfillSince call.
func TestHandler_SubscribeWithResume_ZeroCursor_SkipsBackfill(t *testing.T) {
	core := &stubCoreClient{
		visible: map[string][]string{"user-test": {"ch-1"}},
	}
	srv, _, _ := newResumeTestServer(t, core)
	key, _ := loadTestKey(t)
	tok := mintTestToken(t, key, time.Now().Add(time.Hour))

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(srv.URL)+"?token="+tok, nil)
	require.NoError(t, err)
	defer c.Close(websocket.StatusNormalClosure, "")

	envBytes, err := json.Marshal(protocol.Envelope{
		Type: protocol.TypeSubscribe,
		Payload: mustMarshal(protocol.SubscribeRequest{
			ChannelIDs:    []string{"ch-1"},
			ChannelResume: []int64{0},
		}),
	})
	require.NoError(t, err)
	require.NoError(t, c.Write(ctx, websocket.MessageText, envBytes))

	_, raw, err := c.Read(ctx)
	require.NoError(t, err)
	var env protocol.Envelope
	require.NoError(t, json.Unmarshal(raw, &env))
	assert.Equal(t, protocol.TypeSubscribed, env.Type)
	assert.Empty(t, core.snapshotCalls())
}

// TestHandler_SubscribeNonMember_RejectedWithError verifies the per-connection
// ACL gate (spec D5): a Subscribe targeting a channel NOT in the user's
// VisibleChannels set yields a TypeError envelope (code "acl_denied"), the
// channel is NOT registered in the subscription registry, and no
// BackfillSince call is issued. The trailing TypeSubscribed ack lists only
// the channels that passed the gate (here: none → empty list).
func TestHandler_SubscribeNonMember_RejectedWithError(t *testing.T) {
	core := &stubCoreClient{
		visible: map[string][]string{"user-test": {"ch-allowed"}},
	}
	srv, _, subs := newResumeTestServer(t, core)
	key, _ := loadTestKey(t)
	tok := mintTestToken(t, key, time.Now().Add(time.Hour))

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(srv.URL)+"?token="+tok, nil)
	require.NoError(t, err)
	defer c.Close(websocket.StatusNormalClosure, "")

	envBytes, err := json.Marshal(protocol.Envelope{
		Type: protocol.TypeSubscribe,
		Payload: mustMarshal(protocol.SubscribeRequest{
			ChannelIDs: []string{"ch-private"},
		}),
	})
	require.NoError(t, err)
	require.NoError(t, c.Write(ctx, websocket.MessageText, envBytes))

	// Frame 1: TypeError with code "acl_denied".
	_, raw, err := c.Read(ctx)
	require.NoError(t, err)
	var errEnv protocol.Envelope
	require.NoError(t, json.Unmarshal(raw, &errEnv))
	assert.Equal(t, protocol.TypeError, errEnv.Type)
	var ep protocol.ErrorPayload
	require.NoError(t, json.Unmarshal(errEnv.Payload, &ep))
	assert.Equal(t, "acl_denied", ep.Code)
	assert.Contains(t, ep.Message, "ch-private")

	// Frame 2: TypeSubscribed ack listing zero accepted channels.
	_, raw, err = c.Read(ctx)
	require.NoError(t, err)
	var ackEnv protocol.Envelope
	require.NoError(t, json.Unmarshal(raw, &ackEnv))
	assert.Equal(t, protocol.TypeSubscribed, ackEnv.Type)
	var ack protocol.SubscribedPayload
	require.NoError(t, json.Unmarshal(ackEnv.Payload, &ack))
	assert.Empty(t, ack.ChannelIDs, "denied channel must not appear in ack")

	// Subscription registry was NOT updated for the denied channel and no
	// backfill request was issued.
	assert.Empty(t, subs.Subscribers("ch-private"))
	assert.Empty(t, core.snapshotCalls())
}
