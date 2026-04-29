package acl

import (
	"context"
	"sort"
	"testing"
)

// --- ParseInvalidation ---

func TestParseInvalidationEvent_B_Add(t *testing.T) {
	got, err := ParseInvalidation("acl:invalidate:user:abc:channel:def:add")
	if err != nil {
		t.Fatal(err)
	}
	if got.Kind != KindB || got.UserID != "abc" || got.ChannelID != "def" || got.Op != "add" {
		t.Fatalf("got %+v", got)
	}
}

func TestParseInvalidationEvent_B_Remove(t *testing.T) {
	got, err := ParseInvalidation("acl:invalidate:user:abc:channel:def:remove")
	if err != nil {
		t.Fatal(err)
	}
	if got.Op != "remove" {
		t.Fatalf("op=%s", got.Op)
	}
	if got.Kind != KindB || got.UserID != "abc" || got.ChannelID != "def" {
		t.Fatalf("got %+v", got)
	}
}

func TestParseInvalidationEvent_A(t *testing.T) {
	got, err := ParseInvalidation("acl:invalidate:user:abc")
	if err != nil {
		t.Fatal(err)
	}
	if got.Kind != KindA || got.UserID != "abc" {
		t.Fatalf("got %+v", got)
	}
	if got.ChannelID != "" || got.Op != "" {
		t.Fatalf("kindA must not carry channel/op: %+v", got)
	}
}

func TestParseInvalidationEvent_Bad(t *testing.T) {
	cases := []string{
		"",
		"acl:invalidate:user",
		"acl:invalidate:user:",
		"acl:invalidate:user:abc:channel:def:modify",
		"acl:invalidate:user:abc:channel::add",
		"acl:invalidate:user::channel:def:add",
		"acl:invalidate:user:abc:wrong:def:add",
		"wrong:prefix:user:abc",
		"acl:wrong:user:abc",
	}
	for _, in := range cases {
		if _, err := ParseInvalidation(in); err == nil {
			t.Errorf("expected error for %q", in)
		}
	}
}

// --- connectionsHandler ---

type fakeReg struct {
	conns map[string][]ConnectionACL
}

func (f *fakeReg) ConnsByUser(uid string) []ConnectionACL { return f.conns[uid] }

type fakeConn struct {
	id    string
	uid   string
	ws    string
	cache *Cache
	sent  [][]byte
}

func (c *fakeConn) ID() string          { return c.id }
func (c *fakeConn) UserID() string      { return c.uid }
func (c *fakeConn) WorkspaceID() string { return c.ws }
func (c *fakeConn) ACL() *Cache         { return c.cache }
func (c *fakeConn) Send(b []byte) error { c.sent = append(c.sent, b); return nil }

type fakeEnvs struct{}

func (fakeEnvs) Revoked(id, reason string) []byte { return []byte("revoked:" + id + ":" + reason) }
func (fakeEnvs) Granted(id string) []byte         { return []byte("granted:" + id) }

type fakeVisible struct {
	res     map[string][]string // workspaceID|userID → channels
	err     error
	resFlat []string // fallback when res is nil
}

func (f *fakeVisible) VisibleChannels(_ context.Context, ws, uid string) ([]string, error) {
	if f.err != nil {
		return nil, f.err
	}
	if f.res != nil {
		return f.res[ws+"|"+uid], nil
	}
	return f.resFlat, nil
}

func TestConnectionsHandler_BRemove_DropsAndSendsRevoked(t *testing.T) {
	cache := NewCacheFromSlice([]string{"c1", "c2"})
	conn := &fakeConn{id: "x", uid: "u", ws: "w", cache: cache}
	reg := &fakeReg{conns: map[string][]ConnectionACL{"u": {conn}}}
	h := NewConnectionsHandler(reg, &fakeVisible{}, fakeEnvs{})
	h.HandleEvent(context.Background(), Event{Kind: KindB, UserID: "u", ChannelID: "c1", Op: "remove"})
	if cache.Has("c1") {
		t.Fatal("c1 not removed")
	}
	if len(conn.sent) != 1 || string(conn.sent[0]) != "revoked:c1:acl_revoked" {
		t.Fatalf("sent=%v", conn.sent)
	}
}

func TestConnectionsHandler_BRemove_AlreadyAbsent_NoEnvelope(t *testing.T) {
	// Idempotency: removing a channel not in the cache must NOT emit an
	// envelope. This guards the per-conn cache contract: Send only when
	// the local view actually changed.
	cache := NewCacheFromSlice([]string{"c1"})
	conn := &fakeConn{id: "x", uid: "u", ws: "w", cache: cache}
	reg := &fakeReg{conns: map[string][]ConnectionACL{"u": {conn}}}
	h := NewConnectionsHandler(reg, &fakeVisible{}, fakeEnvs{})
	h.HandleEvent(context.Background(), Event{Kind: KindB, UserID: "u", ChannelID: "absent", Op: "remove"})
	if len(conn.sent) != 0 {
		t.Fatalf("expected no envelope, got %v", conn.sent)
	}
}

func TestConnectionsHandler_BAdd_AdmitsAndSendsGranted(t *testing.T) {
	cache := NewCacheFromSlice([]string{"c1"})
	conn := &fakeConn{id: "x", uid: "u", ws: "w", cache: cache}
	reg := &fakeReg{conns: map[string][]ConnectionACL{"u": {conn}}}
	h := NewConnectionsHandler(reg, &fakeVisible{}, fakeEnvs{})
	h.HandleEvent(context.Background(), Event{Kind: KindB, UserID: "u", ChannelID: "c2", Op: "add"})
	if !cache.Has("c2") {
		t.Fatal("c2 not added")
	}
	if len(conn.sent) != 1 || string(conn.sent[0]) != "granted:c2" {
		t.Fatalf("sent=%v", conn.sent)
	}
}

func TestConnectionsHandler_BAdd_AlreadyPresent_NoEnvelope(t *testing.T) {
	cache := NewCacheFromSlice([]string{"c1"})
	conn := &fakeConn{id: "x", uid: "u", ws: "w", cache: cache}
	reg := &fakeReg{conns: map[string][]ConnectionACL{"u": {conn}}}
	h := NewConnectionsHandler(reg, &fakeVisible{}, fakeEnvs{})
	h.HandleEvent(context.Background(), Event{Kind: KindB, UserID: "u", ChannelID: "c1", Op: "add"})
	if len(conn.sent) != 0 {
		t.Fatalf("expected no envelope, got %v", conn.sent)
	}
}

func TestConnectionsHandler_KindA_DiffsAndEmitsBoth(t *testing.T) {
	cache := NewCacheFromSlice([]string{"c1", "c2"})
	conn := &fakeConn{id: "x", uid: "u", ws: "w", cache: cache}
	reg := &fakeReg{conns: map[string][]ConnectionACL{"u": {conn}}}
	h := NewConnectionsHandler(
		reg,
		&fakeVisible{res: map[string][]string{"w|u": {"c2", "c3"}}},
		fakeEnvs{},
	)
	h.HandleEvent(context.Background(), Event{Kind: KindA, UserID: "u"})
	if cache.Has("c1") {
		t.Fatal("c1 should be removed")
	}
	if !cache.Has("c3") {
		t.Fatal("c3 should be added")
	}
	if len(conn.sent) != 2 {
		t.Fatalf("sent=%v", conn.sent)
	}
	got := []string{string(conn.sent[0]), string(conn.sent[1])}
	sort.Strings(got)
	want := []string{"granted:c3", "revoked:c1:acl_revoked"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("envelope %d: got %q want %q (full=%v)", i, got[i], want[i], got)
		}
	}
}

func TestConnectionsHandler_KindA_VisibleError_NoChange(t *testing.T) {
	// Fail-soft: a VisibleChannels error must NOT mutate the cache or
	// send envelopes — the existing seed remains authoritative until the
	// next successful refetch.
	cache := NewCacheFromSlice([]string{"c1", "c2"})
	conn := &fakeConn{id: "x", uid: "u", ws: "w", cache: cache}
	reg := &fakeReg{conns: map[string][]ConnectionACL{"u": {conn}}}
	h := NewConnectionsHandler(
		reg,
		&fakeVisible{err: context.DeadlineExceeded},
		fakeEnvs{},
	)
	h.HandleEvent(context.Background(), Event{Kind: KindA, UserID: "u"})
	if !cache.Has("c1") || !cache.Has("c2") {
		t.Fatal("cache must be untouched on visible error")
	}
	if len(conn.sent) != 0 {
		t.Fatalf("expected no envelopes on error, got %v", conn.sent)
	}
}

func TestConnectionsHandler_KindA_PerConnWorkspace(t *testing.T) {
	// Multi-workspace correctness: two conns for the same user with
	// different workspace IDs each refetch against THEIR OWN ws.
	cache1 := NewCacheFromSlice([]string{"a"})
	cache2 := NewCacheFromSlice([]string{"x"})
	conn1 := &fakeConn{id: "1", uid: "u", ws: "ws-A", cache: cache1}
	conn2 := &fakeConn{id: "2", uid: "u", ws: "ws-B", cache: cache2}
	reg := &fakeReg{conns: map[string][]ConnectionACL{"u": {conn1, conn2}}}
	h := NewConnectionsHandler(
		reg,
		&fakeVisible{res: map[string][]string{
			"ws-A|u": {"a", "b"},
			"ws-B|u": {"y"},
		}},
		fakeEnvs{},
	)
	h.HandleEvent(context.Background(), Event{Kind: KindA, UserID: "u"})
	if !cache1.Has("b") || cache1.Has("x") {
		t.Fatalf("conn1 cache: %v", cache1.Snapshot())
	}
	if !cache2.Has("y") || cache2.Has("a") {
		t.Fatalf("conn2 cache: %v", cache2.Snapshot())
	}
}

func TestConnectionsHandler_NoConns_Noop(t *testing.T) {
	reg := &fakeReg{conns: map[string][]ConnectionACL{}}
	h := NewConnectionsHandler(reg, &fakeVisible{}, fakeEnvs{})
	// Should not panic.
	h.HandleEvent(context.Background(), Event{Kind: KindA, UserID: "u"})
	h.HandleEvent(context.Background(), Event{Kind: KindB, UserID: "u", ChannelID: "c", Op: "add"})
}
