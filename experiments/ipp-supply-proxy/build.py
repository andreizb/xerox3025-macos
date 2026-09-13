#!/usr/bin/env python3
"""Build this optional experiment in its own prefix/cache; never install it."""
# SPDX-License-Identifier: MIT
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
LOCK = json.loads((ROOT / "sources.json").read_text())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offline', action='store_true')
args = parser.parse_args()
BUILD.mkdir(exist_ok=True)
# Keep the downloaded toolchain/cache outside this module's package traversal.
(BUILD / "go.mod").write_text("module xerox3025.local/isolated-build\n\ngo 1.27.1\n")
archive = BUILD / LOCK["go"]["url"].rsplit("/", 1)[1]
if not archive.exists():
    if args.offline:
        raise RuntimeError('Offline build requires the pinned Go toolchain archive in build/')
    with urllib.request.urlopen(LOCK["go"]["url"], timeout=60) as incoming, archive.open("wb") as output:
        shutil.copyfileobj(incoming, output)
if hashlib.sha256(archive.read_bytes()).hexdigest() != LOCK["go"]["sha256"]:
    raise RuntimeError("Go archive checksum does not match the pinned official release")
if not (BUILD / "go/bin/go").exists():
    with tarfile.open(archive) as source:
        source.extractall(BUILD, filter="data")
environment = {**os.environ, "GOCACHE": str(BUILD / "gocache"),
               "GOMODCACHE": str(BUILD / "gomodcache"), "GOPATH": str(BUILD / "gopath"),
               "GOTOOLCHAIN": "local", "GOOS": "darwin", "GOARCH": "arm64",
               "CGO_ENABLED": "1", "CC": "/usr/bin/clang"}
go = BUILD / "go/bin/go"
def run(*arguments):
    subprocess.run([str(x) for x in arguments], cwd=ROOT, env=environment, check=True)
if args.offline:
    environment['GOPROXY'] = 'off'
    environment['GOSUMDB'] = 'off'
    vendor = {str(p.relative_to(ROOT / 'vendor')): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((ROOT / 'vendor').rglob('*')) if p.is_file()}
    if vendor != json.loads((ROOT / 'vendor.sha256.json').read_text()):
        raise RuntimeError('Vendored source differs from the saved dependency manifest')
else:
    run(go, "mod", "download", "all")
    run(go, "mod", "vendor")
    vendor = {str(p.relative_to(ROOT / 'vendor')): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((ROOT / 'vendor').rglob('*')) if p.is_file()}
    (ROOT / 'vendor.sha256.json').write_text(json.dumps(vendor, indent=2, sort_keys=True) + '\n')
run(go, "test", "-mod=vendor", "-race", "-count=1", "-v", ".")
run(go, "build", "-mod=vendor", "-buildvcs=false", "-trimpath", "-ldflags=-buildid=", "-o", BUILD / "ipp-supply-proxy", ".")
run('/usr/bin/clang', '-O2', '-arch', 'arm64', '-mmacosx-version-min=14.0',
    ROOT.parents[1] / 'src/discover.c', '-o', BUILD / 'discover')
run('/usr/bin/codesign', '--force', '--sign', '-', BUILD / 'discover')
run('/usr/bin/codesign', '--verify', '--strict', BUILD / 'discover')
run("/usr/bin/codesign", "--force", "--sign", "-", BUILD / "ipp-supply-proxy")
run("/usr/bin/codesign", "--verify", "--strict", BUILD / "ipp-supply-proxy")
architecture = subprocess.check_output(["/usr/bin/lipo", "-archs", BUILD / "ipp-supply-proxy"], text=True).strip()
if architecture != "arm64":
    raise RuntimeError("Proxy is not ARM-native")
dependencies = subprocess.check_output(["/usr/bin/otool", "-L", BUILD / "ipp-supply-proxy"], text=True)
for line in dependencies.splitlines()[1:]:
    if not line.strip().startswith(("/usr/lib/", "/System/Library/")):
        raise RuntimeError("Unexpected non-system runtime dependency: " + line)
licenses = ROOT / "licenses"
licenses.mkdir(exist_ok=True)
shutil.copy2(BUILD / "go/LICENSE", licenses / "Go-BSD-3-Clause.txt")
shutil.copy2(ROOT / "vendor/github.com/OpenPrinting/goipp/LICENSE", licenses / "goipp-BSD-2-Clause.txt")
shutil.copy2(ROOT.parents[1] / "LICENSE", licenses / "Local-MIT.txt")
(BUILD / "architecture.json").write_text(json.dumps({"architectures": architecture,
    "runtime_dependencies": dependencies.splitlines()[1:], "signature": "ad-hoc verified",
    "go": LOCK["go"]["version"], "goipp": LOCK["goipp"]["version"]}, indent=2) + "\n")
print(BUILD / "ipp-supply-proxy")
