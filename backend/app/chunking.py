"""Clause-aware chunking.

A chunk is a paragraph or a numbered section — never a blind fixed-size
slice — so a clause is never split across two chunks and a finding's quote
always comes from one identifiable clause. Page markers (``[[PAGE n]]``,
inserted by the PDF parser) are tracked so every chunk knows its page.
Section headings (``1. ...``, ``Section 3: ...``, ``ARTICLE II``) are
recorded as the chunk's section.
"""
import re

PAGE_RE = re.compile(r"\[\[PAGE (\d+)\]\]")
# "Section 3" / "Article II" / "1. ..." headings — case-insensitive.
HEADING_RE = re.compile(
    r"^\s*("
    r"(?:section|article|clause)\s+\d+[A-Za-z0-9.\-]*"
    r"|\d+[.)]\s+\S.*"
    r")\s*$",
    re.IGNORECASE,
)
# ALL-CAPS headings only ("ARTICLE II", "PAYMENT TERMS"). Case-sensitive
# and letters-only on purpose: with IGNORECASE this class also matches
# ordinary lowercase clauses ("Payment", "Net 30"), and with digits it
# matches table-cell values ("USD 500000", "NET 30") — either way the
# chunker would silently drop real contract content as if it were a
# heading. A line with digits is a value, not a heading; it stays a chunk.
ALLCAPS_HEADING_RE = re.compile(r"^\s*[A-Z][A-Z ,&\-]{4,}\s*$")
# A very long paragraph is split on sentence boundaries so no chunk is huge.
MAX_CHUNK_CHARS = 2000
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])")


class ChunkDraft:
    def __init__(self, text: str, page: int | None, section: str | None):
        self.text = text
        self.page = page
        self.section = section


def _split_long(text: str, page: int | None, section: str | None) -> list[ChunkDraft]:
    """Split an over-long paragraph on sentence boundaries, keeping order."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [ChunkDraft(text, page, section)]
    sentences = SENTENCE_RE.split(text)
    out: list[ChunkDraft] = []
    buf = ""
    for sent in sentences:
        if buf and len(buf) + len(sent) + 1 > MAX_CHUNK_CHARS:
            out.append(ChunkDraft(buf.strip(), page, section))
            buf = sent
        else:
            buf = f"{buf} {sent}".strip() if buf else sent
    if buf.strip():
        out.append(ChunkDraft(buf.strip(), page, section))
    return out


def chunk_text(full_text: str) -> list[ChunkDraft]:
    """Split contract text into clause-sized chunks with page/section."""
    chunks: list[ChunkDraft] = []
    page: int | None = None
    section: str | None = None
    for raw_para in full_text.split("\n"):
        para = raw_para.strip()
        if not para:
            continue
        m = PAGE_RE.match(para)
        if m:
            page = int(m.group(1))
            continue
        # A heading line becomes the section for the chunks that follow it.
        if (HEADING_RE.match(para) or ALLCAPS_HEADING_RE.match(para)) and len(para) < 120:
            section = para
            continue
        chunks.extend(_split_long(para, page, section))
    return chunks
