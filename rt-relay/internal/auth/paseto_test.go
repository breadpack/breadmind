package auth

import (
	"encoding/hex"
	"os"
	"strings"
	"testing"
	"time"

	"aidanwoods.dev/go-paseto"
	"github.com/stretchr/testify/assert"
)

const testKeyHex = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

func loadTestKey(t *testing.T) (paseto.V4SymmetricKey, []byte) {
	raw, err := hex.DecodeString(testKeyHex)
	assert.NoError(t, err)
	key, err := paseto.V4SymmetricKeyFromBytes(raw)
	assert.NoError(t, err)
	return key, raw
}

func issueTestToken(key paseto.V4SymmetricKey, exp time.Time, kind, wid, uid, role string) string {
	tok := paseto.NewToken()
	tok.SetExpiration(exp)
	tok.SetString("wid", wid)
	tok.SetString("uid", uid)
	tok.SetString("role", role)
	tok.SetString("kind", kind)
	return tok.V4Encrypt(key, nil)
}

func TestVerify_ValidAccessToken(t *testing.T) {
	key, raw := loadTestKey(t)
	tok := issueTestToken(key, time.Now().Add(time.Hour), "access", "ws-abc", "user-123", "member")

	v, err := NewVerifier(raw)
	assert.NoError(t, err)
	got, err := v.Verify(tok)
	assert.NoError(t, err)
	assert.Equal(t, "user-123", got.UserID)
	assert.Equal(t, "ws-abc", got.WorkspaceID)
	assert.Equal(t, "member", got.Role)
	assert.Equal(t, "access", got.Kind)
}

func TestVerify_Expired(t *testing.T) {
	key, raw := loadTestKey(t)
	tok := issueTestToken(key, time.Now().Add(-time.Hour), "access", "ws-abc", "user-123", "member")

	v, _ := NewVerifier(raw)
	_, err := v.Verify(tok)
	assert.Error(t, err)
}

func TestVerify_InvalidKey(t *testing.T) {
	key, _ := loadTestKey(t)
	tok := issueTestToken(key, time.Now().Add(time.Hour), "access", "ws-abc", "user-123", "member")

	wrongRaw, _ := hex.DecodeString("ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff")
	v, _ := NewVerifier(wrongRaw)
	_, err := v.Verify(tok)
	assert.Error(t, err)
}

func TestVerify_RejectsRefreshKind(t *testing.T) {
	key, raw := loadTestKey(t)
	tok := issueTestToken(key, time.Now().Add(time.Hour), "refresh", "ws-abc", "user-123", "member")

	v, _ := NewVerifier(raw)
	_, err := v.Verify(tok)
	assert.ErrorContains(t, err, "kind")
}

func TestNewVerifier_RejectsBadKeyLength(t *testing.T) {
	_, err := NewVerifier([]byte("too short"))
	assert.Error(t, err)
}

func TestVerify_PythonCompat(t *testing.T) {
	tokenBytes, err := os.ReadFile("testdata/python_v4_token.txt")
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	pythonToken := strings.TrimSpace(string(tokenBytes))
	raw, _ := hex.DecodeString(testKeyHex)
	v, _ := NewVerifier(raw)
	claims, err := v.Verify(pythonToken)
	assert.NoError(t, err)
	assert.Equal(t, "87654321-4321-4321-4321-210987654321", claims.UserID)
	assert.Equal(t, "12345678-1234-1234-1234-123456789012", claims.WorkspaceID)
	assert.Equal(t, "admin", claims.Role)
	assert.Equal(t, "access", claims.Kind)
}

func TestVerify_RejectsTokenWithoutExp(t *testing.T) {
	key, raw := loadTestKey(t)
	tok := paseto.NewToken()
	tok.SetString("wid", "ws-abc")
	tok.SetString("uid", "user-123")
	tok.SetString("role", "member")
	tok.SetString("kind", "access")
	// intentionally NO SetExpiration() — token has no exp claim
	encrypted := tok.V4Encrypt(key, nil)

	v, _ := NewVerifier(raw)
	_, err := v.Verify(encrypted)
	assert.Error(t, err)
}
