#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Independent PDF parser checks; pypdf is a test dependency, never a runtime."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, DictionaryObject, ArrayObject, NumberObject

binary = Path(sys.argv[1]).resolve()
fixtures = Path(sys.argv[2]).resolve()
checks = []
def check(value, description):
    assert value, description
    checks.append(description)
for filename in ("booklet-five.pdf", "card-a4.pdf", "interleave-reverse.pdf", "empty-removed.pdf"):
    pdf = PdfReader(fixtures / filename)
    check(all(len(page.images) == 0 for page in pdf.pages), filename + " text/vector fixture remains vector PDF without page raster images")
    check(any("România" in (page.extract_text() or "") for page in pdf.pages), filename + " existing Unicode text readable by independent parser")
book = PdfReader(fixtures / "booklet-five.pdf")
for index, expected in enumerate(((1,), (2,), (3,), (4, 5))):
    text = book.pages[index].extract_text()
    check(all(f"BOOK PAGE {n}" in text for n in expected), f"booklet physical face {index + 1} has correct semantic pages")
check(all(abs(float(page.mediabox.width) - 841.8898) < .01 and abs(float(page.mediabox.height) - 595.2756) < .01 for page in book.pages), "independent parser confirms A4 landscape media")
with tempfile.TemporaryDirectory(prefix="xerox-doc-pdf-parser-") as tmp:
    tmp = Path(tmp)
    source = fixtures / "with-empty.pdf"
    writer = PdfWriter(clone_from=source)
    writer.set_page_label(0, 2, style="/r")
    labelled = tmp / "labels.pdf"
    writer.write(labelled)
    before = hashlib.sha256(labelled.read_bytes()).hexdigest()
    check(PdfReader(labelled).page_labels == ["i", "ii", "iii"], "independent fixture has custom Roman page labels")
    output = tmp / "normal-labels.pdf"
    call = subprocess.run([str(binary), "remove-empty", "--input", str(labelled), "--output", str(output)], capture_output=True, text=True, check=True)
    check(PdfReader(output).page_labels == ["1", "2"], "output labels reset to output order as explicitly documented")
    check("page labels" in " ".join(json.loads(call.stdout)["notes"]), "report discloses page-label normalization")
    check(hashlib.sha256(labelled.read_bytes()).hexdigest() == before, "custom-label original hash unchanged")
    for key in ("/AcroForm", "/Perms"):
        writer = PdfWriter(clone_from=source)
        writer._root_object[NameObject(key)] = DictionaryObject()
        restricted = tmp / (key[1:] + ".pdf")
        writer.write(restricted)
        out = tmp / (key[1:] + "-output.pdf")
        call = subprocess.run([str(binary), "booklet", "--input", str(restricted), "--output", str(out)], capture_output=True, text=True)
        check(call.returncode != 0 and "catalog" in call.stderr and not out.exists(), key + " catalog rejected without output")
report = {"passed": True, "count": len(checks), "checks": checks, "parser": "pypdf", "runtime_dependency": False}
destination = Path(__file__).resolve().parents[1] / "evidence/pdf-structure-tests.json"
destination.parent.mkdir(exist_ok=True)
destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
print(json.dumps(report, indent=2, ensure_ascii=False))
