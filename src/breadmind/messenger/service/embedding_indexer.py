# src/breadmind/messenger/service/embedding_indexer.py
"""Background indexer: messages → embedding column.

Polls messages WHERE embedding IS NULL AND kind='text' AND deleted_at IS NULL,
batches 100 at a time, calls embedder, stores vector.
"""
from __future__ import annotations
from typing import Protocol


class Embedder(Protocol):
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


async def index_pending_messages(db, embedder: Embedder, *, batch_size: int = 100) -> int:
    rows = await db.fetch(
        """SELECT id, text FROM messages
           WHERE embedding IS NULL AND kind = 'text' AND deleted_at IS NULL
             AND text IS NOT NULL AND length(text) >= 5
           ORDER BY created_at LIMIT $1""", batch_size,
    )
    if not rows:
        return 0
    embeddings = await embedder.embed_batch([r["text"] for r in rows])
    for row, emb in zip(rows, embeddings):
        vec_str = "[" + ",".join(str(float(x)) for x in emb) + "]"
        await db.execute(
            "UPDATE messages SET embedding = $1::vector WHERE id = $2",
            vec_str, row["id"],
        )
    return len(rows)
