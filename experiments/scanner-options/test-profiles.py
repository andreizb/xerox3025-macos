#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile actual baseline/candidate XML writers and audit profile contracts.

No server, socket, SANE library, scanner initialization, or motor is involved.
This validates capabilities, not an actual Apple UI or hardware acceptance.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BUILD = HERE / "build"
EVIDENCE = HERE / "evidence"
BUILD.mkdir(exist_ok=True)
SC = "{http://schemas.hp.com/imaging/escl/2011/05/03}"
PWG = "{http://www.pwg.org/schemas/2010/12/sm}"
reports = []

def run(args):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(json.dumps({"argv": [str(x) for x in args], "returncode": result.returncode,
                                       "stdout": result.stdout, "stderr": result.stderr}, indent=2))
    return result.stdout

def check(name, passed):
    reports.append({"name": name, "passed": bool(passed)})
    if not passed:
        raise AssertionError(name)

def compile_probe(name, source):
    output = BUILD / ("profile-" + name)
    command = ["clang++", "-arch", "arm64", "-std=c++14", "-O1", "-g",
               "-fsanitize=address,undefined", "-ffunction-sections", "-fdata-sections", "-Wl,-dead_strip",
               "-I" + str(ROOT / "upstream/AirSane"), "-I" + str(ROOT / "upstream/AirSane/server"),
               "-I" + str(ROOT / "upstream/sane-backends/include"),
               '-DPROFILE_SOURCE="' + str(source) + '"', HERE / "profile-probe.cpp", "-o", output]
    build_output = run(command)
    linked = run(["otool", "-L", output])
    imports = run(["nm", "-u", output])
    architectures = run(["lipo", "-archs", output]).strip()
    check(name + " is ARM-only", architectures == "arm64")
    check(name + " has no SANE or network imports",
          not any(word in (linked + imports).lower() for word in ("libsane", "_sane_", "_socket", "_connect")))
    (EVIDENCE / ("profile-" + name + "-build.json")).write_text(json.dumps({
        "argv": [str(x) for x in command], "output": build_output,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "architecture": architectures, "linked_libraries": linked, "undefined_symbols": imports,
    }, indent=2) + "\n")
    return output

def profiles(xml):
    return xml.findall(".//" + SC + "SettingProfile")

def modes(profile):
    return {x.text for x in profile.findall("./" + SC + "ColorModes/" + SC + "ColorMode")}

def formats(profile):
    return {x.text for x in profile.findall("./" + SC + "DocumentFormats/" + PWG + "DocumentFormat")}

def contract(xml):
    return {(mode, fmt, int(res.find(SC + "XResolution").text), int(res.find(SC + "YResolution").text))
            for profile in profiles(xml)
            for mode in modes(profile) for fmt in formats(profile)
            for res in profile.findall(".//" + SC + "DiscreteResolution")}

run([sys.executable, HERE / "prepare-candidate.py"])
baseline = compile_probe("baseline", ROOT / "upstream/AirSane/server/scanner.cpp")
candidate = compile_probe("candidate", HERE / "candidate/server/scanner.cpp")
for kind in ("xerox", "without-lineart", "gray-only", "other-model", "other-backend", "with-adf"):
    roots = {}
    data = {}
    for name, binary in (("baseline", baseline), ("candidate", candidate)):
        target = (EVIDENCE if kind == "xerox" else BUILD) / (kind + "-" + name + "-capabilities.xml")
        run([binary, kind, target])
        data[name] = target.read_bytes()
        roots[name] = ET.fromstring(data[name])
    check(kind + " preserves every mode/format/resolution combination", contract(roots["baseline"]) == contract(roots["candidate"]))
    for name, xml in roots.items():
        check(kind + " " + name + " never advertises 1-bit JPEG",
              all(not ("BlackAndWhite1" in modes(p) and "image/jpeg" in formats(p)) for p in profiles(xml)))
        check(kind + " " + name + " keeps only qualified resolutions",
              {int(x.text) for x in xml.findall(".//" + SC + "XResolution")} == {75, 100, 150, 200, 300, 600})
        check(kind + " " + name + " does not invent threshold or halftone controls",
              all(xml.find(".//" + SC + tag) is None for tag in ("ThresholdSupport", "BinaryRenderings", "BinaryRendering")))
    if kind in ("xerox", "gray-only"):
        check(kind + " candidate exposes accepted one-bit mode in first profile", "BlackAndWhite1" in modes(profiles(roots["candidate"])[0]))
        check(kind + " first profile retains all previous continuous-tone modes",
              modes(profiles(roots["baseline"])[0]) <= modes(profiles(roots["candidate"])[0]))
        check(kind + " first profile formats are common lossless transports",
              formats(profiles(roots["candidate"])[0]) == {"application/pdf", "image/png"})
    else:
        check(kind + " unaffected bytes are preserved", data["baseline"] == data["candidate"])
    if kind == "xerox":
        saved = ROOT / "evidence/2026-09-09/scanner-capabilities.xml"
        check("baseline fixture exactly matches saved installed capabilities", data["baseline"] == saved.read_bytes())

summary = {"passed": all(x["passed"] for x in reports), "checks": len(reports), "results": reports,
           "sanitizers": ["AddressSanitizer", "UndefinedBehaviorSanitizer"],
           "compiled": "complete actual scanner.cpp with unreachable acquisition code removed at link time",
           "hardware_contact": False, "native_app_acceptance": False, "installed": False}
(EVIDENCE / "profile-tests.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
