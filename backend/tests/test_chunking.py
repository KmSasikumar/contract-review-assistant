"""Chunking: clause boundaries kept, page numbers tracked, long paragraphs split."""
from app.chunking import chunk_text


def test_paragraphs_become_chunks():
    text = "First clause about payment.\n\nSecond clause about term."
    chunks = chunk_text(text)
    assert [c.text for c in chunks] == [
        "First clause about payment.",
        "Second clause about term.",
    ]


def test_page_markers_tracked():
    text = "[[PAGE 1]]\nClause on page one.\n\n[[PAGE 2]]\nClause on page two."
    chunks = chunk_text(text)
    assert chunks[0].page == 1
    assert chunks[1].page == 2


def test_headings_become_sections():
    text = "1. Payment Terms\n\nPay within 30 days.\n\n2. Termination\n\nEither party may end it."
    chunks = chunk_text(text)
    assert chunks[0].section == "1. Payment Terms"
    assert chunks[0].text == "Pay within 30 days."
    assert chunks[1].section == "2. Termination"


def test_long_paragraph_splits_on_sentences():
    para = " ".join(f"Sentence number {i} about the agreement." for i in range(120))
    chunks = chunk_text(para)
    assert len(chunks) > 1
    assert all(len(c.text) <= 2000 for c in chunks)
    # No sentence is lost or duplicated.
    joined = " ".join(c.text for c in chunks)
    assert "Sentence number 0" in joined and "Sentence number 119" in joined


def test_empty_text_yields_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("\n\n  \n") == []
