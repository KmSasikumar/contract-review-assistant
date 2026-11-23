"""Pydantic response schemas (what the API returns)."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ContractOut(BaseModel):
    id: UUID
    filename: str
    size_bytes: int
    mime_type: str
    status: str
    error: str | None = None
    review_note: str | None = None
    page_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class ChunkOut(BaseModel):
    id: UUID
    chunk_index: int
    page: int | None = None
    section: str | None = None
    text: str

    class Config:
        from_attributes = True


class ReviewItemOut(BaseModel):
    key: str
    label: str
    status: str
    summary: str
    quote: str | None = None
    quote_verified: bool
    chunk_id: UUID | None = None
    page: int | None = None
    section: str | None = None

    class Config:
        from_attributes = True


class ReviewOut(BaseModel):
    contract_id: UUID
    items: list[ReviewItemOut]
    risk_flags: list[str]


class ChatMessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    sources: list[dict] = []
    created_at: datetime

    class Config:
        from_attributes = True


class ChatAsk(BaseModel):
    question: str


class HealthOut(BaseModel):
    ok: bool
    ai_configured: bool
    auth_configured: bool
