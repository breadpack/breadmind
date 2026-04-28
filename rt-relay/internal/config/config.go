package config

import (
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"strconv"
)

type Config struct {
	ListenAddr         string
	RedisURL           string
	CoreBaseURL        string
	PgDSN              string
	PasetoKey          []byte
	PresenceTTLSeconds int
	TypingTTLSeconds   int
	HeartbeatSeconds   int
	IdleTimeoutSeconds int
	MetricsAddr        string
}

func Load() (*Config, error) {
	keyHex := os.Getenv("BREADMIND_MESSENGER_PASETO_KEY_HEX")
	if keyHex == "" {
		return nil, errors.New("BREADMIND_MESSENGER_PASETO_KEY_HEX required")
	}
	if len(keyHex) != 64 {
		return nil, fmt.Errorf("BREADMIND_MESSENGER_PASETO_KEY_HEX must be 64 hex chars (got %d)", len(keyHex))
	}
	keyBytes, err := hex.DecodeString(keyHex)
	if err != nil {
		return nil, fmt.Errorf("BREADMIND_MESSENGER_PASETO_KEY_HEX invalid hex: %w", err)
	}
	cfg := &Config{
		ListenAddr:         envOr("BREADMIND_RELAY_LISTEN_ADDR", ":8090"),
		RedisURL:           envOr("BREADMIND_RELAY_REDIS_URL", "redis://localhost:6379"),
		CoreBaseURL:        envOr("BREADMIND_RELAY_CORE_BASE_URL", "http://localhost:8080"),
		PgDSN:              envOr("BREADMIND_RELAY_PG_DSN", "postgres://breadmind:breadmind@localhost:5434/breadmind"),
		PasetoKey:          keyBytes,
		PresenceTTLSeconds: envInt("BREADMIND_RELAY_PRESENCE_TTL_S", 30),
		TypingTTLSeconds:   envInt("BREADMIND_RELAY_TYPING_TTL_S", 5),
		HeartbeatSeconds:   envInt("BREADMIND_RELAY_HEARTBEAT_S", 25),
		IdleTimeoutSeconds: envInt("BREADMIND_RELAY_IDLE_TIMEOUT_S", 60),
		MetricsAddr:        envOr("BREADMIND_RELAY_METRICS_ADDR", ":9090"),
	}
	return cfg, nil
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func envInt(k string, def int) int {
	if v := os.Getenv(k); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}
