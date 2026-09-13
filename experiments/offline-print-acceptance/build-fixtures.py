#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create deterministic synthetic PDFs for local Apple print-filter checks.

This program never submits a print job or contacts a device.
"""
import hashlib
import json
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from pypdf import PdfReader

OUT = Path(__file__).resolve().parent / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def create(name, count, size):
    path = OUT / name
    width, height = (value * mm for value in size)
    pdf = canvas.Canvas(str(path), pagesize=(width, height), invariant=1,
                        pageCompression=1)
    pdf.setTitle("Offline Apple print-filter acceptance - synthetic only")
    pdf.setAuthor("Xerox3025 modernization local test")
    for page in range(1, count + 1):
        pdf.setStrokeColorRGB(0, 0, 0)
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setLineWidth(.5 * mm)
        pdf.rect(10 * mm, 10 * mm, width - 20 * mm, height - 20 * mm)
        pdf.setFont("Helvetica-Bold", min(66, width / 6))
        pdf.drawCentredString(width / 2, height * .59, f"PAGE {page:02d}")
        pdf.setFont("Helvetica-Bold", 17)
        pdf.drawString(15 * mm, height - 22 * mm, "TOP LEFT")
        pdf.drawRightString(width - 15 * mm, height - 22 * mm, "RIGHT")
        pdf.setFont("Helvetica", 12)
        pdf.drawCentredString(width / 2, 20 * mm, f"BOTTOM {page:02d}")
        pdf.setFont("Helvetica", 9)
        pdf.drawCentredString(width / 2, height * .50, "OFFLINE HOST RENDERING ONLY")
        # Two solid fiducials are useful for geometry even if OCR misses a label.
        pdf.rect(20 * mm, height * .35, 30 * mm, 5 * mm, stroke=0, fill=1)
        pdf.circle(width - 25 * mm, height * .35, 3 * mm, stroke=0, fill=1)
        pdf.showPage()
    pdf.save()
    document = PdfReader(path)
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "pages": len(document.pages), "size_mm": list(size),
            "media_boxes_points": [list(map(float, page.mediabox)) for page in document.pages]}


if __name__ == "__main__":
    fixtures = [create("labels-16.pdf", 16, (210, 297)),
                create("labels-4.pdf", 4, (210, 297)),
                create("geometry-a4.pdf", 1, (210, 297)),
                create("geometry-wide.pdf", 1, (300, 180)),
                create("geometry-custom.pdf", 1, (100, 150))]
    (OUT / "manifest.json").write_text(json.dumps(fixtures, indent=2) + "\n")
    print(json.dumps(fixtures, indent=2))
