#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real ARM64 command, Apple Automator execution, and isolated lifecycle tests."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maintenance import install, uninstall, load_manifest
import maintenance
from workflows import generate

package = Path(sys.argv[1]).resolve()
fixtures = Path(sys.argv[2]).resolve()
evidence = ROOT / "evidence"
evidence.mkdir(exist_ok=True)
checks = []

def check(value: bool, label: str) -> None:
    if not value:
        raise AssertionError(label)
    checks.append(label)

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(args: list[str], expected: int = 0, timeout: int = 35) -> subprocess.CompletedProcess:
    completed = subprocess.run([str(arg) for arg in args], text=True, capture_output=True, timeout=timeout)
    if expected == 0 and completed.returncode:
        raise AssertionError(f"Command failed {args}: {completed.stdout}\n{completed.stderr}")
    if expected != 0:
        check(completed.returncode != 0, f"refused command {' '.join(str(a) for a in args[1:3])}")
    return completed

with tempfile.TemporaryDirectory(prefix="xerox-document-lifecycle-") as temp_string:
    temp = Path(temp_string)
    home = temp / "home"; home.mkdir()
    user_docs = home / "Documents"; user_docs.mkdir()
    sentinel = user_docs / "keep-my-document.pdf"; sentinel.write_bytes(b"user document sentinel")
    result = install(package, home)
    check(result["installed"] and not result["ui_accepted"], "install into isolated home only; UI status remains unaccepted")
    root = home / "Library/Application Support/Xerox3025Documents"
    tool = root / "bin/xerox-document"
    runner = root / "run-workflow"
    check(os.stat(root).st_mode & 0o777 == 0o700, "private installation permissions")
    check(subprocess.check_output(["/usr/bin/lipo", "-archs", str(tool)], text=True).strip() == "arm64", "installed document command exactly ARM64")
    for workflow in (home / "Library/PDF Services").iterdir():
        body = plistlib.loads((workflow / "Contents/document.wflow").read_bytes())
        check(body["workflowMetaData"]["workflowTypeIdentifier"] == "com.apple.Automator.printPlugin", f"print metadata {workflow.name}")
        check(len(body["actions"]) == 2 and body["actions"][1]["action"]["ActionParameters"]["appPath"] == "/System/Applications/Preview.app", f"native Preview final action {workflow.name}")
    for workflow in (home / "Library/Services").iterdir():
        info = plistlib.loads((workflow / "Contents/Info.plist").read_bytes())
        check(info["NSServices"][0]["NSSendFileTypes"] == ["com.adobe.pdf"], f"Finder service accepts PDF only {workflow.name}")
    # Unattended execution includes Apple's real Run Shell Script action. The
    # final Open Finder Items action is deliberately omitted to leave UI asleep.
    for action, input_file in [("booklet", "five-page.pdf"), ("remove-empty", "with-empty.pdf"), ("id-card", "card-pair.pdf"), ("deskew", "with-empty.pdf")]:
        if action == "deskew" and not (root / "bin/xerox-pdf-deskew").exists(): continue
        original = fixtures / input_file; original_hash = digest(original)
        destination = temp / "workflow outputs" / action
        script = f"exec {shlex.quote(str(runner))} {shlex.quote(action)} {shlex.quote(str(destination))} \"$@\"\n"
        workflow = generate(ROOT / "build/workflow-builder", temp / "headless-workflows" / action, action, "print", open_preview=False, script_override=script)
        command = run(["/usr/bin/automator", "-i", original, workflow], timeout=50)
        (evidence / ("automator-" + action + ".log")).write_text(command.stdout + "\nSTDERR:\n" + command.stderr)
        outputs = list(destination.glob("*/processed.pdf"))
        check(len(outputs) == 1, f"Apple Automator executed {action} and produced one PDF")
        output_folder = outputs[0].parent
        check(digest(output_folder / "original.pdf") == original_hash == digest(original), f"Automator {action} retained exact original bytes")
        check(bool(json.loads((output_folder / "report.json").read_text())), f"Automator {action} produced JSON report")
        check(os.stat(outputs[0]).st_mode & 0o777 == 0o600, f"Automator {action} derivative private mode 0600")
        check(str(outputs[0]) in command.stdout, f"Automator {action} output passes derivative path to the next action")
        retained = evidence / "representative"
        retained.mkdir(exist_ok=True)
        shutil.copy2(output_folder / "report.json", retained / (action + "-workflow-report.json"))
    duplex_dir = temp / "odd duplex"; duplex_dir.mkdir()
    front = duplex_dir / "test-fronts.pdf"; back = duplex_dir / "test-backs.pdf"
    shutil.copy2(fixtures / "fronts.pdf", front); shutil.copy2(fixtures / "backs.pdf", back)
    operation_dir = temp / "direct operations"
    interleave = run([runner, "interleave-reverse", operation_dir, back, front])
    interleaved = Path(interleave.stdout.strip())
    inter_report = json.loads(interleaved.with_name("report.json").read_text())
    check(len(inter_report["outputPages"]) == 5 and inter_report["sourcePageMapping"][1] == ["backs:2"], "workflow ignores Finder selection order and honors reverse backs")
    run([runner, "interleave-same", operation_dir, front, front], expected=1)
    unrelated = duplex_dir / "other-backs.pdf"; shutil.copy2(back, unrelated)
    run([runner, "interleave-same", operation_dir, front, unrelated], expected=1)
    run([runner, "booklet", operation_dir, front, back], expected=1)
    before = set(operation_dir.iterdir())
    run([runner, "booklet", operation_dir, fixtures / "malformed.pdf"], expected=1)
    check(set(operation_dir.iterdir()) == before, "failed workflow removes only its own incomplete folder")
    output = temp / "already-exists.pdf"; output.write_bytes(b"existing sentinel")
    run([tool, "booklet", "--input", front, "--output", output], expected=1)
    check(output.read_bytes() == b"existing sentinel", "CLI does not overwrite existing output")
    run([tool, "booklet", "--input", fixtures / "encrypted.pdf", "--output", temp / "must-not-exist.pdf"], expected=1)
    check(not (temp / "must-not-exist.pdf").exists(), "encrypted failure creates no derivative")
    run([tool, "booklet", "--input", front, "--output", temp / "new.pdf", "--report", output], expected=1)
    check(not (temp / "new.pdf").exists(), "report overwrite preflight prevents PDF partial result")
    run([tool, "booklet", "--input", front, "--input", back, "--output", temp / "duplicate.pdf"], expected=1)
    try: install(package, home)
    except RuntimeError as exc: check("already exists" in str(exc), "repeat install refuses existing installation")
    else: raise AssertionError("repeat install accepted")
    runner.write_text(runner.read_text() + "\n# user edit\n")
    try: uninstall(home)
    except RuntimeError as exc: check("changed or removed" in str(exc), "uninstall refuses modified owned files before mutation")
    else: raise AssertionError("modified install uninstalled")
    check(tool.exists(), "failed uninstall leaves component intact")
    shutil.copy2(package / "payload/run-workflow", runner)
    result = uninstall(home)
    check(result["uninstalled"] and not root.exists(), "isolated uninstall removes complete owned installation")
    check(not list((home / "Library/PDF Services").glob("*.workflow")) and not list((home / "Library/Services").glob("*.workflow")), "all owned workflow bundles removed")
    check(sentinel.read_bytes() == b"user document sentinel" and interleaved.exists(), "uninstaller retains unrelated and generated user documents")
    install(package, home); uninstall(home)
    check(not root.exists(), "cold isolated reinstall/uninstall passes")
    conflict_bundle = home / "Library/PDF Services" / next((package / "workflows/PDF Services").iterdir()).name
    conflict_bundle.mkdir()
    try: install(package, home)
    except RuntimeError as exc: check("existing workflow" in str(exc), "installer refuses an existing workflow directory even without colliding files")
    else: raise AssertionError("merged existing workflow")
    check(not root.exists(), "workflow conflict causes no installation mutation")
    conflict_bundle.rmdir()
    broken_package = temp / "bad-package"
    shutil.copytree(package, broken_package)
    invalid = broken_package / "workflows/Preferences/whatever"
    invalid.parent.mkdir(parents=True); invalid.write_text("not a workflow")
    invalid_manifest = json.loads((broken_package / "manifest.json").read_text())
    invalid_manifest["files"]["workflows/Preferences/whatever"] = {"sha256": digest(invalid), "bytes": invalid.stat().st_size}
    (broken_package / "manifest.json").write_text(json.dumps(invalid_manifest))
    try: install(broken_package, home)
    except RuntimeError as exc: check("outside the owned" in str(exc), "malformed manifest cannot write workflows/Preferences/whatever")
    else: raise AssertionError("out-of-scope manifest accepted")
    check(not root.exists() and not (home / "Library/Preferences/whatever").exists(), "invalid manifest refused before all mutation")
    real_dump = maintenance.json.dump
    def fail_receipt(*args, **kwargs):
        raise OSError("simulated receipt write failure")
    maintenance.json.dump = fail_receipt
    try:
        try: install(package, home)
        except OSError as exc: check("simulated receipt" in str(exc), "receipt write fault injected")
        else: raise AssertionError("receipt error ignored")
    finally:
        maintenance.json.dump = real_dump
    check(not root.exists() and not list((home / "Library/Services").glob("*.workflow")), "receipt failure rolls back receipt, payload and workflows")

report = {"passed": True, "count": len(checks), "checks": checks,
    "ui_selection_tested": False, "preview_open_action_executed": False, "physical_printing_tested": False,
    "real_user_installation_changed": False, "automator_run_shell_script_executed": True}
(evidence / "workflow-lifecycle-tests.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
print(json.dumps(report, indent=2, ensure_ascii=False))
