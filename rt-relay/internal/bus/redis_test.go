package bus

import (
	"context"
	"testing"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	tcredis "github.com/testcontainers/testcontainers-go/modules/redis"
)

func TestPubSub_ReceivesPublishedEvent(t *testing.T) {
	ctx := context.Background()
	rc, err := tcredis.Run(ctx, "redis:7-alpine")
	require.NoError(t, err)
	defer rc.Terminate(ctx) //nolint:errcheck

	uri, err := rc.ConnectionString(ctx)
	require.NoError(t, err)
	opt, err := goredis.ParseURL(uri)
	require.NoError(t, err)
	rdb := goredis.NewClient(opt)

	bus := NewRedisBus(rdb)

	got := make(chan []byte, 1)
	stop, err := bus.Subscribe(ctx, "channel:c1.events", func(payload []byte) {
		got <- payload
	})
	require.NoError(t, err)
	defer stop()

	time.Sleep(50 * time.Millisecond) // ensure subscription active

	require.NoError(t, rdb.Publish(ctx, "channel:c1.events", []byte(`{"type":"message_created"}`)).Err())

	select {
	case payload := <-got:
		assert.Contains(t, string(payload), "message_created")
	case <-time.After(2 * time.Second):
		t.Fatal("did not receive message")
	}
}
