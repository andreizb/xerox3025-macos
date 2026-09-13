#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import sys
from workflows import generate_all

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--deskew-binary", type=Path)
args = parser.parse_args()
output = args.output.absolute()
if output.exists(): raise SystemExit("Output already exists; choose a fresh package directory.")
output.mkdir(parents=True, mode=0o700)
payload = output / "payload"
(payload / "bin").mkdir(parents=True)
shutil.copy2(root / "build/xerox-document", payload / "bin/xerox-document")
if args.deskew_binary:
    shutil.copy2(args.deskew_binary, payload / "bin/xerox-pdf-deskew")
for name in ("run-workflow", "LICENSE", "README.md", "maintenance.py"):
    shutil.copy2(root / name, payload / name)
shutil.copy2(root / "maintenance.py", output / "maintenance.py")
shutil.copy2(root / "README.md", output / "README.md")
generate_all(root / "build/workflow-builder", output / "workflows", deskew=bool(args.deskew_binary))
architecture = []
for binary in (payload / "bin").iterdir():
    slices = subprocess.check_output(["/usr/bin/lipo", "-archs", str(binary)], text=True).strip()
    if slices != "arm64": raise RuntimeError(f"Non-ARM64 dependency: {binary}: {slices}")
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(binary)], check=True)
    dependencies = subprocess.check_output(["/usr/bin/otool", "-L", str(binary)], text=True)
    architecture.append({"name": binary.name, "architectures": slices, "imports": dependencies,
                         "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()})
files = {}
for dirname in ("payload", "workflows"):
    for path in sorted((output / dirname).rglob("*")):
        if path.is_file():
            files[str(path.relative_to(output))] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
(output / "manifest.json").write_text(json.dumps({"schema_version": 1, "component": "Xerox3025Documents", "files": files}, indent=2, sort_keys=True) + "\n")
(output / "architecture.json").write_text(json.dumps(architecture, indent=2, sort_keys=True) + "\n")
with tarfile.open(output / "source.tar.gz", "w:gz") as archive:
    for name in ("Sources", "Tests", "build.py", "package.py", "workflows.py", "maintenance.py", "run-workflow", "README.md", "LICENSE"):
        archive.add(root / name, arcname="native-documents/" + name, filter=lambda info: None if "__pycache__" in info.name else info)
    if args.deskew_binary:
        deskew_source = args.deskew_binary.resolve().parent.parent
        for name in ("deskew.swift", "build.sh", "README.md", "test.py"):
            archive.add(deskew_source / name, arcname="scan-alignment/" + name)
subprocess.run([sys.executable, str(output / "maintenance.py"), "verify", "--package", str(output)], check=True)
print(output)
