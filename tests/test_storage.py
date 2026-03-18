from breadmind.storage.models import AuditEntry, EpisodicNote


def test_audit_entry_creation():
    entry = AuditEntry(
        action="k8s_list_pods",
        params={"namespace": "default"},
        result="ALLOWED",
        reason="auto-allow",
        channel="slack",
        user="U12345",
    )
    assert entry.action == "k8s_list_pods"
    assert entry.result == "ALLOWED"


def test_episodic_note_creation():
    note = EpisodicNote(
        content="User prefers snapshots before VM changes",
        keywords=["snapshot", "vm", "preference"],
        tags=["user_preference", "proxmox"],
        context_description="Learned from conversation about VM management",
    )
    assert "snapshot" in note.keywords
    assert note.embedding is None  # not yet computed


class TestDatabasePgvector:
    def test_has_pgvector_default_false(self):
        """Without a real database, has_pgvector should return False."""
        # This tests the attribute default
        from breadmind.storage.database import Database
        db = Database.__new__(Database)
        db._has_pgvector = False
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(db.has_pgvector())
        assert result is False
