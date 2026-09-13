#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
build = root / "build"
build.mkdir(exist_ok=True)
common = ["/usr/bin/xcrun", "swiftc", "-O", "-target", "arm64-apple-macosx13.0", "-module-cache-path", str(build / "module-cache")]
for sources, name, frameworks, library in [
    (["DocumentOps.swift", "main.swift"], "xerox-document", ["PDFKit", "CoreGraphics"], False),
    (["WorkflowBuilder.swift"], "workflow-builder", ["Automator"], True),
]:
    command = common + (["-parse-as-library"] if library else [])
    for framework in frameworks: command += ["-framework", framework]
    command += [str(root / "Sources" / source) for source in sources]
    command += ["-o", str(build / name)]
    subprocess.run(command, check=True)
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(build / name)], check=True)
    arch = subprocess.check_output(["/usr/bin/lipo", "-archs", str(build / name)], text=True).strip()
    if arch != "arm64": raise RuntimeError(f"Non-native build: {arch}")
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(build / name)], check=True)
print("ARM64 native command and build-time Automator serializer compiled and ad-hoc signed.")
