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

## Configuration

`rt-relay` is configured via environment variables (loaded by `internal/config/config.Load`):

| Env var | Default | Purpose |
|---|---|---|
| `BREADMIND_RELAY_LISTEN_ADDR` | `:8090` | WebSocket bind address |
| `BREADMIND_RELAY_REDIS_URL` | `redis://localhost:6379` | Redis pub/sub (event fan-out) |
| `BREADMIND_RELAY_CORE_BASE_URL` | `http://localhost:8080` | BreadMind core REST API |
| `BREADMIND_RELAY_PG_DSN` | `postgres://breadmind:breadmind@localhost:5434/breadmind` | Postgres DSN |
| `BREADMIND_MESSENGER_PASETO_KEY_HEX` | *(required)* | 64-hex-char PASETO v4.local key shared with Python issuer |
| `BREADMIND_RELAY_PRESENCE_TTL_S` | `30` | Presence key TTL in Redis |
| `BREADMIND_RELAY_TYPING_TTL_S` | `5` | Typing key TTL in Redis |
| `BREADMIND_RELAY_HEARTBEAT_S` | `25` | Server→client WebSocket ping interval (keeps NAT/intermediaries alive) |
| `BREADMIND_RELAY_IDLE_TIMEOUT_S` | `60` | Max time a client connection may go without sending an *application-level* envelope before being disconnected. Set to `0` to disable. |
| `BREADMIND_RELAY_METRICS_ADDR` | `:9090` | Prometheus `/metrics` bind |

### Heartbeat vs idle-timeout semantics

These two are independent and operate at different protocol layers:

- **`HEARTBEAT_S`** — server sends a WebSocket protocol-level *ping* control frame every N seconds. The client (and any intermediaries) auto-respond with a *pong* control frame. This keeps NAT/load-balancer connection state warm; it does NOT carry application data.

- **`IDLE_TIMEOUT_S`** — server requires the client to send an *application-level* envelope (`protocol.TypePing`, `protocol.TypeSubscribe`, `protocol.TypeTyping`, …) at least this often. **Protocol-level pong responses to the server's pings do NOT count.** A client that only answers control pings but is otherwise silent at the application layer will be disconnected every `IDLE_TIMEOUT_S` seconds.

  If you have a long-lived client that legitimately stays quiet (e.g., a presence-only listener), either (a) have it send a periodic `protocol.TypePing` envelope at less than `IDLE_TIMEOUT_S` cadence, or (b) set `BREADMIND_RELAY_IDLE_TIMEOUT_S=0` to disable the per-read deadline entirely (at the cost of holding goroutines for genuinely-dead TCP connections until keep-alive trips, often minutes).

## Docker

```bash
make docker       # docker build -t breadmind/rt-relay:dev -f Dockerfile .
```

## Module

`github.com/breadpack/breadmind/rt-relay`
