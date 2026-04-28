package config

import (
	"encoding/hex"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestLoad_Defaults(t *testing.T) {
	t.Setenv("BREADMIND_MESSENGER_PASETO_KEY_HEX", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
	cfg, err := Load()
	assert.NoError(t, err)
	assert.Equal(t, ":8090", cfg.ListenAddr)
	assert.Equal(t, "redis://localhost:6379", cfg.RedisURL)
	assert.Equal(t, "http://localhost:8080", cfg.CoreBaseURL)
	assert.Equal(t, 30, cfg.PresenceTTLSeconds)

	expectedKey, _ := hex.DecodeString("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
	assert.Equal(t, expectedKey, cfg.PasetoKey)
	assert.Len(t, cfg.PasetoKey, 32)
}

func TestLoad_RequiresPasetoKey(t *testing.T) {
	t.Setenv("BREADMIND_MESSENGER_PASETO_KEY_HEX", "")
	_, err := Load()
	assert.ErrorContains(t, err, "BREADMIND_MESSENGER_PASETO_KEY_HEX")
}

func TestLoad_RejectsInvalidHex(t *testing.T) {
	t.Setenv("BREADMIND_MESSENGER_PASETO_KEY_HEX", strings.Repeat("zz", 32))
	_, err := Load()
	assert.ErrorContains(t, err, "invalid hex")
}
