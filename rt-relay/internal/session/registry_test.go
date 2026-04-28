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
