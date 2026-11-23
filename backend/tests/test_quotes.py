"""Quote verification: exact quotes pass, invented ones fail."""
from app.quotes import find_quote_span, normalize, quote_in_text

CONTRACT = (
    "Acme will pay Northwind INR 5,00,000 per quarter. "
    "Each invoice is payable within thirty (30) days of receipt."
)


def test_exact_quote_passes():
    assert quote_in_text("Acme will pay Northwind INR 5,00,000 per quarter.", CONTRACT)


def test_case_and_whitespace_differences_pass():
    assert quote_in_text("  acme   will pay\nnorthwind INR 5,00,000 per quarter. ", CONTRACT)


def test_invented_quote_fails():
    assert not quote_in_text("Acme will pay Northwind INR 9,99,999 per month.", CONTRACT)


def test_partial_sentence_still_verifies():
    # The model may quote one sentence out of a longer clause.
    assert quote_in_text("Each invoice is payable within thirty (30) days of receipt.", CONTRACT)


def test_too_short_quote_rejected():
    assert not quote_in_text("Acme", CONTRACT)


def test_normalize_unifies_smart_quotes():
    assert normalize("\u201cHello\u201d") == '"hello"'


def test_find_quote_span():
    span = find_quote_span("payable within thirty (30) days", CONTRACT)
    assert span is not None
    start, end = span
    assert "payable" in CONTRACT[start:end]
