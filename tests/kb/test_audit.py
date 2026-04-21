"""Tests for breadmind.kb.audit."""
from __future__ import annotations

import uuid

from breadmind.kb.audit import audit_log
from breadmind.storage.database import Database


async def test_audit_log_inserts_row(test_db: Database) -> None:
    project_id = uuid.uuid4()
    async with test_db.acquire() as conn:
        await conn.execute(
            "INSERT INTO org_projects(id, name, slack_team_id) "
            "VALUES($1, 'proj', 'T1')",
            project_id,
        )
    await audit_log(
        test_db,
        actor="U12345",
        action="query",
        subject_type="knowledge",
        subject_id="42",
        project_id=str(project_id),
        metadata={"q": "hi"},
    )
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT actor, action, subject_type, subject_id, "
            "project_id, metadata "
            "FROM kb_audit_log WHERE actor='U12345' "
            "ORDER BY id DESC LIMIT 1"
        )
        await conn.execute(
            "DELETE FROM kb_audit_log WHERE actor='U12345'"
        )
        await conn.execute(
            "DELETE FROM org_projects WHERE id=$1", project_id
        )
    assert row is not None
    assert row["actor"] == "U12345"
    assert row["action"] == "query"
    assert row["subject_type"] == "knowledge"
    assert row["subject_id"] == "42"
    assert str(row["project_id"]) == str(project_id)


async def test_audit_log_accepts_null_optional_fields(
    test_db: Database,
) -> None:
    await audit_log(test_db, actor="U99", action="llm_call")
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT subject_id, project_id, metadata "
            "FROM kb_audit_log WHERE actor='U99' "
            "ORDER BY id DESC LIMIT 1"
        )
        await conn.execute("DELETE FROM kb_audit_log WHERE actor='U99'")
    assert row["subject_id"] is None
    assert row["project_id"] is None
    assert row["metadata"] is None
