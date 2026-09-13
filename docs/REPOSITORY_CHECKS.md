# Initial repository export checks — 13 September 2026

The curated source was checked on an Apple Silicon Mac running macOS 26.6.2.
This preparation did not reinstall the scanner, touch queues, scan or print.

- All production `src/` files and the three production patch files are identical
  to the retained working source. Changes are packaging privacy, parameterized
  diagnostic helpers, source export checks and portable documentation.
- 29 Python tests passed: queue preservation/association plus four source export
  tests, including private identity exclusion and rejection of symlinked paths.
- 19 toner maintenance tests passed against fake queues and temporary folders.
- Eight native TCP cases passed with AddressSanitizer and UndefinedBehaviorSanitizer.
- 34 Python sources parsed; 11 shell entry points passed shell syntax checks.
  All 20 vendored Go dependency files match their recorded SHA-256 manifest.
- Both optional native document tools rebuilt as ARM64 and their signatures
  verified. The native PDF test runner passed 85 assertions with synthetic inputs.
- An exported corresponding-source subset was extracted into a fresh temporary
  directory and its complete offline repository check passed. It includes the
  optional source and vendor files needed by that check. No private identity file
  or generated fixture is exported. This checks the project-source export helper;
  it is not a fresh complete dependency build or binary installer qualification.

The full scanner dependency build, Go runtime build, visible document menus and
physical/UI acceptance were not repeated for this source migration. Historical
hardware results and remaining gaps are in STATUS.md. Private diagnostics and
physical scans remain outside Git; source checks do not replace those tests.
