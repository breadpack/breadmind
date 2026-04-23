# Pilot Rollout Checklist (IT / Ops)

## Slack
- [ ] App manifest applied (scopes: `app_mentions:read`, `chat:write`,
      `conversations.members:read`, `im:write`, `team:read`, `users:read`).
- [ ] Socket Mode token provisioned and stored in `CredentialVault` as
      `slack_bot_token` + `slack_app_token`.
- [ ] Workspace events subscribed: `team_join`, `app_mention`, `message.channels`.
- [ ] Bot invited to pilot channels listed in `scripts/seed_pilot_data.py`.

## Confluence
- [ ] Service account `breadmind-bot@` created.
- [ ] API token issued and stored in `CredentialVault` as `confluence_token`.
- [ ] Read-only access to pilot spaces configured.

## Database
- [ ] Postgres 17 + pgvector provisioned.
- [ ] `alembic upgrade head` applied.
- [ ] `pgBackRest` configured (daily full + 15m WAL, 30d retention).
- [ ] DR drill date on calendar.

## Observability
- [ ] Prometheus scraping `http://breadmind:8080/kb/metrics`.
- [ ] Grafana dashboards imported from `deploy/grafana/dashboards/`.
- [ ] Alertmanager rules loaded from `deploy/alerts/prometheus-rules.yaml`.
- [ ] OpenTelemetry OTLP endpoint set via `OTEL_EXPORTER_OTLP_ENDPOINT` env var
      if tracing backend is available.

## OAuth / Secrets
- [ ] `.env` provisioned from template; no secrets in git.
- [ ] `CredentialVault` master key rotated for production.
- [ ] Slack bot token, Confluence token, Anthropic key, Azure OpenAI key all
      health-checked via `breadmind smoke --targets deploy/smoke/pilot-targets.yaml`.

## LLM
- [ ] Anthropic enterprise contract confirms "no training" clause.
- [ ] Azure OpenAI fallback deployment wired with same clause.
- [ ] Local Ollama standby available for 3rd-level fallback.

## Go-live gate
- [ ] `breadmind smoke --targets deploy/smoke/pilot-targets.yaml` exits 0.
      Exit 1 blocks Go-live; exit 2 means `pilot-targets.yaml` is missing or
      malformed. See "Preflight smoke" below for per-check remediation.
- [ ] `python scripts/check_go_no_go.py --report <latest report>` returns exit 0
      and prints `Decision: GO`.
- [ ] Pilot lead and security lead sign off in `#breadmind-pilot`.

## LLM outage runbook (referenced from alert)
1. Check Anthropic status page.
2. Check `breadmind_llm_latency_seconds_count{provider="azure"}` — if rising,
   fallback is working; silence alert for 30m.
3. If Azure also dead, users see "검색만" mode; monitor user_satisfaction.
4. Escalate to on-call if both remain down > 30m.

## Preflight smoke
`breadmind smoke` probes every runtime dependency and exits 0 / 1 / 2.
Reference each check's meaning when a failure appears.

| Check | What a failure means | Where to fix |
|-------|----------------------|--------------|
| `config` | `pilot-targets.yaml` missing or has unknown/missing keys (exit 2) | Copy `deploy/smoke/pilot-targets.yaml.example`, fill in values |
| `database` | `DATABASE_URL` unreachable or migration head mismatch | Run `breadmind migrate upgrade`; verify `alembic_version` |
| `vault` | Required credential not in CredentialVault | Store via admin UI or `CredentialVault.store` |
| `slack_auth` | Bot token invalid / scopes missing | Regenerate in Slack app config |
| `slack_channels` | Bot not a member of a required channel | `/invite @BreadMind` in Slack |
| `slack_events` | App token lacks `connections:write` or Socket Mode off | Enable Socket Mode, regenerate app-level token |
| `confluence_base_url` | Not HTTPS | Fix `confluence.base_url` in `pilot-targets.yaml` |
| `confluence_auth` | Service-account token expired/revoked | Issue new API token |
| `confluence_spaces` | Service account missing read on a space | Grant read in Confluence space permissions |
| `anthropic` | Required model absent from `/v1/models` | Verify enterprise contract model availability |
| `azure_openai` | Missing deployment | Create deployment in Azure portal |
| `llm_no_training` | `no_training_confirmed: false` | Security/legal sign-off, flip flag |

Run with `--skip check1,check2` only to isolate known not-yet-wired
fallbacks (e.g. `--skip azure_openai` during phased rollout). Never use
`--skip` to silence real failures.
