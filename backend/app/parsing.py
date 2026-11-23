"""File parsing: PDF, DOCX and TXT -> plain text with page numbers.

Each page/paragraph keeps its page number so chunks (and therefore findings)
can point back at exactly where a clause lives in the contract.
"""
import io
import re

MAX_CHARS = 2_000_000  # sanity cap on extracted text


class ParseError(ValueError):
    pass


def _clean(text: str) -> str:
    # Normalise line endings and collapse runs of blank lines to at most two.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_txt(data: bytes) -> tuple[str, int]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    return _clean(text), 1


def parse_pdf(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        # Prefix each page with a marker so chunking can record the page.
        page_text = (page.extract_text() or "").strip()
        pages.append(f"\n[[PAGE {i + 1}]]\n{page_text}")
    text = _clean("\n".join(pages))
    return text, len(reader.pages)


def parse_docx(data: bytes) -> tuple[str, int]:
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts: list[str] = []
    for para in doc.paragraphs:
        parts.append(para.text)
    # Tables often hold contract terms; include their cell text too.
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)
    return _clean("\n".join(parts)), 1


def parse_file(filename: str, data: bytes) -> tuple[str, int]:
    """Return (plain text, page count). Raises ParseError on bad input."""
    name = filename.lower()
    if name.endswith(".pdf"):
        text, pages = parse_pdf(data)
    elif name.endswith(".docx"):
        text, pages = parse_docx(data)
    elif name.endswith(".txt"):
        text, pages = parse_txt(data)
    else:
        raise ParseError("Unsupported file type. Upload a PDF, DOCX or TXT file.")
    if len(text) > MAX_CHARS:
        raise ParseError("Contract text is too large to process.")
    if not text.strip():
        raise ParseError("No readable text found in the file.")
    return text, pages
