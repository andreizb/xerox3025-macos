#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify retained synthetic Apple action outputs; never execute a workflow.

Only the native PDF renderer is compiled and run, in a scoped temporary folder.
The four synthetic source/result pages are compared at 72 dpi; one comparison
pair is retained. No printer, installed workflow or user document is accessed.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "evidence/2026-09-09/unattended-print/apple-action-execution"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((OUT / name).read_text())


def main():
    os.umask(0o077)
    checks = []

    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})
        assert condition, name

    runs = ["watermark", "sequence", "date", "date-full", "date-ymd", "watermark-direct"]
    check("six_native_engine_executions_succeeded",
          all(read(n + ".execution.json").get("exit_code") == 0 for n in runs))
    allowed = {"Copy Finder Items", "Move Finder Items", "Rename Finder Items", "Watermark PDF Documents"}
    check("only_allowlisted_native_actions_no_open_or_print_action",
          all(a["action"] in allowed for n in runs for a in read(n + ".actions.json")))

    wm = read("watermark-result.json")
    original = HERE / "fixtures/labels-4.pdf"
    marked = ROOT / wm["output"]
    before, after = PdfReader(original), PdfReader(marked)
    check("watermark_original_and_input_copy_unchanged",
          sha(original) == wm["input_sha256"] == sha(OUT / "watermark-input-copies/labels-4.pdf"))
    check("watermark_output_hash_retained", sha(marked) == wm["output_sha256"])
    boxes = [{"before": [float(v) for v in a.mediabox], "after": [float(v) for v in b.mediabox]}
             for a, b in zip(before.pages, after.pages)]
    check("four_pages_and_media_geometry_preserved", len(before.pages) == len(after.pages) == 4 and
          all(abs(x-y) < 0.001 for p in boxes for x, y in zip(p["before"], p["after"])))
    text_equal = [" ".join(a.extract_text().split()) == " ".join(b.extract_text().split())
                  for a, b in zip(before.pages, after.pages)]
    check("whitespace_normalized_selectable_text_preserved", all(text_equal))
    check("one_watermark_image_on_every_output_page", all(len(p.images) == 1 for p in after.pages))

    measurements = []
    with tempfile.TemporaryDirectory(prefix="apple-action-verify-", dir=HERE) as tmpname:
        tmp = Path(tmpname)
        command = ["swiftc", "-target", "arm64-apple-macos14.0", "-O",
                   str(HERE / "RenderApplePDF.swift"), "-o", str(tmp / "render-pdf")]
        subprocess.run(command, check=True, timeout=60)
        for label, source in [("original", original), ("watermarked", marked)]:
            subprocess.run([str(tmp / "render-pdf"), str(source), str(tmp / label)], check=True, timeout=30)
        for page in range(1, 5):
            ap, bp = tmp / f"original-{page}.png", tmp / f"watermarked-{page}.png"
            a = np.asarray(Image.open(ap).convert("RGB"), dtype=np.int16)
            b = np.asarray(Image.open(bp).convert("RGB"), dtype=np.int16)
            red_a = ((a[:, :, 0]-a[:, :, 1]) > 40) & ((a[:, :, 0]-a[:, :, 2]) > 40)
            red_b = ((b[:, :, 0]-b[:, :, 1]) > 40) & ((b[:, :, 0]-b[:, :, 2]) > 40)
            y, x = np.where(red_b)
            bounds = [int(x.min()), int(y.min()), int(x.max()), int(y.max())]
            delta = np.max(abs(a-b), axis=2)
            outside = np.ones(delta.shape, dtype=bool)
            outside[bounds[1]:bounds[3]+1, bounds[0]:bounds[2]+1] = False
            measurements.append({"page": page, "render_size_px": [b.shape[1], b.shape[0]],
                                 "source_red_pixels": int(red_a.sum()), "output_red_pixels": int(red_b.sum()),
                                 "red_bounds_inclusive_px": bounds, "changed_pixels": int((delta > 0).sum()),
                                 "changed_pixels_outside_stamp_rectangle": int(((delta > 0) & outside).sum()),
                                 "max_channel_difference_outside_stamp_rectangle": int(delta[outside].max()),
                                 "source_png_sha256": sha(ap), "output_png_sha256": sha(bp)})
            if page == 1:
                shutil.copyfile(ap, OUT / "original-page-1.png")
                shutil.copyfile(bp, OUT / "watermarked-page-1.png")
    check("new_visible_red_stamp_same_measured_region_on_all_four_pages",
          all(m["source_red_pixels"] == 0 and m["output_red_pixels"] == 4805 and
              m["red_bounds_inclusive_px"] == [84, 606, 195, 657] for m in measurements))

    seq = read("sequence-result.json")
    date = read("date-result.json")
    source_hashes = seq["input_hashes"]
    check("numbered_names_have_requested_start_and_three_digits",
          seq["names"] == ["007.Scan.pdf", "008.Scan.pdf", "009.Scan.pdf"])
    check("numbered_files_preserved_source_bytes",
          list(seq["file_hashes"].values()) == list(source_hashes.values()))
    year = datetime.datetime.fromisoformat(date["date_before"]).year
    check("year_suffix_names_and_bytes_preserved",
          date["names"] == [f"00{i}.Scan:{year}.pdf" for i in (7, 8, 9)] and
          list(date["file_hashes"].values()) == list(source_hashes.values()) and
          all(sha(OUT / "rename-source-copies" / n) == h for n, h in date["file_hashes"].items()))
    for mode in ["date-full", "date-ymd"]:
        result = read(mode + "-result.json")
        instant = datetime.datetime.fromisoformat(result["before"])
        prefix = (f"{instant.month}{instant.day}{instant.year}" if mode == "date-full" else
                  f"{instant.year}-{instant.month}-{instant.day}")
        check(mode + "_name_and_bytes_preserved",
              result["names"] == [prefix + "-Scan.pdf"] and
              all(h == source_hashes["geometry-a4.pdf"] == sha(OUT / (mode + "-copies") / n)
                  for n, h in result["hashes"].items()))
    check("all_rename_originals_unchanged",
          all(sha(HERE / "fixtures" / name) == h for name, h in source_hashes.items()))
    cleanup = read("watermark-temporary-cleanup.json")
    check("exact_native_temporary_output_removed_after_verified_retention",
          cleanup["exact_returned_file_removed_after_hash_verified_copy"] and
          not Path(cleanup["exact_posix_path"]).exists() and
          sha(ROOT / cleanup["retained_copy"]) == cleanup["sha256"] and
          not cleanup["shared_system_temp_directory_removed"])

    acceptance = {
        "classification": "generic native engine validation on synthetic files; no installed everyday workflow or Finder UI acceptance",
        "native_workflow_executions": len(runs), "rendered_watermark_pages": 4,
        "assertions_passed": len(checks), "checks": checks, "render_engine": "Apple CoreGraphics, 72 dpi, arm64",
        "media_boxes": boxes, "whitespace_normalized_text_equal": text_equal,
        "exact_extracted_text_equal": wm["text_unchanged"], "page_measurements": measurements,
        "limitations": [
            "Exact extracted whitespace changed; normalized selectable text matches on this fixture only.",
            "The derivative has measurable changed pixels outside the stamp rectangle; no pixel-identity guarantee.",
            "Year Month Day mode yields unpadded 2026-9-9, not a verified zero-padded ISO template.",
            "Current date for compact-date test has equal month and day; this case cannot distinguish their order.",
            "No OCR layer, annotation, signature, complex transparency, scanned-page underlay, Finder UI or physical-paper acceptance.",
            "No configured Quick Action installed; scanner naming controls are unchanged."
        ],
        "physical_prints": 0, "scanner_operations": 0, "workflow_installed": False,
        "user_documents_touched": 0, "external_temp_cleanup": "watermark-temporary-cleanup.json"
    }
    (OUT / "acceptance.json").write_text(json.dumps(acceptance, indent=2) + "\n")
    run = read("engine-run.json")
    run.update(pixel_verification_pending=False, verification="acceptance.json", assertions_passed=len(checks),
               native_workflow_executions=len(runs), rendered_watermark_pages=4)
    (OUT / "engine-run.json").write_text(json.dumps(run, indent=2) + "\n")
    print(json.dumps({"workflow_executions": len(runs), "watermark_pages": 4,
                      "assertions_passed": len(checks), "evidence": str(OUT / "acceptance.json")}))


if __name__ == "__main__":
    main()
