// Package acl provides per-connection visible-channels caches and Redis
// invalidation subscriber primitives. The cache is populated on WebSocket
// connect (one VisibleChannels call) and updated by invalidation events.
package acl

import "sync"

// Cache is a per-connection set of channel IDs the user is permitted to
// observe. Lookups and mutations are concurrency-safe.
type Cache struct {
	mu  sync.RWMutex
	set map[string]struct{}
}

// NewCacheFromSlice populates a Cache from an initial channel-ID slice. A nil
// or empty slice yields an empty cache (all Has() lookups return false).
func NewCacheFromSlice(ids []string) *Cache {
	c := &Cache{set: make(map[string]struct{}, len(ids))}
	for _, id := range ids {
		c.set[id] = struct{}{}
	}
	return c
}

// Has returns true if the channel is permitted.
func (c *Cache) Has(id string) bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	_, ok := c.set[id]
	return ok
}

// Add admits a channel. Returns true if it was newly added.
func (c *Cache) Add(id string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.set[id]; ok {
		return false
	}
	c.set[id] = struct{}{}
	return true
}

// Remove revokes a channel. Returns true if it was present.
func (c *Cache) Remove(id string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.set[id]; !ok {
		return false
	}
	delete(c.set, id)
	return true
}

// Replace atomically swaps the entire set, returning (added, removed)
// channel IDs computed from the diff. Used for A-granular invalidation
// (Task 9).
func (c *Cache) Replace(ids []string) (added, removed []string) {
	next := make(map[string]struct{}, len(ids))
	for _, id := range ids {
		next[id] = struct{}{}
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	for id := range next {
		if _, ok := c.set[id]; !ok {
			added = append(added, id)
		}
	}
	for id := range c.set {
		if _, ok := next[id]; !ok {
			removed = append(removed, id)
		}
	}
	c.set = next
	return
}

// Snapshot returns a copy of the current set as a slice.
func (c *Cache) Snapshot() []string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	out := make([]string, 0, len(c.set))
	for id := range c.set {
		out = append(out, id)
	}
	return out
}
