package presence

import (
	"context"
	"errors"
	"time"

	"github.com/redis/go-redis/v9"
)

// Tracker stores per-user presence status in Redis with TTL-based expiry.
type Tracker struct {
	rdb *redis.Client
	ttl time.Duration
}

// NewTracker returns a Tracker backed by rdb. Keys expire after ttl.
func NewTracker(rdb *redis.Client, ttl time.Duration) *Tracker {
	return &Tracker{rdb: rdb, ttl: ttl}
}

// SetActive marks userID as "active" and refreshes the TTL.
func (t *Tracker) SetActive(ctx context.Context, userID string) error {
	return t.rdb.Set(ctx, "presence:"+userID, "active", t.ttl).Err()
}

// SetOffline removes the presence key for userID immediately.
func (t *Tracker) SetOffline(ctx context.Context, userID string) error {
	return t.rdb.Del(ctx, "presence:"+userID).Err()
}

// Get returns the presence status for userID.
// Returns "offline" when the key is missing or has expired.
func (t *Tracker) Get(ctx context.Context, userID string) (string, error) {
	v, err := t.rdb.Get(ctx, "presence:"+userID).Result()
	if errors.Is(err, redis.Nil) {
		return "offline", nil
	}
	if err != nil {
		return "", err
	}
	return v, nil
}
