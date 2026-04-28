// Package transport implements the rt-relay HTTP/WebSocket entry point.
package transport

import (
	"context"
	"time"
)

// StartHeartbeat invokes ping at the given interval until ctx is cancelled or
// ping returns an error. The loop runs in its own goroutine.
func StartHeartbeat(ctx context.Context, interval time.Duration, ping func() error) {
	go func() {
		t := time.NewTicker(interval)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				if err := ping(); err != nil {
					return
				}
			}
		}
	}()
}
