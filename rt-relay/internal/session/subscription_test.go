package session

import (
	"sort"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestSubscription_AddAndList(t *testing.T) {
	s := NewSubscription()
	s.Subscribe("c1", "ch-1")
	s.Subscribe("c2", "ch-1")
	s.Subscribe("c1", "ch-2")

	subs := s.Subscribers("ch-1")
	sort.Strings(subs)
	assert.Equal(t, []string{"c1", "c2"}, subs)
}

func TestSubscription_Unsubscribe(t *testing.T) {
	s := NewSubscription()
	s.Subscribe("c1", "ch-1")
	s.Unsubscribe("c1", "ch-1")
	assert.Empty(t, s.Subscribers("ch-1"))
}

func TestSubscription_RemoveConn(t *testing.T) {
	s := NewSubscription()
	s.Subscribe("c1", "ch-1")
	s.Subscribe("c1", "ch-2")
	s.RemoveAll("c1")
	assert.Empty(t, s.Subscribers("ch-1"))
	assert.Empty(t, s.Subscribers("ch-2"))
}
