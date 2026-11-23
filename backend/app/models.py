"""Database models.

Every row that belongs to a user carries that user's Clerk id (``user_id``).
All queries filter on it — see isolation.py. A user can never see another
user's rows, even if they guess an id, because the filter is applied in the
service layer on every single query.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from .db import Base, EmbeddingType


def _utcnow():
    return datetime.now(timezone.utc)


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # processing | reviewed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set when the review ran on a fallback (e.g. Groq backup after an
    # OpenRouter rate limit), so the user can see which AI did the work.
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="contract", cascade="all, delete-orphan"
    )
    review_items: Mapped[list["ReviewItem"]] = relationship(
        "ReviewItem", back_populates="contract", cascade="all, delete-orphan"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="contract", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """One clause-sized piece of a contract.

    Chunks keep clause/section boundaries: a chunk is a paragraph or a
    numbered section, never a blind fixed-size slice. ``page`` and ``section``
    are recorded so a finding can point back at exactly where it came from.
    """

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(nullable=False, default=0)
    page: Mapped[int | None] = mapped_column(nullable=True)
    section: Mapped[str | None] = mapped_column(String(512), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType, nullable=True)

    contract: Mapped[Contract] = relationship("Contract", back_populates="chunks")

    __table_args__ = (Index("ix_chunks_contract_index", "contract_id", "chunk_index"),)


class ReviewItem(Base):
    """One checklist item's verdict for one contract."""

    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    # found | not_found | unclear
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    page: Mapped[int | None] = mapped_column(nullable=True)
    section: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    contract: Mapped[Contract] = relationship("Contract", back_populates="review_items")

    __table_args__ = (UniqueConstraint("contract_id", "key", name="uq_review_contract_key"),)


class ChatMessage(Base):
    """One chat turn about a contract. History persists across refreshes."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON string: [{"quote": ..., "chunk_id": ..., "page": ..., "verified": bool}]
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    contract: Mapped[Contract] = relationship("Contract", back_populates="messages")
