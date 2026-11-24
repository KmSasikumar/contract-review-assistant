"""Review pipeline: contract -> checklist verdicts.

For each checklist item:
  1. Retrieve the most relevant chunks (vector + keyword, user-scoped).
  2. Ask the LLM, with ONLY those excerpts, for a verdict in JSON:
     status (found / not_found / unclear), a one-line summary, and a quote
     copied word for word from the excerpts.
  3. Verify the quote really appears in the contract text. If it does not,
     the item becomes ``unclear`` and the quote is flagged unverified.
  4. A ``not_found`` verdict must have no quote; the summary says plainly
     that the contract does not cover the item.

Nothing is ever assumed: if the excerpts do not show it, the answer is
not_found, never a "standard" clause.
"""
import json
import uuid

from sqlalchemy.orm import Session

from .checklist import CHECKLIST
from .embeddings import get_embedder
from .llm import get_llm_for_user
from .models import Chunk, Contract, ReviewItem
from .quotes import quote_in_text
from .retrieval import format_excerpts, retrieve

SYSTEM_PROMPT = (
    "You are a contract review assistant. You answer ONLY from the contract "
    "excerpts below. For each checklist item, return a JSON object "
    '{"items": [{"key": ..., "status": "found" | "not_found" | "unclear", '
    '"summary": "...", "quote": "...", "chunk_id": "..."}]}. '
    "Rules: status is found only when an excerpt clearly covers the item; "
    "the quote must be copied WORD FOR WORD from the excerpts, and chunk_id "
    "must be the id of the excerpt it came from. If the contract does not "
    "cover an item, status is not_found, summary is one plain-English line "
    "saying so, and quote is an empty string. Never invent, assume, or add "
    "a standard clause. If the excerpts are ambiguous, status is unclear."
)


def review_prompt(item, excerpts: str) -> list[dict]:
    items_json = json.dumps(
        [{"key": item.key, "question": item.question, "keywords": item.keywords}]
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Contract excerpts:\n{excerpts}\n\nITEMS:\n{items_json}",
        },
    ]


def run_review(
    db: Session,
    contract: Contract,
    llm=None,
    embedder=None,
) -> list[ReviewItem]:
    """Run the full checklist review for one contract. Returns the items."""
    llm = llm or get_llm_for_user(db, contract.user_id)
    embedder = embedder or get_embedder()
    user_id = contract.user_id

    # One embedding pass per item would waste calls; embed the item questions
    # once up front, then review each item separately for clean JSON.
    item_texts = [f"{it.label}. {it.question}" for it in CHECKLIST]
    try:
        item_vecs = embedder.embed(item_texts)
    except Exception:
        item_vecs = [None] * len(CHECKLIST)

    results: list[ReviewItem] = []
    for item, vec, item_text in zip(CHECKLIST, item_vecs, item_texts):
        chunks = retrieve(
            db, user_id, contract.id, item.keywords, vec
        )
        excerpts = format_excerpts(chunks)
        try:
            parsed = llm.complete_json(review_prompt(item, excerpts))
            # Guard: if the model returns "items" as a non-list (a float,
            # a dict, a string), indexing it raises TypeError and fails
            # the whole review. Only a real list is usable.
            items = parsed.get("items")
            raw = items[0] if isinstance(items, list) and items else {}
        except Exception:
            raw = {}
        status = raw.get("status") if raw.get("status") in ("found", "not_found", "unclear") else "unclear"
        summary = str(raw.get("summary") or "")
        quote = str(raw.get("quote") or "")
        chunk_id = raw.get("chunk_id")

        verified = False
        if status == "found":
            # A "Found" verdict is only real when its quote is verified.
            # An empty quote skips verification entirely, so it must fail
            # the same way an unverifiable quote does — otherwise the
            # user sees a green "Found" with no evidence at all.
            if quote:
                verified = quote_in_text(quote, contract.full_text)
            if not verified:
                status = "unclear"
                summary = summary or "The quoted text could not be verified in the contract."
        if status == "not_found":
            quote = ""
            if not summary:
                summary = f"Not found in the contract: {item.label.lower()}."
        # Resolve the cited chunk (only if it belongs to this contract).
        # The id arrives as a string; the Uuid column needs a UUID object.
        chunk = None
        if chunk_id:
            try:
                chunk_uuid = uuid.UUID(str(chunk_id))
            except (ValueError, TypeError):
                chunk_uuid = None
            if chunk_uuid is not None:
                chunk = (
                    db.query(Chunk)
                    .filter(Chunk.id == chunk_uuid, Chunk.contract_id == contract.id)
                    .first()
                )
        page = chunk.page if chunk else None
        section = chunk.section if chunk else None

        existing = (
            db.query(ReviewItem)
            .filter(ReviewItem.contract_id == contract.id, ReviewItem.key == item.key)
            .first()
        )
        if existing:
            existing.status, existing.summary = status, summary
            existing.quote, existing.quote_verified = quote, verified
            existing.chunk_id, existing.page, existing.section = (
                chunk.id if chunk else None,
                page,
                section,
            )
            results.append(existing)
        else:
            row = ReviewItem(
                contract_id=contract.id,
                user_id=user_id,
                key=item.key,
                status=status,
                summary=summary,
                quote=quote,
                quote_verified=verified,
                chunk_id=chunk.id if chunk else None,
                page=page,
                section=section,
            )
            db.add(row)
            results.append(row)
    # Say so on the contract when the backup model did (part of) the review.
    if getattr(llm, "fallback_used", False):
        note = "OpenRouter chat was rate-limited, so the Groq backup model wrote this review."
        contract.review_note = f"{contract.review_note} {note}".strip() if contract.review_note else note
    db.commit()
    return results


def get_review(db: Session, user_id: str, contract_id) -> list[ReviewItem]:
    return (
        db.query(ReviewItem)
        .filter(ReviewItem.user_id == user_id, ReviewItem.contract_id == contract_id)
        .order_by(ReviewItem.key)
        .all()
    )
