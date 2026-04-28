package session

import "sync"

// Conn is the interface satisfied by every live WebSocket connection.
type Conn interface {
	ID() string
	Send(payload []byte) error
	Close() error
}

// Registry maps connection IDs to active Conn instances.
type Registry struct {
	mu    sync.RWMutex
	conns map[string]Conn
}

// NewRegistry returns an initialised, empty Registry.
func NewRegistry() *Registry {
	return &Registry{conns: make(map[string]Conn)}
}

// Add registers a connection under the given id.
func (r *Registry) Add(id string, c Conn) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.conns[id] = c
}

// Remove deletes the connection with the given id.
func (r *Registry) Remove(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.conns, id)
}

// Get returns the Conn for id, or (nil, false) if absent.
func (r *Registry) Get(id string) (Conn, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	c, ok := r.conns[id]
	return c, ok
}

// Count returns the number of registered connections.
func (r *Registry) Count() int {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return len(r.conns)
}
