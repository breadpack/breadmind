# rt-relay

WebSocket gateway for BreadMind Messenger M2 real-time transport.

## Overview

`rt-relay` is a Go-based fan-out relay that sits in front of the Python M1 REST/DB backend.
It handles:

- Real-time WebSocket connections for messenger clients
- Presence and typing-indicator fan-out via Redis pub/sub
- Reconnect backfill (missed events during disconnect)
- PASETO token authentication
- Prometheus metrics

See [plan](../docs/superpowers/plans/2026-04-27-messenger-m2a-rt-relay.md) and
[spec](../docs/superpowers/specs/2026-04-27-messenger-m2-design.md) for full design details.

## Requirements

- Go 1.22+
- Redis 7+
- PostgreSQL 15+ (pgvector)
- `golangci-lint` for linting

## Build

```bash
make build        # produces bin/relay (bin/relay.exe on Windows)
```

## Test

```bash
make test         # go test ./... -race -count=1
```

## Lint

```bash
make lint         # golangci-lint run
```

## Run

```bash
make run          # go run ./cmd/relay
```

## Docker

```bash
make docker       # docker build -t breadmind/rt-relay:dev -f Dockerfile .
```

## Module

`github.com/breadpack/breadmind/rt-relay`
