# Acceptance status and remaining work

This is a sanitized summary of local acceptance recorded on 9 September 2026.
Private source evidence and original generated releases remain outside this
repository. It is not a claim that every clone or macOS version was tested.
The repository preparation on 13 September did not reinstall anything or run
new physical scans or prints.

## Working baseline

- BI hardware confirmed: flatbed, no ADF/fax/automatic duplex. Main firmware
  V3.50.03.06 and network V6.01.19 were observed in the accepted setup.
- All three native routes acquired separately after the firmware update and an
  actual Mac sleep/wake: original queue's Scanner button to searchable A4 PDF
  (300 dpi), independent Image Capture to gray TIFF (150 dpi), and Preview to
  color PNG (150 dpi).
- Color, grayscale, 1-bit output, region dimensions, 75–600 dpi, cancellation,
  repeated acquisition and recovery were exercised. Native UI tests are distinct
  from HTTP acquisition tests. Concurrent Apple client handover can still report
  device-already-open; close the previous scanner view before opening another.
- Toner correction rendered the native bar black while retaining the live amount.
  Physical printing passed. Combined uninstall/reinstall restored the recorded
  direct queue and then the working installation. Printer power-cycle and Mac
  sleep recovery passed on that setup.

## Limits that remain

- The Apple OCR checkbox resets on reopening the native panel. No supported
  preference solution has been demonstrated. The bridge does not force OCR or
  silently process originals. Other remembered settings are application-specific.
- Precise physical print margins and scan placement are uncalibrated. A sheet
  placed outside the selected A4 area cannot be recovered by software. Native
  automatic size detection and a freshly skewed physical page need an attended test.
- Deskew can straighten confidently detected text inside the captured page and
  expands the PDF canvas to avoid clipping. It cannot move paper or recover missing
  edges. The optional component is not installed by the scanner package.
- Native document processing has offline functional and Automator execution
  coverage. Visible PDF/Finder menu use and physical booklet/refeed calibration
  still need a person. Structural empty-page removal deliberately keeps scanned
  white pages and faint marks; general raster blank detection is not implemented.
- USB attachment/acquisition, actual DHCP address change, logout/login, fresh-user
  installation, 1200 dpi scanning, NI hardware and broader macOS compatibility are
  unqualified. A deployment target is not a compatibility test.
- Advanced background cleanup, automatic card detection, poster tiling, generalized
  watermark/overlay editing and naming templates are not added to scanner controls.
  The isolated Apple-action experiments are not installed product features.
- The extra scanner setting-profile patch is an uninstalled candidate. The normal
  build does not apply it. SpliX printing is a separate future evaluation.

Overall specification acceptance remains incomplete. This repository preserves
working implementation and experiments without treating offline tests as physical
or visible-UI acceptance.
