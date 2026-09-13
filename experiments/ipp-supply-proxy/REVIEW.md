# Optional IPP toner metadata correction

This component corrects the demonstrated WC3025 black-toner color reported as
`#FFFFFF`. It preserves the live level and changes only that validated metadata.
The accepted baseline includes native Supply Levels and physical printing on one
Mac; see the repository's docs/STATUS.md. This is not a universal printer proxy.

The existing AirPrint queue is retained, but its device URI becomes
`ipp://127.0.0.1:18326/ipp/print`. Printing then depends on this per-user service.
Review that tradeoff before installation. Use the guarded installer and keep its
private rollback records; the server itself never changes queues.

## Exact behavior

- Accept IPP POST requests only at `/ipp/print` on a numeric loopback address.
  Browser-origin requests are rejected; no network-facing listener is opened.
- Discover the configured stable hardware UUID using this project's native
  Bonjour discover executable. Confirm both UUID and model through an actual
  IPP query, refresh discovery after 60 seconds, and use the discovered host.
  No IP address is compiled into the program.
- Use Go's maintained `net/http/httputil.ReverseProxy` for HTTP transport and
  OpenPrinting's `goipp` parser for the bounded metadata response.
- Decode only successful Get-Printer-Attributes responses, at most 1 MiB. The
  single black-toner name, type and white color must match the demonstrated
  hardware metadata. After full validation, walk original wire records by their
  lengths to locate the top-level printer marker color. Preserve the device's
  noncanonical unsupported-value records, binary values and nested collections.
- Change only the six `F` color digits to `0`, and verify exactly six bytes
  differ. Leave level, warning thresholds, cartridge identity and every other
  IPP value intact. Unknown or different supplies pass through unchanged.
- Forward non-metadata request and response bodies as streams. Do not parse,
  buffer whole jobs, manufacture pages, or log job data. Do not retry a
  submitted operation after a communication failure.
- On SIGTERM, stop accepting new requests and wait up to ten seconds for active
  responses to drain before closing stalled connections and exiting.

The proxy does not rewrite IPP printer/job URI attributes or manufacture
capabilities. The older device's acceptance of a loopback `printer-uri` and
its response URI behavior require live qualification. The process health URL
reports only process availability. Identity checking, metadata parsing and
response bounds fail closed. Upstream printing remains the printer's existing
unencrypted local IPP transport.

## Reproducible isolated build

Run `python3 build.py` from this directory or invoke its absolute path. The
script downloads the official Go Darwin ARM64 archive pinned by SHA-256 in
`sources.json`; all toolchain files and Go caches remain under this directory's
`build/`. `go.mod` and `go.sum` pin OpenPrinting goipp. The build vendors it,
runs race-enabled tests, builds ARM64, verifies its ad-hoc signature and checks
that runtime imports are Apple's system libraries only. License copies are
under `licenses/`. No Homebrew or system installation is performed.

The offline tests verify unchanged levels including IPP unknown/error
sentinels, unchanged unrelated data, malformed metadata rejection, actual
HTTP correction, browser-origin rejection, and streaming of synthetic
16 MiB bodies with both Content-Length and chunked transfer. The synthetic
producer waits until the mock upstream receives initial bytes before sending
the rest: buffering a complete job cannot pass this test. No synthetic request
is sent to the physical printer. Maintenance tests use fake CUPS state and
temporary Library folders, covering exact URI rollback before unload, retained
user preferences, deferred jobs, missing runtime, changed URI/queue identity,
uncertain/rejected writes and complete removal/reinstallation.

The optional package includes native runtime, private-review maintenance,
installed license notices and an offline corresponding-source archive. Follow
[INSTALLATION.md](INSTALLATION.md) for review, installation and complete removal.
The proxy must be uninstalled before the scanner association, because the latter
requires its original Bonjour URI during restoration. The source checkout itself performs no persistent installation.
