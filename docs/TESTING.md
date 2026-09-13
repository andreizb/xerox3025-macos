# Verification

`python3 scripts/check.py` runs offline Python queue/rollback/export tests and
native TCP framing tests with sanitizers. It also parses Python sources, checks
shell syntax and verifies vendored Go source against its manifest. It never
contacts the printer or changes installed services. Build outputs stay ignored.

After a complete scanner build, use `tests/busy_test.sh` for the backend busy
state test. The C/C++ sources also cover final-band reading, crop geometry and
worker serialization against the patched upstream code. These are synthetic
checks, not scan acceptance. See tests/busy_test.md for backend details.

Optional component checks:

- `experiments/ipp-supply-proxy/build.py` runs the Go suite with race detection
  and verifies native binaries. Python maintenance tests use fake queues only.
- `experiments/native-documents/README.md` documents native PDF and workflow tests.
- `experiments/scan-alignment/test.py` uses synthetic PDFs and optionally supplied
  private physical evidence. Missing private cases are explicitly skipped.
- `experiments/scanner-options/README.md` describes an uninstalled profile candidate.
- `experiments/offline-print-acceptance/README.md` describes file-to-file Apple
  filters. The fixture generator does not submit jobs; provide your own private PPD.

Only run `scripts/capture.py`, `accept-escl.py`, `accept-formats.py` or
`accept-cancel.py` when a physical test sheet is ready: they actuate the scanner.
`probe-inquiry.py --printer-uuid UUID` is a read-only device query, not a scan.
Generated images and logs go under ignored evidence directories.

Release acceptance requires actual acquisition through each native route,
correct dimensions/modes/crop, cancellation and repeat jobs, reconnection and
sleep recovery, and guarded uninstall/reinstall. If the toner proxy is installed,
verify native Supply Levels and physical printing through the preserved queue.
New hardware transports, page detection and document workflows need their own
physical/visible acceptance, not just source or protocol checks.
