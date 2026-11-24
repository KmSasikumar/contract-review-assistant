"""Parsing: TXT / PDF / DOCX extraction, page numbers, bad input."""
import io

from app.parsing import ParseError, parse_file


def test_parse_txt():
    text, pages = parse_file("a.txt", b"Hello\n\nWorld")
    assert "Hello" in text and "World" in text
    assert pages == 1


def test_parse_pdf_two_pages():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 720, "First page clause.")
    c.showPage()
    c.drawString(72, 720, "Second page clause.")
    c.save()
    text, pages = parse_file("a.pdf", buf.getvalue())
    assert pages == 2
    assert "First page clause." in text
    assert "Second page clause." in text
    assert "[[PAGE 1]]" in text and "[[PAGE 2]]" in text


def test_parse_docx():
    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph("Services clause.")
    doc.add_paragraph("Payment clause.")
    doc.save(buf)
    text, pages = parse_file("a.docx", buf.getvalue())
    assert "Services clause." in text
    assert "Payment clause." in text


def test_parse_docx_table_row_stays_together():
    """A table row's label and value stay on one line, so the review
    sees them together instead of attributing the wrong cell's value."""
    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Payment"
    table.rows[0].cells[1].text = "Net 30"
    table.rows[1].cells[0].text = "Governing law"
    table.rows[1].cells[1].text = "India"
    doc.save(buf)
    text, pages = parse_file("a.docx", buf.getvalue())
    assert "Payment | Net 30" in text
    assert "Governing law | India" in text


def test_parse_unsupported_type():
    try:
        parse_file("a.png", b"\x89PNG")
    except ParseError as exc:
        assert "PDF, DOCX or TXT" in str(exc)
    else:
        raise AssertionError("expected ParseError")


def test_parse_empty_file():
    try:
        parse_file("a.txt", b"   \n  ")
    except ParseError as exc:
        assert "No readable text" in str(exc)
    else:
        raise AssertionError("expected ParseError")
