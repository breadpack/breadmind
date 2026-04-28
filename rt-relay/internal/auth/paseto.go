package auth

import (
	"errors"
	"fmt"
	"time"

	"aidanwoods.dev/go-paseto"
)

type Claims struct {
	UserID      string
	WorkspaceID string
	Role        string
	Kind        string
	Expiration  time.Time
}

type Verifier struct {
	key paseto.V4SymmetricKey
}

func NewVerifier(rawKey []byte) (*Verifier, error) {
	key, err := paseto.V4SymmetricKeyFromBytes(rawKey)
	if err != nil {
		return nil, fmt.Errorf("invalid v4 symmetric key: %w", err)
	}
	return &Verifier{key: key}, nil
}

func (v *Verifier) Verify(token string) (*Claims, error) {
	parser := paseto.NewParser() // includes NotExpired() rule by default
	parsed, err := parser.ParseV4Local(v.key, token, nil)
	if err != nil {
		return nil, err
	}

	uid, err := parsed.GetString("uid")
	if err != nil {
		return nil, fmt.Errorf("missing uid claim: %w", err)
	}
	wid, err := parsed.GetString("wid")
	if err != nil {
		return nil, fmt.Errorf("missing wid claim: %w", err)
	}
	kind, err := parsed.GetString("kind")
	if err != nil {
		return nil, fmt.Errorf("missing kind claim: %w", err)
	}
	if kind != "access" {
		return nil, errors.New("invalid kind: relay accepts access tokens only")
	}
	role, _ := parsed.GetString("role") // optional — ACL layer enforces

	// exp errors are intentionally discarded: parser.NewParser() applies
	// NotExpired() by default, which calls GetExpiration() internally and
	// fails ParseV4Local above if exp is missing or in the past.
	exp, _ := parsed.GetExpiration()
	return &Claims{
		UserID:      uid,
		WorkspaceID: wid,
		Role:        role,
		Kind:        kind,
		Expiration:  exp,
	}, nil
}
