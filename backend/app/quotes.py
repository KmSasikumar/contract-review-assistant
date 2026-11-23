"""Quote verification — the honesty check.

Every quote the AI returns must appear, word for word, in the contract
text. We normalise both sides (lowercase, collapse whitespace, unify
quotes/dashes) and check for substring containment. If the quote is not
there, the finding is marked ``unclear`` — the app never presents an
invented clause as real.

A quote may be shorter than the full clause (the model quotes the relevant
sentence); that still counts, because the sentence is in the contract.
"""
import re
import unicodedata


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def quote_in_text(quote: str, full_text: str) -> bool:
    """True if the quote appears verbatim (after normalisation) in the text."""
    q = normalize(quote)
    if len(q) < 8:  # too short to be a meaningful quote
        return False
    return q in normalize(full_text)


def find_quote_span(quote: str, full_text: str) -> tuple[int, int] | None:
    """Character span of the quote inside the (unnormalised) full text.

    Used to locate a quote for the frontend's jump-to-clause. Returns None
    when the quote is not in the text. Matching is done on normalised text,
    then mapped back approximately by length ratio.
    """
    q = normalize(quote)
    hay = normalize(full_text)
    idx = hay.find(q)
    if idx < 0:
        return None
    # Map the normalised index back to the raw text by proportional position.
    ratio = len(full_text) / max(len(hay), 1)
    start = int(idx * ratio)
    end = int((idx + len(q)) * ratio)
    return (start, min(end, len(full_text)))
