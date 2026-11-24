"""Retrieval tests.

Vector similarity is computed in Python (cosine) over the fetched chunks
on every database — the Postgres-only pgvector <=> SQL path was removed
24 Nov 2026 after it broke live twice in one day (cosine_distance missing
on the EmbeddingType TypeDecorator, then a "'float' object is not
subscriptable" failure in the shared retrieve path). These tests pin the
Python-cosine behaviour that the live review and chat now depend on.
"""
import uuid

from app.models import Chunk
from app.retrieval import retrieve


def test_retrieve_ranks_by_keyword_then_vector(db):
    """Keyword hits rank first; the vector score breaks ties."""
    cid = uuid.uuid4()
    ch1 = Chunk(user_id="u1", contract_id=cid, text="payment terms payable fees", embedding=[1.0, 0.0])
    ch2 = Chunk(user_id="u1", contract_id=cid, text="governing law jurisdiction", embedding=[0.0, 1.0])
    db.add_all([ch1, ch2])
    db.commit()

    got = retrieve(db, "u1", cid, keywords=["payment"], query_embedding=[1.0, 0.0])
    assert got, "retrieve should return chunks"
    assert got[0].text.startswith("payment"), "payment chunk should rank first"


def test_retrieve_works_without_embedding(db):
    """With no query embedding, retrieval is keyword-only (no crash)."""
    cid = uuid.uuid4()
    ch1 = Chunk(user_id="u1", contract_id=cid, text="payment terms payable fees", embedding=[1.0, 0.0])
    db.add(ch1)
    db.commit()

    got = retrieve(db, "u1", cid, keywords=["payment"], query_embedding=None)
    assert len(got) == 1
    assert got[0].text.startswith("payment")
