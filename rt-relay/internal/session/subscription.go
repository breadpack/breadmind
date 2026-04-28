package session

import "sync"

// Subscription tracks which connections are subscribed to which channels
// using a bidirectional index for O(1) fan-out lookups in both directions.
type Subscription struct {
	mu          sync.RWMutex
	chanToConns map[string]map[string]struct{}
	connToChans map[string]map[string]struct{}
}

// NewSubscription returns an initialised, empty Subscription.
func NewSubscription() *Subscription {
	return &Subscription{
		chanToConns: make(map[string]map[string]struct{}),
		connToChans: make(map[string]map[string]struct{}),
	}
}

// Subscribe registers connID as a subscriber of channelID.
func (s *Subscription) Subscribe(connID, channelID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.chanToConns[channelID] == nil {
		s.chanToConns[channelID] = make(map[string]struct{})
	}
	s.chanToConns[channelID][connID] = struct{}{}
	if s.connToChans[connID] == nil {
		s.connToChans[connID] = make(map[string]struct{})
	}
	s.connToChans[connID][channelID] = struct{}{}
}

// Unsubscribe removes connID from channelID's subscriber set.
func (s *Subscription) Unsubscribe(connID, channelID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if conns, ok := s.chanToConns[channelID]; ok {
		delete(conns, connID)
		if len(conns) == 0 {
			delete(s.chanToConns, channelID)
		}
	}
	if chans, ok := s.connToChans[connID]; ok {
		delete(chans, channelID)
		if len(chans) == 0 {
			delete(s.connToChans, connID)
		}
	}
}

// Subscribers returns the IDs of all connections subscribed to channelID.
func (s *Subscription) Subscribers(channelID string) []string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	conns := s.chanToConns[channelID]
	out := make([]string, 0, len(conns))
	for id := range conns {
		out = append(out, id)
	}
	return out
}

// RemoveAll unsubscribes connID from every channel it is subscribed to.
func (s *Subscription) RemoveAll(connID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for ch := range s.connToChans[connID] {
		delete(s.chanToConns[ch], connID)
		if len(s.chanToConns[ch]) == 0 {
			delete(s.chanToConns, ch)
		}
	}
	delete(s.connToChans, connID)
}
