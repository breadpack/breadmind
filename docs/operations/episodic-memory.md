# Episodic Memory Recorder (Phase 1)

## Knobs

| Env | Default | Effect |
|-----|---------|--------|
| `BREADMIND_EPISODIC_NORMALIZE` | `on` | LLM normalization; `off` writes raw notes only. |
| `BREADMIND_EPISODIC_NORMALIZE_TIMEOUT_SEC` | `8` | Per-call LLM timeout. |
| `BREADMIND_EPISODIC_QUEUE_MAX` | `200` | When in-flight normalize calls exceed this, new events bypass the LLM. |
| `BREADMIND_EPISODIC_RECALL_TURN_K` | `5` | Turn-level recall top-K. |
| `BREADMIND_EPISODIC_RECALL_TOOL_K` | `3` | Tool-level recall top-K. |
| `BREADMIND_EPISODIC_RECALL_MESSAGES_MAX` | `8` | Per-turn cap for buffered prior_runs system messages drained into the next LLM prompt. Overflow drops oldest FIFO. `0` disables buffering. |
| `BREADMIND_EPISODIC_RECALL_DECAY_DAYS` | `7` | Recency decay τ in days (Phase 2 wiring). |

## Rollout

1. Apply migration `008_episodic_recorder` (`breadmind migrate upgrade head`).
2. Start with `BREADMIND_EPISODIC_NORMALIZE=off` to verify signal capture and raw writes.
3. Flip `NORMALIZE=on` for 1–2 canary users; watch `breadmind_memory_normalize_*` metrics.
4. Roll out to all users once latency p95 < 3s and `llm_failed` rate < 5%.

## Rollback

Set `BREADMIND_EPISODIC_NORMALIZE=off` to immediately stop LLM calls. Existing data remains intact and is reused once flipped back on.

## Failure mode contract

Memory-circuit failures must never block the agent loop. All recorder/store/recall paths are wrapped in `try/except`. Failures are logged at WARNING and incremented as metrics.
