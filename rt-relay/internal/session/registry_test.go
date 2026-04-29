package session

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestRegistry_AddAndGet(t *testing.T) {
	r := NewRegistry()
	conn := &fakeConn{id: "c1"}
	r.Add("c1", conn)

	got, ok := r.Get("c1")
	assert.True(t, ok)
	assert.Equal(t, "c1", got.(*fakeConn).id)
}

func TestRegistry_Remove(t *testing.T) {
	r := NewRegistry()
	r.Add("c1", &fakeConn{id: "c1"})
	r.Remove("c1")
	_, ok := r.Get("c1")
	assert.False(t, ok)
}

func TestRegistry_Count(t *testing.T) {
	r := NewRegistry()
	r.Add("c1", &fakeConn{id: "c1"})
	r.Add("c2", &fakeConn{id: "c2"})
	assert.Equal(t, 2, r.Count())
}

type fakeConn struct{ id string }

func (f *fakeConn) Send(payload []byte) error { return nil }
func (f *fakeConn) Close() error              { return nil }
func (f *fakeConn) ID() string                { return f.id }

// fakeUserConn additionally implements UserScopedConn so it appears in the
// per-user index used by ConnsByUser.
type fakeUserConn struct {
	id  string
	uid string
}

func (f *fakeUserConn) Send(payload []byte) error { return nil }
func (f *fakeUserConn) Close() error              { return nil }
func (f *fakeUserConn) ID() string                { return f.id }
func (f *fakeUserConn) UserID() string            { return f.uid }

func TestRegistry_ConnsByUser_TracksUserScopedConns(t *testing.T) {
	r := NewRegistry()
	r.Add("c1", &fakeUserConn{id: "c1", uid: "alice"})
	r.Add("c2", &fakeUserConn{id: "c2", uid: "alice"})
	r.Add("c3", &fakeUserConn{id: "c3", uid: "bob"})

	alice := r.ConnsByUser("alice")
	assert.Len(t, alice, 2)
	bob := r.ConnsByUser("bob")
	assert.Len(t, bob, 1)
	assert.Empty(t, r.ConnsByUser("eve"))
}

func TestRegistry_ConnsByUser_RemoveUpdatesIndex(t *testing.T) {
	r := NewRegistry()
	r.Add("c1", &fakeUserConn{id: "c1", uid: "alice"})
	r.Add("c2", &fakeUserConn{id: "c2", uid: "alice"})
	r.Remove("c1")
	assert.Len(t, r.ConnsByUser("alice"), 1)
	r.Remove("c2")
	assert.Empty(t, r.ConnsByUser("alice"))
}

func TestRegistry_ConnsByUser_NonScopedConn_NotIndexed(t *testing.T) {
	// fakeConn does NOT implement UserScopedConn, so it should be tracked
	// in the main map (Get works) but NOT appear in ConnsByUser.
	r := NewRegistry()
	r.Add("c1", &fakeConn{id: "c1"})
	_, ok := r.Get("c1")
	assert.True(t, ok)
	assert.Empty(t, r.ConnsByUser(""))
	assert.Empty(t, r.ConnsByUser("anyone"))
}
