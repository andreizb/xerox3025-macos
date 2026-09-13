#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later WITH SANE-exception
"""Run actual backend option/inquiry/window code with a disconnected recorder."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--inquiry", type=Path, required=True, help="Private JSON from scripts/probe-inquiry.py; never commit it")
args = parser.parse_args()
HERE = Path(__file__).resolve().parent
(HERE / "evidence").mkdir(exist_ok=True)
ROOT = HERE.parent.parent
BUILD = HERE / "build"
BUILD.mkdir(exist_ok=True)
SOURCE = ROOT / "upstream/sane-backends/backend/xerox_mfp.c"
source = SOURCE.read_text()
# These stable boundaries include whole original functions. A source change
# must be inspected before changing the extraction; never rewrite logic here.
start = source.index("static int inq_dpi_bits[] = {")
end = source.index("static SANE_Status\ndev_inquiry_adf_status", start)
fragment = source[start:end]
if not all(x in fragment for x in ("static void init_options", "static int fix_window",
                                  "static int dev_set_window", "dev_inquiry(struct device *dev)")):
    raise SystemExit("Unexpected upstream boundaries")
notice = source[:source.index("#define DEBUG_NOT_STATIC")]
(BUILD / "backend-routines.inc").write_text(notice + "\n" + fragment)
types_source = (ROOT / "upstream/sane-backends/include/sane/sanei_backend.h").read_text()
types = re.search(r"typedef union\s*\{.*?\}\s*Option_Value;", types_source, re.S)
if not types:
    raise SystemExit("Actual Option_Value definition missing")
(BUILD / "backend-types.inc").write_text("/* SANE Option_Value, GPL-2.0+ with SANE exception. */\n" + types[0] + "\n")
saved = json.loads(args.inquiry.read_text())
inquiry = bytes.fromhex(saved["response_hex"])
if len(inquiry) != 70:
    raise SystemExit("Saved inquiry is not a complete known frame")
(BUILD / "inquiry.bin").write_bytes(inquiry)
binary = BUILD / "backend-options"
command = ["clang", "-arch", "arm64", "-std=c11", "-D_DARWIN_C_SOURCE", "-O1", "-g",
           "-fsanitize=address,undefined", "-I" + str(BUILD),
           "-I" + str(ROOT / "upstream/sane-backends/include"),
           "-I" + str(ROOT / "upstream/sane-backends/backend"),
           str(HERE / "backend-probe.c"), "-o", str(binary)]
compile_result = subprocess.run(command, capture_output=True, text=True, timeout=60)
if compile_result.returncode:
    raise RuntimeError(compile_result.stdout + compile_result.stderr)
result = subprocess.run([str(binary), str(BUILD / "inquiry.bin")], capture_output=True, text=True, timeout=15)
if result.returncode:
    raise RuntimeError(result.stdout + result.stderr)
report = json.loads(result.stdout)
report.update({
    "argv": command,
    "compiler_output": compile_result.stdout + compile_result.stderr,
    "stderr": result.stderr,
    "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "extracted_routines_sha256": hashlib.sha256(fragment.encode()).hexdigest(),
    "extracted_source_start_line": source[:start].count("\n") + 1,
    "extracted_source_end_line": source[:end].count("\n"),
    "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    "architecture": subprocess.check_output(["lipo", "-archs", str(binary)], text=True).strip(),
    "sanitizers": ["AddressSanitizer", "UndefinedBehaviorSanitizer"],
    "scope": "Option descriptors, inquiry parsing and command construction; no USB/TCP, full SANE API, acquisition or image processing test",
    "basis": "Explicit user-supplied inquiry fixture; firmware compatibility is not inferred",
})
if report["architecture"] != "arm64":
    raise RuntimeError("Native-only build required")
(HERE / "evidence/backend-tests.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
