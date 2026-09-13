#!/usr/bin/env python3
"""Offline repository checks; no printer, queue or service operations.

SPDX-License-Identifier: MIT
"""
import ast
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def main():
    excluded = {".git", ".venv", "build", "build-tools", "upstream", "pristine", "prefix", "downloads", "dist", "evidence", "tmp", "candidate", "vendor"}
    python_count = shell_count = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or set(path.relative_to(ROOT).parts) & excluded:
            continue
        if path.suffix == ".py":
            ast.parse(path.read_text(), filename=str(path))
            python_count += 1
        elif path.suffix == ".sh" or path.read_bytes().startswith((b"#!/bin/bash", b"#!/bin/sh")):
            run("/bin/bash", "-n", path)
            shell_count += 1
    print(f"Parsed {python_count} Python files and checked {shell_count} shell scripts", flush=True)
    proxy = ROOT / "experiments/ipp-supply-proxy"
    expected = json.loads((proxy / "vendor.sha256.json").read_text())
    actual = {str(p.relative_to(proxy / "vendor")): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((proxy / "vendor").rglob("*")) if p.is_file()}
    if actual != expected:
        raise RuntimeError("Vendored Go dependency differs from its recorded source manifest")
    print(f"Verified {len(actual)} vendored source files", flush=True)
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py")
    run(sys.executable, proxy / "test_maintenance.py")
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        build = ROOT / "build/offline-checks"
        build.mkdir(parents=True, exist_ok=True)
        run("/usr/bin/clang", "-arch", "arm64", "-O1", "-g", "-fsanitize=address,undefined",
            "tests/tcp_io_test.c", "-o", build / "tcp-test")
        run(build / "tcp-test")
    else:
        print("SKIP native TCP test: requires an Apple Silicon Mac")
    print("Offline repository checks passed. Physical/UI acceptance was not run.")


if __name__ == "__main__":
    main()
