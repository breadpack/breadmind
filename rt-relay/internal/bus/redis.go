package bus

import (
	"context"

	"github.com/redis/go-redis/v9"
)

type Handler func(payload []byte)

type RedisBus struct {
	client *redis.Client
}

func NewRedisBus(client *redis.Client) *RedisBus {
	return &RedisBus{client: client}
}

// Subscribe runs until the returned cancel func is called.
func (b *RedisBus) Subscribe(ctx context.Context, pattern string, h Handler) (func(), error) {
	pubsub := b.client.PSubscribe(ctx, pattern)
	if _, err := pubsub.Receive(ctx); err != nil {
		return nil, err
	}
	ch := pubsub.Channel()
	stopCtx, cancel := context.WithCancel(ctx)

	go func() {
		for {
			select {
			case <-stopCtx.Done():
				return
			case msg, ok := <-ch:
				if !ok {
					return
				}
				h([]byte(msg.Payload))
			}
		}
	}()

	return func() {
		cancel()
		_ = pubsub.Close()
	}, nil
}

func (b *RedisBus) Publish(ctx context.Context, channel string, payload []byte) error {
	return b.client.Publish(ctx, channel, payload).Err()
}
