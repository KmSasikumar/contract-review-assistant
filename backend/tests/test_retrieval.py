"""Retrieval tests.

The Postgres vector path (pgvector <=> in SQL) is NOT exercised by the
SQLite test DB, so a query-construction regression there once 500'd every
live review (24 Nov 2026: Chunk.embedding.cosine_distance does not exist
on the EmbeddingType TypeDecorator). These tests compile the Postgres
query to SQL, which fails at construction time if the operator is wrong.
"""
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import Chunk


def test_postgres_vector_query_builds():
    """The pgvector cosine-distance query must build against Postgres.

    Regression test for the 24 Nov 2026 live failure: calling
    Chunk.embedding.cosine_distance(...) raised AttributeError because
    EmbeddingType (a TypeDecorator) does not expose pgvector's comparator
    methods. The query now uses the generic .op("<=>") operator.
    """
    stmt = (
        select(Chunk.id, Chunk.embedding.op("<=>")([0.1, 0.2, 0.3]).label("d"))
        .where(Chunk.user_id == "u1", Chunk.contract_id == 1)
        .order_by("d")
        .limit(9)
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "<=>" in sql
    assert "embedding" in sql


def test_retrieve_falls_back_to_python_cosine_on_sqlite(db):
    """On SQLite, retrieve() scores vectors in Python (no pgvector)."""
    import uuid

    from app.retrieval import retrieve

    cid = uuid.uuid4()
    ch1 = Chunk(user_id="u1", contract_id=cid, text="payment terms payable fees", embedding=[1.0, 0.0])
    ch2 = Chunk(user_id="u1", contract_id=cid, text="governing law jurisdiction", embedding=[0.0, 1.0])
    db.add_all([ch1, ch2])
    db.commit()

    got = retrieve(db, "u1", cid, keywords=["payment"], query_embedding=[1.0, 0.0])
    assert got, "retrieve should return chunks"
    assert got[0].text.startswith("payment"), "payment chunk should rank first"
