"""Generate PDF versions of the sample contracts (for the demo upload).

Usage: python3 samples/generate_pdfs.py
Writes sample-contract-complete.pdf and sample-contract-missing-items.pdf
next to the .txt files. Page numbers are printed in the footer so the
review's page citations are meaningful in the demo.
"""
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

HERE = os.path.dirname(os.path.abspath(__file__))


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 9)
    canvas.drawCentredString(A4[0] / 2, 1.5 * cm, f"Page {doc.page}")
    canvas.restoreState()


def txt_to_pdf(txt_path: str, pdf_path: str) -> None:
    with open(txt_path, encoding="utf-8") as fh:
        lines = [line.rstrip("\n") for line in fh]
    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title2", parent=styles["Title"], fontSize=16, spaceAfter=12)
    body = ParagraphStyle("Body2", parent=styles["BodyText"], fontSize=11, leading=15, spaceAfter=8)
    heading = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=10)
    story = []
    first = True
    for line in lines:
        if not line.strip():
            story.append(Spacer(1, 4))
            continue
        if first:
            story.append(Paragraph(line, title))
            first = False
        elif line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.")) and len(line) < 60:
            story.append(Paragraph(line, heading))
        else:
            story.append(Paragraph(line, body))
    doc = SimpleDocTemplate(pdf_path, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


if __name__ == "__main__":
    for name in ("sample-contract-complete", "sample-contract-missing-items"):
        txt_to_pdf(os.path.join(HERE, f"{name}.txt"), os.path.join(HERE, f"{name}.pdf"))
        print(f"wrote {name}.pdf")
