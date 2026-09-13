# Conservative PDF deskew — reviewed optional component

9 September 2026. Native ARM64 command, implemented using Apple's public
Vision, CoreGraphics and PDFKit frameworks. It is invoked explicitly from the
optional native document workflows; it has no app, watcher, daemon or scanner
frontend. **Not installed or accepted in the visible Apple UI yet.**

Software can straighten captured content. It cannot recover parts of a sheet
outside the selected acquisition area or the physical sensor. Sheet placement
alone does not establish a print-margin or scanner-coordinate defect.

Apple documents that **Detect Separate Images** can straighten items while
**Detect Enclosing Box** cannot. These are the first native acquisition choices
to check on the unlocked Mac. Their presence and behavior on this exact scanner
have not been accepted. See [Apple's scanner guide](https://support.apple.com/guide/mac-help/scan-images-documents-a-scanner-mac-mh28032/mac).

## What this command does

```
xerox-pdf-deskew INPUT.pdf OUTPUT.pdf
```

It renders each page in memory solely to measure text-line angles with Vision.
At least five long, sufficiently confident lines and 75% agreement are required.
An image projection refines that estimate; corrections smaller than 0.25 degrees
or larger than 8 degrees are skipped. Photographs, sideways pages, sparse and
ambiguous documents may therefore remain unchanged. This is an intentionally
limited text-document tool, not general photo or perspective correction.

Corrected pages use affine CoreGraphics PDF drawing. The media box expands to
contain the entire original page after rotation: content is not cropped or
rasterized. This means a corrected A4 PDF is slightly larger than A4; use native
Fit to Page when printing it on A4. It does not automatically recenter or remove
the paper background. Existing selectable text/OCR must survive an internal
comparison before any output is written. Vision's recognized strings are not
saved and no new searchable text is inserted. The Apple OCR choice is respected.

The input is never rewritten. An existing output, alias or symlink is refused;
exclusive creation and mode 0600 protect the new file. If every page is skipped,
the derivative is byte-identical. JSON on stdout reports hashes, per-page
decisions, angles and sizes, with no document text. A native workflow keeps its
incoming PDF alongside the derivative and report in a private operation folder.

Encrypted PDFs, annotations/forms, bookmarks, attachments/names, tagged PDFs,
optional layers, portfolios and custom crop boxes are refused instead of silently
discarding their structure. Limits are 512 MiB, 300 pages and 200 inches per page.
Document metadata and custom page labels are not preserved by reconstructed
pages; use the retained original for archival metadata. This component does not
modify Apple's OCR preference persistence or any installed scanner settings.

## Build and qualification

Run `sh build.sh` on Apple Silicon with Xcode/Command Line Tools. It compiles
`deskew.swift` with `swiftc`, targets the macOS 14 ABI and signs ad hoc. Runtime
imports are Apple frameworks only. Actual qualification is on macOS 26.6.2;
the deployment target does not certify other macOS versions. No Rosetta or
third-party runtime is needed.

`test.py` needs Python, ReportLab, pypdf and Poppler for test fixtures and independent
inspection, not runtime. Install those test prerequisites in an isolated environment. The physical-document cases use private retained acceptance scans
under the project evidence directory, which are excluded from distributable
source. Those cases are skipped when absent or when `XEROX_SKIP_PRIVATE=1`.
Synthetic cases are reproducible without a printer. Set `PDFTOPPM` if Poppler
is outside PATH and the bundled runtime. The portable run passed 122 assertions.

The recorded full qualification passed 134 assertions, including:

- Known angles -3, -1, +2, +7 degrees, independent text extraction and a second image
  analysis of the corrected result. The largest error from the known angle was
  under 0.1 degrees in those fixtures; this is not an accuracy guarantee for all
  documents.
- Blank, sparse, ambiguous, 12 degree and sideways inputs left unchanged; annotated,
  encrypted, malformed and custom-cropped inputs rejected.
- Actual image-only PDF correction without added OCR; invisible existing OCR
  retained during an actual correction; multipage decisions kept independent.
- Input hashes, exclusive output creation, existing-file and symlink protection.
- Saved physical Print Center scan left byte-identical because it was already
  essentially straight. A synthetic tilt of that sparse scan may be refused;
  this is retained as a limitation, not counted as a successful physical deskew.

The corrected synthetic PDF was rendered with Poppler and visually inspected:
all 18 lines are present, upright and unclipped. Tests regenerate ignored evidence locally; historical private artifacts are not in Git.

Visible Print/PDF and Finder Quick Action selection, actual native automatic
size detection, and a freshly placed skewed physical page remain separate
interactive acceptance gates. No acquisition or paper output occurred here.

Public API references: [Vision text observations](https://developer.apple.com/documentation/vision/vnrecognizedtextobservation),
[PDF drawing](https://developer.apple.com/documentation/coregraphics/cgcontext/drawpdfpage(_:)).

## License

Local source is MIT licensed, like the other local project additions. Apple
frameworks are provided by macOS and are not redistributed in this component.
