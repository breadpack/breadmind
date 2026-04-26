# Redmine Backfill Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Prerequisite:** Sub-project 1 (`BackfillJob` pipeline + Slack reference adapter) is **merged to master**. This plan binds to the contract defined in `docs/superpowers/specs/2026-04-26-backfill-pipeline-slack-design.md` (decisions D1–D6, C1–C2). If any of those have shifted between Sub-project 1 merge and the start of execution, re-read the backbone spec first and reconcile field names (`BackfillItem.parent_ref`, `cursor_of`, `instance_id_of`, `HourlyPageBudget` instance-keyed dimension, `OrgMonthlyBudget`) before writing code.

**Goal:** Add a first-class Redmine connector (`RedmineBackfillAdapter`) to the BreadMind backfill pipeline that imports historical issue/journal/wiki knowledge from on-prem Redmine instances while respecting permission locks, signal filters, and per-instance rate limits.

**Architecture:** A new `RedmineBackfillAdapter` (`kb/backfill/adapters/redmine.py`) implements the backbone `BackfillJob` ABC and emits two row shapes per ticket — one **issue anchor row** (`parent_ref=None`, body = `subject + description`) and zero or more **journal child rows** (`parent_ref="redmine_issue:<id>"`, body = note markdown). A thin `RedmineClient` (`kb/backfill/adapters/redmine_client.py`) isolates on-prem REST variability (self-signed TLS, auth mode, self-imposed QPS, legacy `is_closed` fallback) so the adapter stays pure orchestration. A new `breadmind kb backfill redmine` CLI subcommand dispatches into the existing Sub-project 1 runner.

**Tech Stack:** Python 3.12+, `aiohttp` (re-using the project's existing HTTP stack — same as `ConfluenceConnector`; do **not** introduce `httpx` unless the rest of `kb/backfill/` already uses it post Sub-project 1), `pytest-asyncio` (auto mode).

**Spec:** `docs/superpowers/specs/2026-04-26-backfill-redmine-design.md` (read end-to-end before Task 1; line numbers cited below are stable-as-of-spec-merge).

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `src/breadmind/kb/backfill/adapters/__init__.py` | Adapters package init (no-op if Sub-project 1 already created it). |
| Create | `src/breadmind/kb/backfill/adapters/redmine.py` | `RedmineBackfillAdapter`: `prepare()` → ACL snapshot, `discover()` → anchor + journal + wiki rows, `filter()` → signal cuts + ACL label, `cursor_of`, `instance_id_of`. |
| Create | `src/breadmind/kb/backfill/adapters/redmine_client.py` | `RedmineClient`: REST wrapper with on-prem knobs (`verify_ssl`, `auth_mode`, `rate_limit_qps`, `closed_status_ids`), retry/backoff ladder, identity/membership/issues/wiki endpoints. |
| Create | `src/breadmind/kb/backfill/adapters/redmine_types.py` | Plain dataclasses (`RedmineIssue`, `RedmineJournal`, `RedmineMembership`, `RedmineWikiPage`, `RedmineAttachment`) — keeps `redmine.py` slim, decoupled from raw JSON. |
| Modify | `src/breadmind/kb/backfill/cli.py` | Register `redmine` subcommand on the existing `breadmind kb backfill <connector>` Click group with flags `--project / --instance / --since / --until / --include / --token-budget / --dry-run / --confirm / --resume`. |
| Modify | `src/breadmind/kb/backfill/__init__.py` | Re-export `RedmineBackfillAdapter` from the package public surface so the runner's connector dispatcher can resolve `"redmine"` → class. |
| Create | `tests/kb/backfill/adapters/__init__.py` | Test package init. |
| Create | `tests/kb/backfill/adapters/test_redmine_client.py` | Unit tests for the REST client: auth header, TLS opt-out audit, server-side `updated_on` window, rate-limit pacing, closed-status fallback, 429/Retry-After honour. |
| Create | `tests/kb/backfill/adapters/test_redmine.py` | Unit tests for the adapter: ACL snapshot, anchor + journal split, filter rules, `cursor_of`/`instance_id_of`, dry-run breakdown, partial halt on org monthly budget. |
| Create | `tests/kb/backfill/adapters/fixtures/redmine_issues.json` | Recorded fixture issue list with mixed open/closed, private-notes, bot authors, metadata-only journals, attachments. |
| Create | `tests/kb/backfill/adapters/fixtures/redmine_memberships.json` | Recorded fixture project membership response (multi-role). |
| Create | `tests/integration/kb/backfill/test_redmine_e2e.py` | End-to-end fixture-driven run against testcontainers Postgres + migration `010` (depends on Sub-project 1 fixtures). |
| Modify | `docs/operations/kb-backfill.md` (or create if Sub-project 1 didn't) | Operator section: Redmine credentials JSON shape, on-prem knobs, dry-run example, troubleshooting (CDN attachments, pre-4.x `is_closed`). |

> **No source-tree code is touched outside `kb/backfill/`** other than the CLI dispatch hook. The legacy incremental connector tree (`kb/connectors/`) is left alone — Redmine has no incremental flow in Phase 1.

---

## Pre-Flight (run before Task 1)

- [ ] Confirm Sub-project 1 is merged: `BackfillJob`, `BackfillItem` (with `parent_ref` field), `JobReport` (with `skipped: dict[str, int]` and `cursor: str | None`), `HourlyPageBudget` instance-keyed dimension, `OrgMonthlyBudget` table all live on `master`. If any are missing, **stop and surface the gap** — do not work around it.
- [ ] Confirm migration `010_kb_backfill.py` (or whatever Sub-project 1 named it) is applied in the dev DB; verify `org_knowledge.parent_ref` and `kb_backfill_org_budget` exist via `\d`.
- [ ] Confirm the Click group `breadmind kb backfill <connector>` is wired and that `slack` already dispatches through it. The Redmine subcommand attaches to the same group.
- [ ] Skim `kb/backfill/adapters/slack.py` (or wherever the reference adapter lives) for naming conventions: `_membership_snapshot`, `_skip_reason`, `extra` payload shape — Redmine MUST mirror them so the runner's universal counters work.

---

## Task Decomposition (TDD; each step 2–5 minutes)

Every task is **test-first**: write the failing test, implement the smallest code that makes it pass, then move on. Tasks reference the spec's section so each implementation stays anchored.

### Phase A — REST client skeleton (on-prem variability is owned here)

- [ ] **Task 1 — Client skeleton + credential load.** *Spec §Authentication.* Test: `RedmineClient.from_vault(vault, ref)` reads JSON `{base_url, api_key, auth_mode, verify_ssl, rate_limit_qps, closed_status_ids}` and rejects (a) missing `base_url`, (b) `base_url` not starting with `https://`, (c) `auth_mode="api_key"` without `api_key`. Implement minimal constructor + `_build_auth_header()` returning `X-Redmine-API-Key` for `api_mode="api_key"` and `Basic <b64>` for `auth_mode="basic"`. **On-prem knobs introduced: `base_url`, `api_key`, `auth_mode`.**
- [ ] **Task 2 — `GET /users/current.json` identity probe.** *Spec §Authentication, §Permission Lock step 1.* Test: client returns the resolved user id from a fixture; raises `RedmineAuthError` on 401. Implement `verify_identity() -> int`. This is the call the adapter uses at `prepare()` start.
- [ ] **Task 3 — `verify_ssl=False` audit hook.** *Spec §Authentication.* Test: when `verify_ssl=False` the client emits exactly one audit log entry on first request via the injected `audit_log` (mirror the `ConfluenceConnector._audit` pattern). Default `verify_ssl=True`. **On-prem knob: `verify_ssl`.**
- [ ] **Task 4 — `GET /issues.json` with server-side window.** *Spec §Backfill Flow / discover, §Pagination.* Test: client builds query `project_id=<id>&status_id=*&sort=updated_on&limit=100&include=journals,attachments,custom_fields&updated_on=>=<since>&updated_on=<=<until>` and walks offset pagination via `(updated_on, id)` keyset (skip duplicates with same `updated_on` and lower `id` than last seen). Implement `iter_issues(project_id, since, until)` async generator yielding `RedmineIssue` dataclasses.
- [ ] **Task 5 — `GET /projects/<id>/memberships.json`.** *Spec §Permission Lock step 2.* Test: returns the full member set (user id, role names) in one call; falls back to `/users/<id>.json?include=memberships` only on `403`. Implement `fetch_memberships(project_id) -> list[RedmineMembership]`.
- [ ] **Task 6 — `GET /projects/<id>/wiki/index.json` + per-page fetch.** *Spec §Backfill Flow.* Test: enumerates pages, fetches each, returns latest version only (history dropped — open question #1 default). Implement `iter_wiki_pages(project_id, since, until)`. **Open-question decision baked in: latest-only.**
- [ ] **Task 7 — Self-imposed rate limiter.** *Spec §Rate Limit.* Test: client serializes requests so QPS never exceeds `rate_limit_qps` (default `2.0`); 1 in-flight request per instance; uses an `asyncio.Semaphore(1)` + monotonic-clock pacing. Verifiable by stubbing the clock and asserting `sleep` calls. **On-prem knob: `rate_limit_qps`.**
- [ ] **Task 8 — Backoff ladder + `Retry-After`.** *Spec §Rate Limit.* Test: 429 with `Retry-After: 17` sleeps 17s; 429 without header walks `(60, 300, 1800)`; 5xx walks the same ladder; connection reset is treated as 5xx. Re-use the constant tuple from `ConfluenceConnector._BACKOFF_SECONDS` (don't redefine; import).
- [ ] **Task 9 — Legacy `is_closed` fallback.** *Spec §Open Questions #4, §Signal Filters `closed_only`.* Test: client exposes `is_issue_closed(issue, closed_status_ids)` that uses `issue.status.is_closed` when present; falls back to `issue.status.id in closed_status_ids` otherwise; logs a one-shot warning when fallback is taken; if `closed_status_ids` is empty AND `is_closed` is missing, returns `None` (== "unknown") so the filter can downgrade to a no-op without crashing. **On-prem knob: `closed_status_ids`.**

> **Self-check after Phase A:** all four on-prem knobs (`verify_ssl` Task 3, `auth_mode` Task 1, `rate_limit_qps` Task 7, `closed_status_ids` Task 9) are exercised by a dedicated test. If any knob lacks a test, add it before moving on.

### Phase B — Adapter (issue anchor + journal child rows)

- [ ] **Task 10 — Adapter constructor + `instance_id_of`.** *Spec §Rate Limit, §6.5-equivalent for Redmine.* Test: `RedmineBackfillAdapter.instance_id_of({"instance": "<vault_ref>", "project_id": "7"})` returns `sha256(base_url)[:16]` deterministically across runs (no timestamp salt). Implement constructor accepting `org_id`, `source_filter`, `since`, `until`, `dry_run`, `token_budget`, plus injected `client: RedmineClient`, `vault`, `audit_log`. Set `source_kind = "redmine_issue"` (the runner's primary key; child journal rows still use it as their parent's source kind).
- [ ] **Task 11 — `prepare()` ACL snapshot.** *Spec §Permission Lock C1.* Test: `prepare()` calls `verify_identity()`, then `fetch_memberships(project_id)` for every project in `source_filter`, freezes the result on `self._membership_snapshot: frozenset[tuple[int, int, str]]` (`(project_id, user_id, role_name)`), and raises `PermissionError` if any project returns 403. Per-project disappearance between `prepare()` start and snapshot completion increments `skipped["acl_lock"]` at filter time, not here.
- [ ] **Task 12 — `discover()` issue anchor row.** *Spec §Data Mapping → Chosen layout (1).* Test: for each issue yielded by `client.iter_issues()`, the adapter yields a `BackfillItem` with `source_kind="redmine_issue"`, `source_native_id=str(issue.id)`, `source_uri=f"{base}/issues/{id}"`, `body=issue.subject + "\n\n" + issue.description`, `parent_ref=None`, `source_created_at=issue.created_on`, `source_updated_at=issue.updated_on`, `author=str(issue.author.id) if issue.author else None`, `extra={"_kind": "anchor", "tracker": issue.tracker_name, "status_id": issue.status.id, "is_closed_resolved": <bool|None>, "project_id": issue.project_id, "custom_fields": issue.custom_fields}`.
- [ ] **Task 13 — `discover()` journal child rows.** *Spec §Data Mapping → Chosen layout (2), D3 `parent_ref`.* Test: for each journal in `issue.journals` with non-empty trimmed `notes`, yield a separate `BackfillItem` with `source_kind="redmine_journal"`, `source_native_id=f"{issue.id}#note-{journal.id}"`, `source_uri=f"{base}/issues/{issue.id}#note-{journal_display_index}"` (display index computed client-side from journal order, NOT raw id), `body=journal.notes`, `parent_ref=f"redmine_issue:{issue.id}"`, `source_created_at=source_updated_at=journal.created_on`, `author=str(journal.user.id)`, `extra={"_kind": "journal", "private_notes": journal.private_notes, "metadata_only": not journal.notes.strip(), "project_id": issue.project_id}`.
- [ ] **Task 14 — `discover()` wiki page rows.** *Spec §Data Mapping (wiki 1:1 like Confluence).* Test: each wiki page yields one `BackfillItem` with `source_kind="redmine_wiki"`, `parent_ref=None`, `source_native_id=f"{project_id}:{page_title_url_safe}"`, `source_created_at=first_version_created_on`, `source_updated_at=page.updated_on`. Latest version only (Task 6 already enforces this; the adapter just consumes).
- [ ] **Task 15 — `discover()` attachment rows (Phase 1 conservative policy).** *Spec §Open Questions #2.* Test: for issues, attachments are emitted ONLY when MIME prefix is `text/` or `application/json`/`application/xml`/`application/x-yaml` AND `filesize <= 1_048_576`. Implementation tries `client.fetch_attachment(content_url)` with `X-Redmine-API-Key`; on non-2xx (CDN auth differs) the adapter logs a warning, increments a per-job counter, and skips the row. `parent_ref` is set to the parent issue/wiki ref. **Open-question #2 Phase-1 resolution: try API key, fall back to skip + warn.**
- [ ] **Task 16 — `filter()` rules in spec order.** *Spec §Signal Filters table, D1 keys.* Test: each rule in isolation, with default + override config; verify the dropped item stamps `extra["_skip_reason"]` with EXACTLY one of the canonical Redmine keys: `"private_notes"`, `"metadata_only_journal"`, `"empty_description"`, `"closed_old"`, `"acl_lock"`, `"auto_generated"`. Order: `private_notes` → `metadata_only_journal` → `closed_old` → `min_description_chars` / `min_journal_chars` (both map to `"empty_description"`) → `bot_authors` → `tracker_allow` → `acl_lock`. ACL label is the LAST check (it's a snapshot lookup, not a content cut) and is computed by checking `(item.extra["project_id"], int(item.author or -1))` against `self._membership_snapshot`.
- [ ] **Task 17 — `cursor_of` encoding.** *Spec D2, §Pagination & cursoring.* Test: `cursor_of(item)` returns `f"{item.source_updated_at.isoformat()}:{item.source_native_id.split('#')[0]}"` for both anchor (`"2025-09-12T10:14:00+00:00:42117"`) and journal (`"2025-09-12T10:14:00+00:00:42117"`) rows — both decode to the same parent issue id, which is what resume needs. Pipeline never parses; only the adapter does.
- [ ] **Task 18 — Resume-from-cursor.** *Spec §Backfill Flow, §Pagination.* Test: when `discover()` is invoked with a previously persisted `last_cursor`, the adapter parses it (`split(":", 1)`) and forwards `since = max(self.since, parsed_updated_on)` to `client.iter_issues()`, then in-loop skips items whose `(source_updated_at, native_id)` ≤ cursor (handles same-timestamp keyset).
- [ ] **Task 19 — Org monthly budget partial halt.** *Spec §Operational policy.* Test: if `OrgMonthlyBudget.would_exceed(estimate)` returns True mid-discover, the adapter stops yielding, sets `JobReport.partial = True`, and returns a `cursor` pointing at the last successfully filtered item. Verify cursor monotonicity: the resume run picks up exactly where this run stopped.

### Phase C — CLI, dry-run, e2e

- [ ] **Task 20 — `breadmind kb backfill redmine` subcommand.** *Spec §CLI Entry Point.* Test (using Click's `CliRunner`): flags `--org`, `--project`, `--instance` (optional, errors if multiple instances exist for the org without explicit selection), `--since`, `--until` (default = now UTC), `--include` (csv: `issues,wiki,attachments`; default `issues,wiki`), `--token-budget` (default = org KB cost policy), `--dry-run`, `--confirm`, `--resume <job-uuid>`. Construct `RedmineBackfillAdapter` and dispatch through the Sub-project 1 `BackfillRunner`. Reject mixing `--dry-run` and `--confirm`.
- [ ] **Task 21 — Dry-run output renderer (Redmine breakdown).** *Spec §Dry-run Output Example.* Test: snapshot test asserts the exact section headings (`Discover` / `Filter (JobReport.skipped — D1 keys)` / `Rows that WOULD be stored (BackfillItem with parent_ref shown for children — D3)` / `Redaction (preview)` / `Cost estimate`) in order, with anchor (`redmine_issue`, `parent_ref=None`) and journal (`redmine_journal`, `parent_ref=redmine_issue:<id>`) shown on **separate lines** so the parent/child split is visible at a glance.
- [ ] **Task 22 — End-to-end fake-Redmine test.** *Spec §Test Strategy E2E.* Build an `aiohttp` test server (or pytest-aiohttp `aiohttp_server` fixture) that serves the JSON fixtures from `tests/kb/backfill/adapters/fixtures/`. Run a real `RedmineBackfillAdapter` against testcontainers Postgres (migration 010 applied), assert: row counts in `org_knowledge` for `redmine_issue` vs `redmine_journal` match expected, every journal's `parent_ref` resolves to a real anchor, `JobReport.skipped` keys match the spec set exactly. **Vary on-prem knobs across two sub-cases:** (a) `verify_ssl=False, auth_mode="basic"`, (b) `verify_ssl=True, auth_mode="api_key", closed_status_ids=[5,6,7]` against pre-4.x fixture lacking `is_closed`.

---

## Self-Review (run after the last task; do NOT skip)

These are inline checks the executing agent runs against the finished plan + code, NOT separate tasks. Each item is a single grep-or-read verification.

### Spec coverage

- [ ] **§Overview / Indexing targets:** anchor (Task 12), journal (Task 13), wiki (Task 14), attachments (Task 15). Time entries / news / forums **explicitly out of scope** — confirm no code path touches them.
- [ ] **§Backbone Contract Alignment:** D1 (`skipped` keys) → Task 16; D2 (`cursor_of` opaque) → Task 17; D3 (`parent_ref` 1st-class) → Tasks 13/14/15; D4 (`since/until` adapter responsibility) → Tasks 4/13; D5 (`HourlyPageBudget` instance-keyed) → Task 10; D6 (two timestamps) → Tasks 12/13/14/15; C1 (permission lock at discover-start) → Task 11; C2 (canonical class name `RedmineBackfillAdapter`) → Task 10.
- [ ] **§Authentication:** API key + Basic fallback → Task 1; identity verify → Task 2; TLS audit → Task 3.
- [ ] **§Data Mapping:** anchor + journal split rationale baked into Tasks 12/13 (1 row per `(issue, journal)` plus 1 anchor per issue).
- [ ] **§Signal Filters:** every row of the table has a corresponding `_skip_reason` literal in Task 16, all six canonical keys present.
- [ ] **§Permission Lock:** discover-start snapshot (Task 11), per-item ACL label not enforce (Task 16), private notes hard-drop (Task 16 `private_notes` rule).
- [ ] **§Rate Limit:** self-imposed QPS (Task 7), backoff ladder (Task 8), `HourlyPageBudget` instance-keyed (Task 10), `OrgMonthlyBudget` partial halt (Task 19).
- [ ] **§Backfill Flow:** prepare→discover→filter ordering matches Sub-project 1 runner. Adapter does NOT call redact/embed/store.
- [ ] **§Pagination & cursoring:** keyset on `(updated_on, id)` → Task 4; cursor encoding → Task 17; resume → Task 18.
- [ ] **§Dry-run Output:** parent/child separation in renderer → Task 21.
- [ ] **§CLI Entry Point:** flag set complete → Task 20.
- [ ] **§Open Questions:** #1 (wiki latest-only) → Task 6; #2 (attachment CDN) → Task 15; #3 (custom fields) deferred — confirm no code pretends to handle it; #4 (legacy `is_closed`) → Task 9.

### Cross-task invariants

- [ ] **Anchor ↔ journal boundary:** every `BackfillItem` with `source_kind="redmine_journal"` has non-`None` `parent_ref`; every `source_kind="redmine_issue"` has `parent_ref=None`. Verify with one assertion in Task 22.
- [ ] **On-prem knobs map cleanly:** `verify_ssl` (Task 3), `auth_mode` (Task 1), `rate_limit_qps` (Task 7), `closed_status_ids` (Task 9) — each appears exactly once in the client and is covered by a dedicated test row. No knob silently picked up by the adapter.
- [ ] **Type signatures match the backbone:** `parent_ref: str | None`, `cursor_of(item: BackfillItem) -> str`, `instance_id_of(source_filter: dict[str, Any]) -> str`, `discover() -> AsyncIterator[BackfillItem]`. If Sub-project 1 changed any of these between spec freeze and merge, Task 10–14 must be reconciled.
- [ ] **No N+1 API calls in `filter()`:** the ACL check is an in-memory frozenset lookup against `self._membership_snapshot` only. No HTTP in `filter()`. Grep-check: `filter` method body must contain zero `await self._client.` calls.
- [ ] **No placeholders / TODOs in the merged code:** every emitted `BackfillItem` carries all 8 backbone-mandated fields populated (no `body=""`, no `source_uri="TBD"`).

### Out-of-scope guardrails (don't accidentally implement)

- [ ] No realtime/webhook code (spec §Out of scope).
- [ ] No two-way write (KB ingest is read-only).
- [ ] No cross-instance dedup logic (handled by `org_knowledge` policy upstream).
- [ ] No new `kb/connectors/redmine.py` file — the legacy incremental tree is **not** touched.
- [ ] No `httpx` dependency added to `pyproject.toml` unless Sub-project 1 already introduced it package-wide.

---

## Coverage targets (CI gate)

- Unit + integration ≥ 90% line / 85% branch on `kb/backfill/adapters/redmine*.py`. Matches the `confluence.py` baseline cited in spec §Test Strategy.
- One snapshot test on the dry-run renderer (Task 21) — text must be byte-identical to the spec's example modulo dynamic numbers.

---

## Done = all of:

- [ ] Tasks 1–22 checked.
- [ ] Self-review section walked top-to-bottom with every box ticked.
- [ ] `python -m pytest tests/kb/backfill/adapters/ tests/integration/kb/backfill/test_redmine_e2e.py -v` green.
- [ ] `ruff check src/breadmind/kb/backfill/adapters/ tests/kb/backfill/adapters/` clean.
- [ ] CLI smoke: `breadmind kb backfill redmine --org <id> --project <id> --since 2025-01-01 --dry-run` prints the spec's section headings against a local fake server.
