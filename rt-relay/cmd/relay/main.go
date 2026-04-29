package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"

	aclpkg "github.com/breadpack/breadmind/rt-relay/internal/acl"
	"github.com/breadpack/breadmind/rt-relay/internal/auth"
	"github.com/breadpack/breadmind/rt-relay/internal/bus"
	"github.com/breadpack/breadmind/rt-relay/internal/config"
	"github.com/breadpack/breadmind/rt-relay/internal/dispatch"
	"github.com/breadpack/breadmind/rt-relay/internal/metrics"
	"github.com/breadpack/breadmind/rt-relay/internal/presence"
	"github.com/breadpack/breadmind/rt-relay/internal/session"
	"github.com/breadpack/breadmind/rt-relay/internal/transport"
	"github.com/breadpack/breadmind/rt-relay/internal/typing"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg, err := config.Load()
	if err != nil {
		logger.Error("config", "err", err)
		os.Exit(1)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	opt, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		logger.Error("redis url", "err", err)
		os.Exit(1)
	}
	rdb := redis.NewClient(opt)
	defer rdb.Close()

	pool, err := pgxpool.New(ctx, cfg.PgDSN)
	if err != nil {
		logger.Error("pg", "err", err)
		os.Exit(1)
	}
	defer pool.Close()

	verifier, err := auth.NewVerifier(cfg.PasetoKey)
	if err != nil {
		logger.Error("verifier", "err", err)
		os.Exit(1)
	}
	registry := session.NewRegistry()
	subs := session.NewSubscription()
	presenceTr := presence.NewTracker(rdb, time.Duration(cfg.PresenceTTLSeconds)*time.Second)
	typingTr := typing.NewTracker(rdb, time.Duration(cfg.TypingTTLSeconds)*time.Second)
	core := bus.NewCoreClient(cfg.CoreBaseURL, "")
	redisBus := bus.NewRedisBus(rdb)

	_ = presenceTr

	// Subscribe to channel:* events and fan-out
	stop, err := redisBus.Subscribe(ctx, "channel:*.events", func(payload []byte) {
		dispatch.ToSubscribers(payload, subs, registry)
	})
	if err != nil {
		logger.Error("redis subscribe", "err", err)
		os.Exit(1)
	}
	defer stop()

	// ACL invalidation subscriber (Task 9): consume `acl:invalidate:*` from
	// Redis and update each affected connection's per-conn ACL cache,
	// emitting Revoked/Granted client envelopes when the local view changes.
	// Workspace ID is read per-conn (multi-workspace correct).
	aclHandler := aclpkg.NewConnectionsHandler(
		transport.NewACLRegistry(registry),
		core,
		transport.NewEnvelopeFactory(),
	)
	aclCancel := aclpkg.Subscribe(ctx, rdb, aclHandler)
	defer aclCancel()

	handler := transport.NewHandler(
		verifier, registry, subs, core,
		typingTr,
		time.Duration(cfg.HeartbeatSeconds)*time.Second,
		time.Duration(cfg.IdleTimeoutSeconds)*time.Second,
	)

	mux := http.NewServeMux()
	mux.Handle("/ws", handler)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
		_, _ = w.Write([]byte("ok"))
	})

	srv := &http.Server{Addr: cfg.ListenAddr, Handler: mux}
	go func() {
		logger.Info("listening", "addr", cfg.ListenAddr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("listen", "err", err)
			cancel() // unblock main on fatal listen error
		}
	}()

	metricsMux := http.NewServeMux()
	metricsMux.Handle("/metrics", metrics.Handler())
	go func() {
		logger.Info("metrics listening", "addr", cfg.MetricsAddr)
		if err := http.ListenAndServe(cfg.MetricsAddr, metricsMux); err != nil {
			logger.Error("metrics listen", "err", err)
			cancel() // unblock main on fatal metrics listen error
		}
	}()

	<-ctx.Done()
	logger.Info("shutting down")
	shutdownCtx, c2 := context.WithTimeout(context.Background(), 5*time.Second)
	defer c2()
	_ = srv.Shutdown(shutdownCtx)
}
