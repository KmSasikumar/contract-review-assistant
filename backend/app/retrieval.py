"""Retrieval: find the chunks that answer a question, scoped to one user
and one contract.

Two signals, merged:
  1. Vector similarity (cosine) between the query embedding and each chunk
     embedding. On Postgres this runs in SQL via pgvector's <=> operator;
     on SQLite (tests) it runs in Python over the stored vectors.
  2. Keyword overlap between the query's keywords and the chunk text —
     contracts reuse the same legal words, so a keyword hit is strong
     evidence even when the embedding is weak.

Ranking: keyword hits first, vector similarity second. In contract text
the same legal terms repeat, so a chunk that literally mentions the
concept is almost always the right one; the embedding breaks ties.
"""
import math
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Chunk

# Words that carry no retrieval signal (dropped from free-text questions).
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "when", "while",
    "of", "at", "by", "for", "with", "about", "into", "through", "after", "over",
    "between", "out", "against", "during", "without", "before", "under", "around",
    "among", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "having", "do", "does", "did", "doing", "would", "should", "could",
    "ought", "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
    "us", "them", "my", "your", "his", "its", "our", "their", "this", "that",
    "these", "those", "am", "as", "in", "on", "to", "from", "what", "which",
    "who", "whom", "how", "why", "where", "not", "no", "yes", "can", "will",
    "just", "so", "than", "too", "very",
}


def content_words(text: str) -> list[str]:
    """Lowercase words of 3+ letters, minus stopwords (deduped, in order)."""
    seen: list[str] = []
    for w in re.findall(r"[a-z]{3,}", text.lower()):
        if w not in STOPWORDS and w not in seen:
            seen.append(w)
    return seen


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _stem(word: str) -> str:
    """Light stem: strip common suffixes so morphological variants match
    (payment ~ payable, terms ~ term, parties ~ party, fees ~ fee).
    Keeps at least 3 letters, so short words are never mangled."""
    if word.endswith("ies") and len(word) - 3 >= 3:
        word = word[:-3] + "y"
    changed = True
    while changed:
        changed = False
        for suf in ("ments", "ment", "able", "ible", "ing", "ed", "es", "s"):
            if word.endswith(suf) and len(word) - len(suf) >= 3:
                word = word[: -len(suf)]
                changed = True
                break
    return word


def keyword_hits(text: str, keywords: list[str]) -> int:
    """Count keywords present in text.

    Single words match on light stems, so a question asking about
    'payment terms' finds a clause about 'payable fees'. Phrase keywords
    ('entered into', 'starts on', 'continues for') match as substrings,
    exactly as before — stemming must never drop a phrase match."""
    low = text.lower()
    stems = {_stem(w) for w in re.findall(r"[a-z]{3,}", low)}
    hits = 0
    for kw in keywords:
        k = kw.lower()
        if " " in k:
            if k in low:
                hits += 1
        elif _stem(k) in stems:
            hits += 1
    return hits


def retrieve(
    db: Session,
    user_id: str,
    contract_id,
    keywords: list[str],
    query_embedding: list[float] | None = None,
    top_k: int | None = None,
) -> list[Chunk]:
    top_k = top_k or settings.retrieve_top_k
    chunks = (
        db.execute(
            select(Chunk).where(Chunk.user_id == user_id, Chunk.contract_id == contract_id)
        )
        .scalars()
        .all()
    )
    if not chunks:
        return []

    # Vector scores: pgvector in SQL on Postgres, Python cosine otherwise.
    vec_scores: dict[str, float] = {}
    if query_embedding is not None and db.bind.dialect.name == "postgresql":
        # NOTE: Chunk.embedding is an EmbeddingType TypeDecorator, whose
        # comparator does NOT expose pgvector's cosine_distance() method
        # (that raised AttributeError and 500'd every live review on
        # 24 Nov 2026). Use the generic .op("<=>") operator instead —
        # pgvector's cosine-distance operator — which any column supports.
        rows = (
            db.execute(
                select(Chunk.id, Chunk.embedding.op("<=>")(query_embedding).label("d"))
                .where(Chunk.user_id == user_id, Chunk.contract_id == contract_id)
                .order_by("d")
                .limit(top_k * 3)
            )
            .all()
        )
        for row in rows:
            vec_scores[str(row.id)] = 1.0 - float(row.d)
    elif query_embedding is not None:
        for ch in chunks:
            if ch.embedding:
                vec_scores[str(ch.id)] = cosine(query_embedding, ch.embedding)

    scored = []
    for ch in chunks:
        # Search the section heading too: a clause headed "3. Fees and
        # Payment" is about payment even if the paragraph body says "payable".
        hits = keyword_hits((ch.section or "") + " " + ch.text, keywords)
        score = vec_scores.get(str(ch.id), 0.0) + 0.25 * min(hits, 4)
        scored.append((score, hits, ch))
    # Keyword hits rank first, vector score breaks ties.
    scored.sort(key=lambda s: (s[1], s[0]), reverse=True)
    return [ch for _, _, ch in scored[:top_k]]


def format_excerpts(chunks: list[Chunk]) -> str:
    """Render chunks for the LLM prompt, labelled so quotes can be traced."""
    lines = []
    for ch in chunks:
        page = ch.page if ch.page is not None else "-"
        section = ch.section or "-"
        lines.append(f"[chunk {ch.id} | page {page} | {section}]\n{ch.text}")
    return "\n\n".join(lines)
