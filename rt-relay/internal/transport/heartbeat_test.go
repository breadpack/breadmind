package transport

import (
	"context"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestHeartbeat_FiresAtInterval(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()

	var ticks int32
	StartHeartbeat(ctx, 50*time.Millisecond, func() error {
		atomic.AddInt32(&ticks, 1)
		return nil
	})

	<-ctx.Done()
	// give the final goroutine iteration a moment to exit cleanly
	time.Sleep(10 * time.Millisecond)
	assert.GreaterOrEqual(t, atomic.LoadInt32(&ticks), int32(2))
}

func TestHeartbeat_StopsOnPingError(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()

	var ticks int32
	stopErr := assertErr{msg: "boom"}
	StartHeartbeat(ctx, 20*time.Millisecond, func() error {
		atomic.AddInt32(&ticks, 1)
		return stopErr
	})

	time.Sleep(150 * time.Millisecond)
	// only the first tick should have fired before the goroutine exited
	assert.Equal(t, int32(1), atomic.LoadInt32(&ticks))
}

type assertErr struct{ msg string }

func (e assertErr) Error() string { return e.msg }

func TestHeartbeat_StopsOnContextCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())

	var ticks int32
	StartHeartbeat(ctx, 20*time.Millisecond, func() error {
		atomic.AddInt32(&ticks, 1)
		return nil
	})

	time.Sleep(50 * time.Millisecond)
	cancel()
	stable := atomic.LoadInt32(&ticks)
	time.Sleep(80 * time.Millisecond)
	assert.Equal(t, stable, atomic.LoadInt32(&ticks), "no further ticks after cancel")
}
