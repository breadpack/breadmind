"""CQL builder helpers for the Confluence backfill adapter (D4)."""
from __future__ import annotations

from datetime import datetime, timezone


def build_cql(
    source_filter: dict,
    since: datetime,
    until: datetime,
) -> str | None:
    """Build a CQL string for ``discover()``.

    Returns ``None`` for ``kind=page_ids`` (direct fetch, no CQL).
    """
    kind = source_filter.get("kind", "space")
    if kind == "page_ids":
        return None

    since_iso = since.strftime("%Y-%m-%dT%H:%M:%S")
    until_iso = until.strftime("%Y-%m-%dT%H:%M:%S")
    time_clause = (
        f'lastModified >= "{since_iso}" AND lastModified < "{until_iso}"'
    )

    if kind == "space":
        spaces = source_filter.get("spaces", [])
        space_list = ",".join(f'"{s}"' for s in spaces)
        cql = (
            f"space in ({space_list}) AND type=page AND status=current"
            f" AND {time_clause}"
        )
        labels_exclude = source_filter.get("labels_exclude") or []
        if labels_exclude:
            lbl = ",".join(f'"{lbl_name}"' for lbl_name in labels_exclude)
            cql += f' AND label NOT IN ({lbl})'
        return cql

    if kind == "subtree":
        root_id = source_filter.get("root_page_id", "")
        return (
            f'ancestor = "{root_id}" AND type=page AND status=current'
            f" AND {time_clause}"
        )

    raise ValueError(f"Unknown source_filter.kind: {kind!r}")


def build_cql_with_resume(
    source_filter: dict,
    since: datetime,
    until: datetime,
    resume_cursor: str,
) -> str:
    """Append a resume clause to a base CQL string (D2/Task 10)."""
    base = build_cql(source_filter, since, until) or ""
    # cursor format: "<ms>:<page_id>"
    parts = resume_cursor.split(":", 1)
    ts_ms = int(parts[0])
    page_id = parts[1] if len(parts) > 1 else ""
    resume_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    iso = resume_dt.strftime("%Y-%m-%dT%H:%M:%S")
    resume_clause = (
        f'(lastModified > "{iso}" '
        f'OR (lastModified = "{iso}" AND id > "{page_id}"))'
    )
    if base:
        return f"{base} AND {resume_clause}"
    return resume_clause
