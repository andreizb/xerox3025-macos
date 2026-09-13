#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare an uninstalled, review-only first-profile compatibility candidate."""
from pathlib import Path
import difflib
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
(HERE / "evidence").mkdir(exist_ok=True)
SOURCE = ROOT / "upstream/AirSane/server/scanner.cpp"
original = SOURCE.read_text()
modified = original
replacements = [
    (
        "  void writeSettingProfile(int bits, std::ostream&) const;",
        "  void writeSettingProfile(int bits, std::ostream&, bool includeLineart = false) const;",
    ),
    (
        "Scanner::Private::writeSettingProfile(int bits, std::ostream& os) const",
        "Scanner::Private::writeSettingProfile(int bits, std::ostream& os, bool includeLineart) const",
    ),
    (
        "  if (bits == 1)\n    os << \"<scan:ColorMode>BlackAndWhite1</scan:ColorMode>\\r\\n\";",
        "  if (bits == 1 || includeLineart)\n    os << \"<scan:ColorMode>BlackAndWhite1</scan:ColorMode>\\r\\n\";",
    ),
    (
        "    if (bits != 1 || format != HttpServer::MIME_TYPE_JPEG)",
        "    if ((bits != 1 && !includeLineart) || format != HttpServer::MIME_TYPE_JPEG)",
    ),
    (
        "  p->writeSettingProfile(mMaxBits, os);\n  if (!p->mLineartScanModeName.empty()) p->writeSettingProfile(1, os);",
        """  // Apple AirScanScanner 63.3 builds its ICA color choices from profile 0.
  // Put all accepted modes and their common lossless formats there. JPEG is
  // still offered separately for continuous-tone modes; never advertise it
  // for a one-bit mode. No new mode or resolution is synthesized here.
  const bool haveLineart = !p->mLineartScanModeName.empty();
  const bool commonFirstProfile = haveLineart && xeroxcrop::applies(
      p->mDeviceInfo.name, p->mMakeAndModel, this == p->mpPlaten,
      p->mpAdfSimplex != nullptr || p->mpAdfDuplex != nullptr);
  p->writeSettingProfile(mMaxBits, os, commonFirstProfile);
  if (haveLineart) p->writeSettingProfile(commonFirstProfile ? mMaxBits : 1, os);""",
    ),
]
for old, new in replacements:
    if modified.count(old) != 1:
        raise SystemExit("Source changed: candidate requires a fresh review of " + repr(old))
    modified = modified.replace(old, new)
target = HERE / "candidate/server/scanner.cpp"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(modified)
patch = "".join(difflib.unified_diff(original.splitlines(True), modified.splitlines(True),
                                   fromfile="a/server/scanner.cpp", tofile="b/server/scanner.cpp"))
(HERE / "AirSane-first-profile-common-formats-review.patch").write_text(patch)
manifest = {
    "installed": False,
    "physical_or_native_app_acceptance": False,
    "base_commit": json.loads((ROOT / "sources.lock.json").read_text())["AirSane"]["commit"],
    "base_local_source_sha256": hashlib.sha256(original.encode()).hexdigest(),
    "candidate_source_sha256": hashlib.sha256(modified.encode()).hexdigest(),
    "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
    "scope": "Xerox flatbed SettingProfile grouping/order only; no threshold, halftone, or 1200 dpi advertised",
}
(HERE / "evidence/candidate.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, indent=2))
