package typing

import (
	"context"
	"testing"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	tcredis "github.com/testcontainers/testcontainers-go/modules/redis"
)

func TestTyping_MarkAndList(t *testing.T) {
	ctx := context.Background()
	rc, err := tcredis.Run(ctx, "redis:7-alpine")
	require.NoError(t, err)
	defer rc.Terminate(ctx) //nolint:errcheck

	uri, err := rc.ConnectionString(ctx)
	require.NoError(t, err)
	opt, err := goredis.ParseURL(uri)
	require.NoError(t, err)
	rdb := goredis.NewClient(opt)

	tr := NewTracker(rdb, 5*time.Second)
	require.NoError(t, tr.Mark(ctx, "ch-1", "u1"))
	require.NoError(t, tr.Mark(ctx, "ch-1", "u2"))

	users, err := tr.Active(ctx, "ch-1")
	require.NoError(t, err)
	assert.ElementsMatch(t, []string{"u1", "u2"}, users)
}
