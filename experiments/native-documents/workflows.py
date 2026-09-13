#!/usr/bin/env python3
"""Build-time generation grounded in AMWorkflow's public serializer.

No user Library changes are made here. The last action uses Apple's Open Finder
Items with Preview. Tests omit that single action and execute the actual first
action in /usr/bin/automator; UI selection remains a separate acceptance test.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import plistlib
import subprocess
import tempfile

ACTIONS = {
    "remove-empty": "Xerox - Elimină paginile PDF complet goale",
    "booklet": "Xerox - Pregătește broșură A4",
    "id-card": "Xerox - Compune act față-verso pe A4",
    "interleave-same": "Xerox - Îmbină fețele, verso în aceeași ordine",
    "interleave-reverse": "Xerox - Îmbină fețele, verso în ordine inversă",
    "deskew": "Xerox - Îndreaptă PDF",
}

def generate(builder: Path, destination: Path, action: str, kind: str,
             *, open_preview: bool = True, script_override: str | None = None) -> Path:
    name = ACTIONS[action]
    bundle = destination / (name + ".workflow")
    destination.mkdir(parents=True, exist_ok=True)
    script = script_override or ('exec "$HOME/Library/Application Support/Xerox3025Documents/run-workflow" '
        f"'{action}' \"$HOME/Documents/Xerox Documents\" \"$@\"\n")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh") as handle:
        handle.write(script)
        handle.flush()
        subprocess.run([str(builder.resolve()), handle.name, str(bundle.resolve()), str(open_preview).lower()], check=True, capture_output=True)
    # AMWorkflow on this Mac writes Contents/document.wflow (not the older
    # bundled stock workflows' Contents/Resources/document.wflow).
    doc_path = bundle / "Contents" / "document.wflow"
    document = plistlib.loads(doc_path.read_bytes())
    metadata = document["workflowMetaData"]
    info = {"CFBundleIdentifier": f"local.xerox3025.documents.{kind}.{action}",
            "CFBundleName": name, "CFBundleShortVersionString": "1.0.0"}
    if kind == "print":
        metadata["workflowTypeIdentifier"] = "com.apple.Automator.printPlugin"
    elif kind == "service":
        metadata.update({"workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject.PDF",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing", "serviceProcessesInput": 0})
        info["NSServices"] = [{"NSMenuItem": {"default": name}, "NSMessage": "runWorkflowAsService",
            "NSSendFileTypes": ["com.adobe.pdf"], "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"}}]
    else:
        raise ValueError(kind)
    doc_path.write_bytes(plistlib.dumps(document, sort_keys=False))
    (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    return bundle

def generate_all(builder: Path, destination: Path, *, deskew: bool = False) -> list[Path]:
    output = []
    for action in ACTIONS:
        if action == "deskew" and not deskew:
            continue
        output.append(generate(builder, destination / "Services", action, "service"))
        if not action.startswith("interleave"):
            output.append(generate(builder, destination / "PDF Services", action, "print"))
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--builder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deskew", action="store_true")
    options = parser.parse_args()
    for workflow in generate_all(options.builder, options.output, deskew=options.deskew):
        print(workflow)
