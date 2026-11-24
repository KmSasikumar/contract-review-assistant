"""Follow-up chat about one contract.

Same grounding rules as the review: the answer comes only from the
contract. The model is given the retrieved chunks and must end its answer
with a Sources section listing the chunk ids and the exact quotes it used:

    Sources:
    - [chunk <id> | page <n>] "exact quote"

The backend parses that section, verifies each quote against the contract
text, and stores the verified sources with the message. The streamed text
reaches the user as it is generated; the stored message carries the
verification result.
"""
import json
import re

from sqlalchemy.orm import Session

from .embeddings import get_embedder
from .llm import get_llm_for_user
from .models import ChatMessage, Chunk, Contract
from .quotes import quote_in_text
from .retrieval import content_words, format_excerpts, retrieve

SYSTEM_PROMPT = (
    "You are a contract assistant. Answer ONLY from the contract excerpts "
    "below. Quote the relevant clause word for word when you use one, and "
    "end your answer with a Sources section listing each quote you used:\n"
    "Sources:\n"
    '- [chunk <id> | page <n>] "exact quote"\n'
    "If the contract does not answer the question, say so plainly and do "
    "not guess. Never invent a clause."
)

SOURCE_RE = re.compile(
    r'\[chunk ([0-9a-f\-]+) \| page (\d+|-)\]\s*"([^"]+)"', re.IGNORECASE
)


def extract_sources(answer: str, contract: Contract) -> list[dict]:
    """Parse the Sources section; verify every quote against the contract."""
    sources = []
    for m in SOURCE_RE.finditer(answer):
        chunk_id, page, quote = m.group(1), m.group(2), m.group(3)
        sources.append(
            {
                "chunk_id": chunk_id,
                "page": int(page) if page.isdigit() else None,
                "quote": quote,
                "verified": quote_in_text(quote, contract.full_text),
            }
        )
    return sources


def chat_prompt(question: str, excerpts: str, history: list[ChatMessage]) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history[-6:]:  # last few turns for context, not the whole history
        messages.append({"role": msg.role, "content": msg.content})
    messages.append(
        {"role": "user", "content": f"Contract excerpts:\n{excerpts}\n\nQuestion: {question}"}
    )
    return messages


def answer_stream(db: Session, contract: Contract, question: str, llm=None, embedder=None):
    """Yield answer chunks as they are generated, then persist both turns.

    Yields dicts: {"type": "token", "text": ...} during generation, then a
    final {"type": "done", "sources": [...]} with the verified sources.
    """
    llm = llm or get_llm_for_user(db, contract.user_id)
    embedder = embedder or get_embedder()
    user_id = contract.user_id

    keywords = content_words(question)
    try:
        vec = embedder.embed([question])[0]
    except Exception:
        vec = None
    chunks = retrieve(db, user_id, contract.id, keywords, vec, top_k=6)
    history = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user_id, ChatMessage.contract_id == contract.id)
        .order_by(ChatMessage.created_at)
        .all()
    )
    prompt = chat_prompt(question, format_excerpts(chunks), history)

    db.add(ChatMessage(contract_id=contract.id, user_id=user_id, role="user", content=question))
    db.commit()

    full = ""
    try:
        for token in llm.stream(prompt):
            full += token
            yield {"type": "token", "text": token}
    except Exception as exc:
        # A mid-stream failure (e.g. rate limit) is reported, not hidden.
        yield {"type": "error", "text": str(exc)}
        full += f"\n\n[The answer stopped early: {exc}]"

    sources = extract_sources(full, contract)
    if getattr(llm, "fallback_used", False):
        note = "OpenRouter chat was rate-limited, so the Groq backup model wrote this answer."
        contract.review_note = f"{contract.review_note} {note}".strip() if contract.review_note else note
    db.add(
        ChatMessage(
            contract_id=contract.id,
            user_id=user_id,
            role="assistant",
            content=full,
            sources=json.dumps(sources),
        )
    )
    db.commit()
    yield {"type": "done", "sources": sources}


def get_history(db: Session, user_id: str, contract_id) -> list[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user_id, ChatMessage.contract_id == contract_id)
        .order_by(ChatMessage.created_at)
        .all()
    )
