"""Upload pipeline: extract text, chunk, embed, review.

Runs in a background task so a large file never blocks the upload request.
Each step updates the contract status; any failure lands in ``error`` and
sets status ``failed`` (the frontend shows the message and offers a retry).
"""
import uuid

from sqlalchemy.orm import Session

from ..chunking import chunk_text
from ..db import SessionLocal
from ..embeddings import HashEmbedder, RateLimitError, get_embedder
from ..models import Chunk, Contract
from ..parsing import ParseError, parse_file
from ..review import run_review


def create_contract(db: Session, user_id: str, filename: str, size: int, mime: str) -> Contract:
    contract = Contract(
        user_id=user_id,
        filename=filename,
        size_bytes=size,
        mime_type=mime,
        status="processing",
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


def process_contract(contract_id: uuid.UUID, data: bytes, filename: str) -> None:
    """Background task: parse -> chunk -> embed -> review."""
    db = SessionLocal()
    try:
        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        if contract is None:
            return
        try:
            _process(db, contract, data, filename)
        except Exception as exc:
            # Any unexpected failure (corrupt file, AI outage, DB error)
            # must land the contract in "failed" with a message. Without
            # this, the contract stays "processing" forever and the
            # frontend polls it forever — the user sees a stuck spinner
            # with no error and no retry button.
            try:
                db.rollback()
            except Exception:
                pass
            try:
                contract.status, contract.error = "failed", str(exc) or exc.__class__.__name__
                db.commit()
            except Exception:
                pass
    finally:
        db.close()


def _process(db: Session, contract: Contract, data: bytes, filename: str) -> None:
    """Parse -> chunk -> embed -> review. Raises on any failure; the caller
    turns the failure into a "failed" contract status."""
    try:
        text, pages = parse_file(filename, data)
    except ParseError as exc:
        contract.status, contract.error = "failed", str(exc)
        db.commit()
        return
    contract.full_text, contract.page_count = text, pages

    drafts = chunk_text(text)
    embedder = get_embedder()
    try:
        vectors = embedder.embed([d.text for d in drafts]) if drafts else []
    except RateLimitError:
        # OpenRouter's free tier is 50 free-model requests/day; once it
        # is exhausted the review would otherwise fail outright. Fall
        # back to keyword retrieval (hash vectors only break ties) and
        # say so on the contract.
        embedder = HashEmbedder()
        vectors = embedder.embed([d.text for d in drafts]) if drafts else []
        contract.review_note = (
            "OpenRouter embeddings were rate-limited, so retrieval used "
            "keywords instead of live embeddings."
        )
    for i, (draft, vec) in enumerate(zip(drafts, vectors)):
        db.add(
            Chunk(
                contract_id=contract.id,
                user_id=contract.user_id,
                chunk_index=i,
                page=draft.page,
                section=draft.section,
                text=draft.text,
                embedding=vec,
            )
        )
    db.commit()
    try:
        run_review(db, contract, embedder=embedder)
        contract.status, contract.error = "reviewed", None
    except Exception as exc:  # AI unavailable (no key / rate limit / outage)
        contract.status, contract.error = "failed", str(exc)
    db.commit()


def retry_review(contract_id: uuid.UUID) -> Contract | None:
    """Re-run the review for a failed contract (chunks already stored)."""
    db = SessionLocal()
    try:
        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        if contract is None:
            return None
        contract.status, contract.error = "processing", None
        db.commit()
        try:
            run_review(db, contract)
            contract.status, contract.error = "reviewed", None
        except Exception as exc:
            contract.status, contract.error = "failed", str(exc)
        db.commit()
        db.refresh(contract)
        return contract
    finally:
        db.close()
