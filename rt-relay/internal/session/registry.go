package session

import "sync"

// Conn is the interface satisfied by every live WebSocket connection.
type Conn interface {
	ID() string
	Send(payload []byte) error
	Close() error
}

// UserScopedConn is the optional extension a Conn may satisfy to opt into
// per-user lookups. Used by the ACL invalidation subscriber (Task 9) to fan
// out Revoked/Granted envelopes to every live connection for a given user.
//
// Conns that don't implement this interface are still tracked normally but
// won't appear in ConnsByUser results.
type UserScopedConn interface {
	Conn
	UserID() string
}

// Registry maps connection IDs to active Conn instances.
//
// A secondary index byUser maps userID → set of connection IDs to support
// O(1) per-user lookups for the ACL invalidation subscriber. The index is
// only populated for conns that implement UserScopedConn — non-user-scoped
// conns appear in conns but not in byUser.
type Registry struct {
	mu     sync.RWMutex
	conns  map[string]Conn
	byUser map[string]map[string]struct{}
}

// NewRegistry returns an initialised, empty Registry.
func NewRegistry() *Registry {
	return &Registry{
		conns:  make(map[string]Conn),
		byUser: make(map[string]map[string]struct{}),
	}
}

// Add registers a connection under the given id. If c implements
// UserScopedConn, the connection is also indexed by user id for ConnsByUser
// lookups.
func (r *Registry) Add(id string, c Conn) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.conns[id] = c
	if uc, ok := c.(UserScopedConn); ok {
		uid := uc.UserID()
		if uid != "" {
			set, exists := r.byUser[uid]
			if !exists {
				set = make(map[string]struct{})
				r.byUser[uid] = set
			}
			set[id] = struct{}{}
		}
	}
}

// Remove deletes the connection with the given id.
func (r *Registry) Remove(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if c, ok := r.conns[id]; ok {
		if uc, ok := c.(UserScopedConn); ok {
			uid := uc.UserID()
			if uid != "" {
				if set, exists := r.byUser[uid]; exists {
					delete(set, id)
					if len(set) == 0 {
						delete(r.byUser, uid)
					}
				}
			}
		}
	}
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

// ConnsByUser returns a snapshot slice of every live connection registered
// under userID. Only connections whose concrete type implements
// UserScopedConn are tracked here. The returned slice is safe to iterate
// outside the registry lock.
func (r *Registry) ConnsByUser(userID string) []Conn {
	r.mu.RLock()
	defer r.mu.RUnlock()
	set, ok := r.byUser[userID]
	if !ok {
		return nil
	}
	out := make([]Conn, 0, len(set))
	for id := range set {
		if c, ok := r.conns[id]; ok {
			out = append(out, c)
		}
	}
	return out
}
