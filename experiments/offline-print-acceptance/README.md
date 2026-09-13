# Offline Apple print-filter experiments

These development helpers convert synthetic PDFs into Apple URF files and inspect
page order, geometry, labels and layout. They never submit print jobs. Results
characterize the host filter stage, not every application's print dialog or
physical printer output. Apple system binaries/frameworks stay provided by macOS.

Requires Apple Silicon, Xcode tools, Python with ReportLab and pypdf, and a
**private PPD snapshot** from the AirPrint queue being evaluated. The snapshot is
not distributed. Generated fixtures, raster outputs and diagnostics are ignored.

From the repository root:

```sh
mkdir -p experiments/offline-print-acceptance/tmp
python3 experiments/offline-print-acceptance/build-fixtures.py
clang -arch arm64 -O2 -Wall -Wextra -Wno-deprecated-declarations \
  experiments/offline-print-acceptance/decode-raster.m \
  -framework Foundation -framework CoreGraphics -framework ImageIO -lcups \
  -o experiments/offline-print-acceptance/tmp/decode-raster
swiftc -target arm64-apple-macos14.0 -O \
  experiments/offline-print-acceptance/read-labels.swift \
  -o experiments/offline-print-acceptance/tmp/read-labels
python3 experiments/offline-print-acceptance/run.py --ppd /absolute/private/queue.ppd
python3 experiments/offline-print-acceptance/verify.py
```

Pass `--case NAME` with `--ppd` for an individual conversion. The verifier expects
the full 28-case set. Output remains in the ignored historical experiment directory
`evidence/2026-09-09/unattended-print/`; the directory name does not date a new run.
The allowed conversion graph is guarded to Apple's `cgpdftoraster` only.

The additional Automator inspection/execution scripts investigate Apple's existing
watermark and renaming actions with synthetic fixtures. They do not install
Quick Actions. Advanced native UI and physical output qualification remains
separate. See the optional native-documents component for packaged workflows.

Original helpers use the root MIT license. No Apple action implementation or
proprietary printer executable is redistributed.
