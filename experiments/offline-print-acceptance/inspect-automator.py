#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read only the metadata of already-installed Apple Automator actions.

No action, workflow, application, document, filter or shell-script action is
executed or installed. Binary inspection uses lipo only for architecture names.
"""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evidence/2026-09-09/unattended-print/automator-action-inventory.json"
NAMES = ["Watermark PDF Documents", "Rename Finder Items", "Rename PDF Documents",
         "Apply Quartz Filter to PDF Documents", "Copy Finder Items", "Crop Images"]


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


actions=[]
for name in NAMES:
    folder=Path("/System/Library/Automator")/(name+".action")
    info_path=folder/"Contents/Info.plist"
    if not info_path.exists():
        actions.append({"name":name,"present":False}); continue
    info=plistlib.loads(info_path.read_bytes())
    exe=folder/"Contents/MacOS"/info["CFBundleExecutable"]
    labels_path=folder/"Contents/Resources/main.loctable"
    labels=plistlib.loads(labels_path.read_bytes()).get("en_GB",{}) if labels_path.exists() else {}
    # Retain actual control labels, not full localized resources or embedded
    # image/ICC data. Hashes point to the exact Apple-owned source files.
    control_labels=sorted(set(v for k,v in labels.items()
                              if k.endswith((".title",".label")) and isinstance(v,str)
                              and v not in ("OtherViews","Radio","Box","Tab","View","Item2","Item3")))
    warning=info.get("AMWarning",{})
    actions.append({"name":name,"present":True,"path":str(folder),
                    "bundle_id":info.get("CFBundleIdentifier"),
                    "version":info.get("CFBundleShortVersionString"),
                    "info_sha256":sha(info_path),"binary_sha256":sha(exe),
                    "architectures":subprocess.check_output(["/usr/bin/lipo","-archs",str(exe)],text=True).split(),
                    "accepts":info.get("AMAccepts"),"provides":info.get("AMProvides"),
                    "can_show_parameters_when_run":info.get("AMCanShowWhenRun"),
                    "default_parameters":info.get("AMDefaultParameters"),
                    "warns_input_mutation":warning.get("Level",0)>0,
                    "suggests_copy_finder_items":warning.get("Action")=="com.apple.Automator.CopyFiles",
                    "control_labels_from_english_localization":control_labels,
                    "labels_sha256":sha(labels_path) if labels_path.exists() else None,
                    "executed":False})
filters=[]
for path in sorted(Path("/System/Library/Filters").glob("*.qfilter")):
    data=plistlib.loads(path.read_bytes())
    image=data.get("FilterData",{}).get("ColorSettings",{}).get("ImageSettings")
    filters.append({"path":str(path),"sha256":sha(path),"name":data.get("Name"),
                    "domains":data.get("Domains"),"image_settings":image,"executed":False})
report={"scope":"Read-only installed action/filter metadata. No UI, execution or action installation.",
        "inspector_path":str(Path(__file__).resolve().relative_to(ROOT)),
        "inspector_sha256":sha(Path(__file__).resolve()),
        "actions":actions,"quartz_filters":filters,
        "native_presence_confirmed":all("arm64e" in action.get("architectures",[]) for action in actions),
        "execution_acceptance":False,"workflows_created":0,"documents_modified":0,
        "sources":["https://support.apple.com/guide/automator/aut7cac58839/mac",
                   "https://support.apple.com/en-ca/guide/automator/atmtr15198/mac",
                   "https://support.apple.com/guide/colorsync-utility/add-or-modify-quartz-filters-csync006/mac"]}
OUT.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps({"present_actions":sum(x["present"] for x in actions),
                  "quartz_filters":len(filters),"all_actions_have_apple_silicon_slice":report["native_presence_confirmed"],
                  "executed":False}))
