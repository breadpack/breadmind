from breadmind.kb.retriever import KBRetriever


async def test_vector_only_returns_closest(db, seeded_kb, seeded_project, embedder, acl):
    retriever = KBRetriever(db=db, embedder=embedder, acl=acl)
    hits = await retriever._vector_search(
        query="payments memory leak",
        project_id=seeded_project,
        limit=20,
    )
    assert hits, "vector search returned nothing"
    # vec_a (0.1) matches the 'leak' branch; row A should rank first.
    assert hits[0][0] == seeded_kb[0]


async def test_fts_search_matches_keyword(db, seeded_kb, seeded_project, embedder, acl):
    retriever = KBRetriever(db=db, embedder=embedder, acl=acl)
    hits = await retriever._fts_search(
        query="memory leak payments",
        project_id=seeded_project,
        limit=20,
    )
    ids = [h[0] for h in hits]
    assert seeded_kb[0] in ids, "BM25 must surface the leak-fix row"
