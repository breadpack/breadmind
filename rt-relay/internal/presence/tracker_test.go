package presence

import (
	"context"
	"testing"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	tcredis "github.com/testcontainers/testcontainers-go/modules/redis"
)

func TestTracker_SetAndGet(t *testing.T) {
	ctx := context.Background()
	rc, err := tcredis.Run(ctx, "redis:7-alpine")
	require.NoError(t, err)
	defer rc.Terminate(ctx) //nolint:errcheck

	uri, err := rc.ConnectionString(ctx)
	require.NoError(t, err)
	opt, err := goredis.ParseURL(uri)
	require.NoError(t, err)
	rdb := goredis.NewClient(opt)

	tr := NewTracker(rdb, 1*time.Second)
	require.NoError(t, tr.SetActive(ctx, "u1"))
	status, err := tr.Get(ctx, "u1")
	require.NoError(t, err)
	assert.Equal(t, "active", status)
}

func TestTracker_Expires(t *testing.T) {
	ctx := context.Background()
	rc, err := tcredis.Run(ctx, "redis:7-alpine")
	require.NoError(t, err)
	defer rc.Terminate(ctx) //nolint:errcheck

	uri, err := rc.ConnectionString(ctx)
	require.NoError(t, err)
	opt, err := goredis.ParseURL(uri)
	require.NoError(t, err)
	rdb := goredis.NewClient(opt)

	tr := NewTracker(rdb, 200*time.Millisecond)
	_ = tr.SetActive(ctx, "u1")
	time.Sleep(300 * time.Millisecond)
	status, _ := tr.Get(ctx, "u1")
	assert.Equal(t, "offline", status)
}
