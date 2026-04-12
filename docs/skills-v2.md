# Skills v2 — Bundle format + Checklist runtime

Phase 4 of the hooks-and-skills improvement series. Builds on the existing
flat skill system (`src/breadmind/core/skill_store.py`).

## What's new

- **Directory bundles** (`SKILL.md` + `references/`) with rich YAML frontmatter
- **Lazy reference loading** via `@references/foo.md` markers
- **Dependencies and priority** in frontmatter
- **Ephemeral checklist tracker** for per-session skill progress
- **Admin API**: `POST /api/skills/bundle/install`, `GET /api/skills/{name}/references`, checklist start/advance/summary

## Bundle layout

```
skills/my-skill/
├── SKILL.md              # frontmatter + body
└── references/
    ├── overview.md
    └── detail.md
```

## Frontmatter

```yaml
---
name: refactor-helper
description: Guide a Python refactor with test-first discipline
priority: 50
depends_on:
  - test-runner
tags: [python, refactor]
version: 0.1.0
author: you
---
```

## Body + references

Use `@references/foo.md` to pull in detail content on demand:

```markdown
# Refactor helper

Start with a failing test. See @references/overview.md for the workflow.
```

At prompt-build time a `ReferenceResolver` substitutes each marker with
the file contents, with a per-session cache so repeated resolutions do
not re-read files. Unknown markers are annotated `[reference missing]`
rather than silently stripped.

## Dependencies

`depends_on` names other installed skills. Skills with unmet dependencies
are skipped at trigger time with a warning (dependency resolution lives in
the skill selector, not in this phase).

## Checklist API

```
POST /api/skills/checklist/start  {session_id, skill_name, steps}
POST /api/skills/checklist/advance {session_id, skill_name}
GET  /api/skills/checklist/summary?session_id=...
```

Checklist state is in-memory only. Session state is cleared on process
restart or explicit `clear_session`.

## Known gaps (future phases)

- Checklist persistence (no DB table; live sessions only)
- Automatic dependency resolution at skill-trigger time (skill selector
  does not yet consult `Skill.depends_on`)
- Bundle upload via web UI (currently requires a path on the server's FS)
- Bundle versioning / upgrade flow
- Reference marker validation at install time
- `export_skills`/`import_skills` do not yet round-trip bundle metadata
  (`priority`, `depends_on`, etc.)
