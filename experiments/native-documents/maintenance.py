#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install/uninstall only the reviewed optional per-user document workflows.

--home exists for isolated lifecycle tests and alternate explicitly selected user
homes. No printer queue, launchd job, document, network or macOS preference changes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

NAME = "Xerox3025Documents"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def below(base: Path, relative: str) -> Path:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or ".." in parts:
        raise RuntimeError("Unsafe manifest path")
    path = base.joinpath(*parts)
    for parent in (path, *path.parents):
        if parent == base.parent:
            break
        if parent.is_symlink():
            raise RuntimeError(f"Refusing symlink: {parent}")
    return path

def root_for(home: Path) -> Path:
    return below(home, "Library/Application Support/" + NAME)

def destination(home: Path, rel: str) -> Path:
    if rel.startswith("payload/"):
        return below(root_for(home), rel[len("payload/"):])
    if rel.startswith("workflows/"):
        parts = Path(rel).parts
        if (len(parts) != 5 or parts[1] not in ("Services", "PDF Services")
                or not parts[2].startswith("Xerox - ") or not parts[2].endswith(".workflow")
                or parts[3] != "Contents" or parts[4] not in ("Info.plist", "document.wflow")):
            raise RuntimeError("Workflow target is outside the owned Services/PDF Services bundles")
        return below(home / "Library", str(Path(*parts[1:])))
    raise RuntimeError("Unexpected package file category")

def load_manifest(package: Path) -> dict:
    manifest = json.loads((package / "manifest.json").read_text())
    if manifest.get("schema_version") != 1 or manifest.get("component") != NAME:
        raise RuntimeError("Unexpected package manifest")
    for relative, info in manifest["files"].items():
        path = below(package, relative)
        if not path.is_file() or sha(path) != info["sha256"]:
            raise RuntimeError(f"Package content changed: {relative}")
    actual = {str(path.relative_to(package)) for dirname in ("payload", "workflows")
              for path in (package / dirname).rglob("*") if path.is_file()}
    if actual != set(manifest["files"]):
        raise RuntimeError("Package contains unlisted payload/workflow files")
    return manifest

def install(package: Path, home: Path) -> dict:
    manifest = load_manifest(package)
    root = root_for(home)
    if root.exists() or root.is_symlink():
        raise RuntimeError(f"An installation already exists; uninstall it first: {root}")
    paths = [(below(package, relative), destination(home, relative)) for relative in manifest["files"]]
    for relative in manifest["files"]:
        if relative.startswith("workflows/"):
            parts = Path(relative).parts
            bundle = below(home / "Library", str(Path(*parts[1:3])))
            if bundle.exists() or bundle.is_symlink():
                raise RuntimeError(f"Refusing to merge into an existing workflow: {bundle}")
    for _, path in paths:
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"Refusing to replace an existing file/workflow: {path}")
    created_files, created_dirs = [], []
    try:
        for source, target in paths:
            missing = []
            parent = target.parent
            while not parent.exists():
                missing.append(parent); parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir(mode=0o700); created_dirs.append(directory)
            with source.open("rb") as source_handle, target.open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
            created_files.append(target)
            target.chmod(0o700 if os.access(source, os.X_OK) else 0o600)
        receipt = {"schema_version": 1, "component": NAME, "files": {
            str(target.relative_to(home)): sha(target) for _, target in paths}}
        receipt_path = root / "receipt.json"
        with receipt_path.open("x") as handle:
            created_files.append(receipt_path)
            json.dump(receipt, handle, indent=2, sort_keys=True)
        receipt_path.chmod(0o600)
        return {"installed": True, "home": str(home), "file_count": len(paths),
                "ui_accepted": False, "documents_changed": False, "printer_queues_changed": False}
    except BaseException:
        for path in reversed(created_files):
            path.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            try: directory.rmdir()
            except OSError: pass
        raise

def uninstall(home: Path) -> dict:
    root = root_for(home)
    receipt_path = below(root, "receipt.json")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("schema_version") != 1 or receipt.get("component") != NAME:
        raise RuntimeError("Missing or invalid ownership receipt")
    paths = []
    allowed_prefixes = ("Library/Application Support/" + NAME + "/", "Library/Services/Xerox - ", "Library/PDF Services/Xerox - ")
    for relative, digest in receipt["files"].items():
        if not relative.startswith(allowed_prefixes):
            raise RuntimeError("Receipt contains an out-of-scope path")
        path = below(home, relative)
        if not path.is_file() or sha(path) != digest:
            raise RuntimeError(f"Owned file was changed or removed; retaining installation for review: {path}")
        paths.append(path)
    owned = {str(path) for path in paths}
    expected_root_entries = set(owned) | {str(receipt_path)}
    for path in paths:
        if root in path.parents:
            expected_root_entries.update(str(parent) for parent in path.parents if parent == root or root in parent.parents)
    actual = {str(path) for path in root.rglob("*")}
    if not actual.issubset(expected_root_entries):
        raise RuntimeError("Installation contains additional files; retaining them for review")
    for path in paths:
        bundle = next((parent for parent in path.parents if parent.suffix == ".workflow"), None)
        if bundle is not None and any(str(item) not in owned for item in bundle.rglob("*") if item.is_file() or item.is_symlink()):
            raise RuntimeError("Workflow contains additional files; retaining it for review")
    directories = set()
    for path in paths:
        parent = path.parent
        while parent not in (home / "Library/Services", home / "Library/PDF Services", root.parent):
            directories.add(parent); parent = parent.parent
    for path in paths: path.unlink()
    receipt_path.unlink()
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        try: directory.rmdir()
        except OSError: pass
    return {"uninstalled": True, "home": str(home), "files_removed": len(paths),
            "user_output_documents_retained": True, "printer_queues_changed": False}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall", "verify"))
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--home", type=Path, default=Path.home())
    args = parser.parse_args()
    home = args.home.absolute()
    if args.action == "install": result = install(args.package.resolve(), home)
    elif args.action == "uninstall": result = uninstall(home)
    else: result = {"verified": True, "files": len(load_manifest(args.package.resolve())["files"])}
    print(json.dumps(result, indent=2, sort_keys=True))

if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"Xerox document maintenance: {exc}", file=sys.stderr)
        sys.exit(1)
