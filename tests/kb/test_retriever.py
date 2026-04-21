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
        query="memory leak payment",
        project_id=seeded_project,
        limit=20,
    )
    ids = [h[0] for h in hits]
    assert seeded_kb[0] in ids, "BM25 must surface the leak-fix row"


def test_rrf_fuse_prefers_shared_ranks(embedder, acl):
    from breadmind.kb.retriever import KBRetriever
    r = KBRetriever(db=None, embedder=embedder, acl=acl)
    vec = [(1, 0.9), (2, 0.8), (3, 0.7)]
    fts = [(3, 2.0), (2, 1.5), (1, 1.0)]
    fused = r._rrf_fuse(vec, fts, k=60)
    ranked_ids = [kid for kid, _ in fused]
    assert ranked_ids[0] in {1, 3}
    assert set(ranked_ids) == {1, 2, 3}
    # Every id appearing in both lists must beat an id appearing in only one.
    assert all(fused[0][1] >= score for _, score in fused)
