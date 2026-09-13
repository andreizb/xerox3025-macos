# Optional native document workflows — review candidate

This component adds explicitly selected actions to Apple's existing **Print →
PDF** menu and Finder **Quick Actions / Services**. It runs a small ARM64 command
in the background, then opens the resulting PDF in **Preview**. It has no app,
menu-bar item, scanner front end, watcher, login job, network access or printing
command. It does not change the installed Xerox scanner, toner bridge, AirPrint
queue or native scanner settings.

**Optional and not installed by the scanner installer.** The native PDF processing and the actual
Automator execution path are tested offline. Visibility and selection in the
Print menu / Finder Services, opening the result in Preview and physical booklet
refeeding still need a user-present acceptance test. No print job was submitted.

## Actions

| Action in the Apple interface | Input / behavior | Limits |
|---|---|---|
| Xerox - Pregătește broșură A4 | One PDF; creates landscape A4 sheet faces, two pages per face, left binding. Pads the logical page count to a multiple of four. | Saves alternate front/back faces; does not feed or print paper. Five millimeter inset on each half. The printer's physical refeed direction needs a paper test. |
| Xerox - Compune act față-verso pe A4 | Exactly two PDF pages, front then back, **already cropped to the card edges in Preview**. Fits both to separate 85.60 × 53.98 mm areas on one A4 page. | Rejects pages outside a 10% tolerance of landscape card aspect ratio. No automatic card detection, physical scale calibration or recovery of clipped content. |
| Xerox - Elimină paginile PDF complet goale | Removes only pages with no content commands, text or annotations. | **Keeps scanned white pages and faint marks.** Raster appearance alone cannot prove a blank page. Refuses a zero-page result. |
| Xerox - Îmbină fețele, verso în aceeași ordine | Finder only: select matching `name-fronts.pdf` and `name-backs.pdf`. Produces front 1, back 1, front 2, back 2… | File names determine roles; Finder selection order is ignored. Front/back counts must match, or fronts may have exactly one additional last page. |
| Xerox - Îmbină fețele, verso în ordine inversă | Same two inputs; reads the backs from the last page to the first. | Choose this only when the back stack was scanned in reverse order. No page is silently discarded. |
| Xerox - Îndreaptă PDF | Included only when the optional, separately tested `xerox-pdf-deskew` binary is packaged. | Its own report records the accepted angle or reason for skipping. It cannot recover content outside the captured scanner area. |

Each invocation creates a private folder below **Documents/Xerox Documents**.
It contains `original.pdf` (or both original front/back PDFs), `processed.pdf`,
and `report.json`. The originals are byte-for-byte copies and the incoming files
are never modified. The report records source/output hashes, page order and the
operation. A failed run removes its own partial folder. The uninstaller leaves
all of these user documents intact.

For a PDF Print Plugin, `original.pdf` is the PDF supplied by the **application's
print system**, after that application's page selection and layout. To work on
the original PDF page objects, use the Finder Quick Action instead. For booklet
creation through Print, use one page per sheet in the application's print dialog;
the plugin performs its own two-page layout. The result is a PDF to inspect in
Preview, not an automatically submitted job.

## Preservation boundaries

Interleaving and removing empty pages copy page objects through PDFKit. Native
tests check exact rendered pixel equality, media/crop boxes, rotations, text/OCR
and annotations. Each operation checks geometry/annotation counts and extracted
text again after serialization and refuses changes. PDFKit normalizes nonzero
MediaBox origins, so structural copy operations reject those unusual PDFs.
Nonzero CropBox origins with ordinary zero-origin media boxes are tested.
Booklet and card composition draw those pages into a PDF context
with public PDFKit/CoreGraphics; the tested text remains selectable, and no image
rasterization or new OCR pass is requested. Composition flattens page annotations
into the derivative.

Output page labels are numbered again in output order. Document-level outlines,
signatures and other catalog structures are not preserved, so this is not a
byte-for-byte or archival PDF transformer. Interactive form/signature widget PDFs
and encrypted PDFs are rejected rather than silently stripped. Original copies
remain available. Complex PDF features beyond the supplied tests are not qualified.

This does **not** implement noisy scanned-page blank detection, background
cleanup, watermark editing, overlays, poster tiling, naming templates or physical
duplex calibration. Image Capture's OCR checkbox is untouched.

## Build and review

Requires Apple Silicon with Apple Xcode command line tools/SDK and an existing ARM-native
Python 3 for build/maintenance only. The runtime uses Apple's frameworks and the
system shell; no Homebrew package is used at runtime.

From this source directory:

```sh
python3 build.py
python3 package.py --output dist/Xerox3025Documents-review
```

Native functional and isolated lifecycle tests (use a fresh fixture directory):

```sh
xcrun swiftc -O -target arm64-apple-macosx13.0 -framework PDFKit -framework CoreGraphics -framework CoreText -module-cache-path build/module-cache Sources/DocumentOps.swift Tests/TestRunner.swift -o build/native-tests
build/native-tests build/test-fixtures
python3 Tests/test_workflows.py dist/Xerox3025Documents-review build/test-fixtures
```

The independent PDF structure checks require `pypdf` only for testing:
`python3 Tests/test_pdf_structure.py build/xerox-document build/test-fixtures`.

The optional deskew binary is supplied with `--deskew-binary /absolute/path/to/
xerox-pdf-deskew`. `architecture.json` records every shipped native binary's
SHA-256, ARM64 slice and linked frameworks. Binaries are ad-hoc signed, not
Developer ID signed/notarized. Only macOS 26.6.2 on this Mac is tested; the compiler
deployment target is not a compatibility promise. Sources are MIT licensed;
Apple's frameworks/actions remain OS components and are not redistributed.

The workflow builder uses **public `AMWorkflow` / `AMBundleAction` APIs** to
serialize the installed Apple Run Shell Script and Open Finder Items actions.
The generated plist metadata declares Print Plugin or Finder Services. No private
action implementation is copied or changed. The actual menu registration remains
an explicit UI acceptance item.

After reviewing the package, its per-user installer is:

```sh
python3 maintenance.py verify --package /absolute/path/to/package
python3 maintenance.py install --package /absolute/path/to/package
```

Installation writes only `~/Library/Application Support/Xerox3025Documents`, the
named Xerox workflows under `~/Library/PDF Services` and `~/Library/Services`, and
an ownership receipt. Existing workflows/installations are never overwritten.
For an isolated lifecycle test, supply `--home /absolute/path/to/test-home`.

To remove it completely:

```sh
python3 "$HOME/Library/Application Support/Xerox3025Documents/maintenance.py" uninstall
```

Uninstall verifies owned bytes before deleting them. A modified or extra file is
retained for review. All scans, processed documents, other services and printer
queues remain untouched. No administrator password is needed for this component.

## Apple sources and local evidence

- [Apple: create an Automator workflow / Print Plugin](https://support.apple.com/en-mn/guide/automator/aut7cac58839/2.10/mac/15.0).
- [Apple: Run Shell Script in Automator](https://support.apple.com/en-euro/guide/automator/aut4bb6b2b4f/mac).
- [Apple PDFPage drawing API](https://developer.apple.com/documentation/pdfkit/pdfpage/draw(with:to:)).
- The current SDK's `PDFPage.h` documents rotation/crop transforms and annotation
  drawing. `AMWorkflow.h` and `AMBundleAction.h` document serialization/actions.
- This Mac's `/System/Library/Automator/Run Shell Script.action` and
  `/System/Library/Automator/Open Finder Items.action` provide the action metadata.
- Tests regenerate local evidence. Private acceptance files are not part of this repository.
