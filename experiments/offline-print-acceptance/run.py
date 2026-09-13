#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise only file-to-file Apple CUPS filtering. Never submits print jobs.

No destination (-d), existing job (-j), backend, lp, lpr, queue mutation, or
network operation is used. Options refer to the filter stage; ignored options
are observations of this stage, not claims about native print-dialog behavior.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "evidence/2026-09-09/unattended-print"
PPD = OUT / "queue-readonly.ppd"
TMP = HERE / "tmp"
BASE = {"media": "iso_a4_210x297mm", "number-up": "1",
        "orientation-requested": "3", "print-scaling": "none",
        "scaling": "100", "Resolution": "600dpi", "ColorModel": "Gray",
        "sides": "one-sided"}
CASES = [
    ("baseline-4", "labels-4.pdf", {}, 1),
    ("range-2-3", "labels-4.pdf", {"page-ranges": "2-3"}, 1),
    ("range-1-and-4", "labels-4.pdf", {"page-ranges": "1,4"}, 1),
    ("odd-pages", "labels-4.pdf", {"page-set": "odd"}, 1),
    ("even-pages", "labels-4.pdf", {"page-set": "even"}, 1),
    ("reverse-order", "labels-4.pdf", {"outputorder": "reverse"}, 1),
    ("even-reverse", "labels-4.pdf", {"page-set": "even", "outputorder": "reverse"}, 1),
    ("collated-2-copies", "labels-4.pdf", {"collate": "true"}, 2),
    ("uncollated-2-copies", "labels-4.pdf", {"collate": "false"}, 2),
    *[(f"nup-{n}", "labels-16.pdf", {"number-up": str(n)}, 1) for n in (2,4,6,9,16)],
    ("nup-4-rltb", "labels-4.pdf", {"number-up": "4", "number-up-layout": "rltb"}, 1),
    ("nup-4-tblr", "labels-4.pdf", {"number-up": "4", "number-up-layout": "tblr"}, 1),
    ("nup-4-border", "labels-4.pdf", {"number-up": "4", "page-border": "single-thick"}, 1),
    ("a4-portrait", "geometry-a4.pdf", {}, 1),
    ("a4-landscape", "geometry-a4.pdf", {"orientation-requested": "4"}, 1),
    ("a4-landscape-fit", "geometry-a4.pdf", {"orientation-requested": "4", "print-scaling": "fit", "fit-to-page": "true"}, 1),
    ("a4-reverse-landscape", "geometry-a4.pdf", {"orientation-requested": "5"}, 1),
    ("a4-reverse-portrait", "geometry-a4.pdf", {"orientation-requested": "6"}, 1),
    ("a4-scale-50", "geometry-a4.pdf", {"scaling": "50"}, 1),
    ("wide-none", "geometry-wide.pdf", {}, 1),
    ("wide-fit", "geometry-wide.pdf", {"print-scaling": "fit", "fit-to-page": "true"}, 1),
    ("wide-fill", "geometry-wide.pdf", {"print-scaling": "fill"}, 1),
    ("a5-media-fit", "geometry-a4.pdf", {"media": "iso_a5_148x210mm", "print-scaling": "fit", "fit-to-page": "true"}, 1),
    ("custom-100x150mm", "geometry-custom.pdf", {"media": "Custom.100x150mm"}, 1),
]


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024*1024), b""): value.update(block)
    return value.hexdigest()


def run(case):
    name, fixture, changes, copies = case
    folder = OUT / "cases" / name
    folder.mkdir(parents=True, exist_ok=True)
    source = HERE / "fixtures" / fixture
    options = BASE | changes
    argv = ["/usr/sbin/cupsfilter", "-p", str(PPD), "-i", "application/pdf",
            "-m", "image/urf", "-n", str(copies)]
    for key, value in options.items(): argv += ["-o", f"{key}={value}"]
    argv.append(str(source))
    filters = subprocess.run([argv[0], "--list-filters", *argv[1:]], text=True,
                             capture_output=True, timeout=20)
    # cgpdftoraster is the only allowed stage. This guard prevents accidental
    # expansion into a vendor executable or backend on a different system.
    if filters.returncode or filters.stdout.strip() != "cgpdftoraster":
        raise RuntimeError(f"Unexpected filter graph: {filters.stdout} {filters.stderr}")
    urf = TMP / f"{name}.urf"
    started = time.monotonic()
    with urf.open("wb") as stream, (folder / "cupsfilter.log").open("wb") as log:
        result = subprocess.run(argv, stdout=stream, stderr=log, timeout=120)
    entry = {"case": name, "scope": "OFFLINE Apple host filter only",
             "device_operations": 0, "print_jobs_submitted": 0,
             "source": str(source.relative_to(ROOT)), "source_sha256": digest(source),
             "ppd_sha256": digest(PPD), "argv": argv,
             "filters": filters.stdout.strip().splitlines(),
             "exit_code": result.returncode, "elapsed_seconds": round(time.monotonic()-started,3),
             "urf_bytes": urf.stat().st_size, "urf_sha256": digest(urf)}
    if result.returncode == 0:
        decoded = subprocess.run([str(TMP / "decode-raster"), str(urf), str(folder),
                                  str(folder / "raster.json")], text=True, capture_output=True, timeout=90)
        entry["decoder_exit_code"] = decoded.returncode
        if decoded.returncode:
            entry["decoder_error"] = decoded.stderr
        else:
            raster = json.loads((folder / "raster.json").read_text())
            images = sorted(folder.glob("page-*.png"))
            ocr_options = ["--grid=4"] if name == "nup-16" else []
            ocr = subprocess.run([str(TMP / "read-labels"), *ocr_options, *map(str,images)],
                                 text=True, capture_output=True, timeout=90)
            entry["ocr_exit_code"] = ocr.returncode
            if ocr.returncode == 0:
                observations = json.loads(ocr.stdout)
                (folder / "ocr.json").write_text(json.dumps(observations,indent=2)+"\n")
                for page, observed in zip(raster["pages"], observations):
                    labels=[]
                    for item in observed["observations"]:
                        match=re.fullmatch(r"PAGE\s+(\d{1,2})",item["text"].strip())
                        if match: labels.append({"id":int(match[1]),"confidence":item["confidence"],
                                                 "box":item["box_normalized_bottom_left"]})
                    page["labels"] = labels
                entry["raster"] = raster
            else: entry["ocr_error"] = ocr.stderr
    (folder / "result.json").write_text(json.dumps(entry,indent=2)+"\n")
    # Retain hashes/geometry and small review images; regenerate large streams.
    urf.unlink()
    print(json.dumps({"case": name,"filter":entry["exit_code"],
                      "pages":entry.get("raster",{}).get("page_count"),
                      "labels":[[x["id"] for x in page.get("labels",[])]
                                for page in entry.get("raster",{}).get("pages",[])]}), flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--ppd", type=Path, required=True, help="Private PPD snapshot; never commit it")
    parser.add_argument("--case", action="append", help="Run only the named case; repeatable")
    args=parser.parse_args()
    PPD=args.ppd.resolve()
    if not PPD.is_file(): parser.error("PPD snapshot does not exist")
    TMP.mkdir(parents=True,exist_ok=True)
    if args.case:
        unknown=set(args.case)-{case[0] for case in CASES}
        if unknown: parser.error(f"unknown cases: {sorted(unknown)}")
    for case in CASES:
        if not args.case or case[0] in args.case: run(case)
