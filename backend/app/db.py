"""Database setup.

Postgres + pgvector in production (docker-compose). SQLite for tests and for
running the backend without Docker — the embedding column degrades to JSON
and retrieval falls back to keyword matching (see review.py).
"""
from sqlalchemy import JSON, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import settings

try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pgvector not installed in some test envs
    Vector = None


class EmbeddingType(TypeDecorator):
    """2048-dim embedding. VECTOR(2048) on Postgres, JSON on anything else."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and Vector is not None:
            return dialect.type_descriptor(Vector(2048))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(v) for v in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(v) for v in value]


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db(url: str | None = None):
    """Create the pgvector extension (Postgres only) and all tables."""
    eng = make_engine(url) if url else engine
    if eng.dialect.name == "postgresql":
        with eng.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    # Import models so Base knows about them before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=eng)
    return eng


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
