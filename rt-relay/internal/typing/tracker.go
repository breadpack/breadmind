package typing

import (
	"context"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

// Tracker stores per-channel per-user typing state in Redis with TTL-based expiry.
type Tracker struct {
	rdb *redis.Client
	ttl time.Duration
}

// NewTracker returns a Tracker backed by rdb. Keys expire after ttl.
func NewTracker(rdb *redis.Client, ttl time.Duration) *Tracker {
	return &Tracker{rdb: rdb, ttl: ttl}
}

// Mark records that userID is currently typing in channelID and refreshes the TTL.
func (t *Tracker) Mark(ctx context.Context, channelID, userID string) error {
	key := "typing:" + channelID + ":" + userID
	return t.rdb.Set(ctx, key, "1", t.ttl).Err()
}

// Active returns the list of user IDs currently typing in channelID.
// Uses cursor-paginated SCAN to avoid blocking Redis on large keyspaces.
func (t *Tracker) Active(ctx context.Context, channelID string) ([]string, error) {
	pattern := "typing:" + channelID + ":*"
	var cursor uint64
	users := []string{}
	for {
		keys, next, err := t.rdb.Scan(ctx, cursor, pattern, 100).Result()
		if err != nil {
			return nil, err
		}
		for _, k := range keys {
			parts := strings.SplitN(k, ":", 3)
			if len(parts) == 3 {
				users = append(users, parts[2])
			}
		}
		if next == 0 {
			break
		}
		cursor = next
	}
	return users, nil
}
