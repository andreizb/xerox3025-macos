# Public source readiness — 11 October 2026

The implementation at commit `73cb957d93bbd040ef9b7ee85266cc3ef328b9ec` was
exported into a fresh temporary directory and built without the old development
workspace or its cached dependencies. Publication changes clarify documentation
and preserve compact historical records; they do not change scanner behavior.

## Verified

- The complete four-commit history was inspected for known private identifiers,
  credential patterns, personal filesystem paths and private/generated files.
  No matches were found. Git author addresses use GitHub's no-reply address.
  This is a bounded review, not a guarantee against every possible secret.
- All 129 tracked paths were covered by the corresponding-source allowlist.
- Fresh scanner and toner builds downloaded their pinned sources, verified hashes,
  and generated both packages. All nine scanner runtime binaries and both toner
  binaries were ARM64; packaging verified their ad-hoc signatures.
- 40 scanner/packaging Python tests, 19 toner maintenance tests and eight native
  TCP cases passed. The toner Go suite passed with race detection enabled.
- The real scanner package passed 40 staging checks, including relocation,
  library loading, integrity failures, guarded association lifecycle and removal.
  The real toner package installed and uninstalled in an isolated Library using
  a synthetic review. No real queue, launch service or physical scan was changed.
- The scanner corresponding-source archive excluded private identity, evidence
  and Git metadata. No development-directory runtime dependency was found in
  the installed components' launch configuration or linked libraries.

The temporary source trees, compilers, caches, packages and test fixtures were
removed after verification. Sanitized results live here; raw logs are local-only.

## Requirements for another user

Use an Apple Silicon Mac and the prerequisites in BUILD.md. Build/download access
to the pinned public upstream sources is required unless using a complete offline
source package. Supply your own hardware UUID, allow local-network access if
macOS requests it, and follow QUEUE_ASSOCIATION.md for the existing AirPrint entry.
The initial discovery stage alone does not qualify Open Scanner association.

This is an experimental source distribution, not a notarized driver release.
The current build is network-only. NI/ADF/fax hardware, USB, other Mac/OS setups
and optional document workflow UI are not qualified by these tests. The existing
capability and physical-acceptance limits in STATUS.md remain in force.

## Retired workspace

The old `printer-modernization` development folder is not required to build or
run the project. Its original specification, custom source, text/JSON acceptance
records and historical notes are retained locally in an ignored compact archive
under `private/`. Photographs, scanned PDFs, generated installers, firmware images,
upstream copies and build outputs are not published and are not retained merely
to reconstruct disposable artifacts. Current source and license notices remain
tracked; installed components retain their own private rollback state.
