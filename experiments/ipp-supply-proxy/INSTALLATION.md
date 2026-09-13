# Optional native toner correction

This add-on preserves your Xerox queue, its AirPrint driver and your printing
defaults. It changes the queue's device URI to a local background proxy so
Print Center receives the correct black cartridge color. Printing then depends
on this additional service. Review this tradeoff before installation.

It adds no frontend. Ordinary printing and Supply Levels remain in Apple's
existing interfaces. It changes no firmware, Wi-Fi, firewall or printer password.
The separate scanner bridge is installed first. This optional proxy is installed
afterward and must be uninstalled first.

The package is local and ad-hoc signed, not Developer ID signed or notarized.
Both shipped executables are ARM64; imported runtime libraries are Apple's
system libraries. Historical hardware qualification is on one macOS 26.6.2 Mac.
Run the following commands from your newly built and reviewed package directory.

## Review and install

Wait until all print jobs finish. Use an existing queue ID and the printer's
stable hardware UUID. The first command only reads the queue and creates a
private review; it does not change printing:

```
python3 maintenance/proxy-maintenance.py prepare \
  --queue EXISTING_QUEUE_ID --printer-uuid HARDWARE_UUID \
  --output /absolute/path/to/new-private-review
```

Review its `manifest.json`, especially the original Bonjour URI, queue identity
and printing defaults. Installation copies the native background component,
starts it, verifies an actual IPP identity/supply response, and then changes only
the queue URI. An unchanged review is required:

```
./install --review /absolute/path/to/new-private-review
```

Cold launch may need time for macOS to evaluate the two native executables.
Installation waits up to twenty seconds for the process listener, then performs
the actual printer identity/supply query. A process health response alone is not
acceptance. Up to three fast, failed read-only IPP startup exchanges may be
retried; each attempt still requires the same complete identity and supply
checks. Wrong identities or unexpected supply data fail immediately. Printing
operations are never retried by this proxy. If startup fails before the URI
change, the direct printer remains
active and the partial installation is removed. Private `install-failure-*.json`
diagnostics are retained inside the supplied review directory.

Maintenance requires native ARM64 Python 3.9+. Use `--python
/absolute/path/to/python3` with install/uninstall to select an interpreter.
Python is never a runtime dependency of the background printing proxy.

The installer refuses an existing service, an occupied port 18326, unfinished
jobs, or any queue already pointing at this proxy. A reinstall uses guarded uninstall followed by a fresh review and install.

## Remove

Uninstall the optional toner component before the scanner bridge:

```
./uninstall
```

An installed copy is also retained at
`~/Library/Application Support/Xerox3025SupplyProxy/uninstall`.
The uninstaller restores the recorded Bonjour URI before unloading or deleting
the proxy. It preserves the queue's current PPD, preferences and defaults. If the
queue's URI/UUID has changed, a write is uncertain, or jobs are unfinished, it
retains the working service and private rollback for review.

Owned files: `~/Library/Application Support/Xerox3025SupplyProxy/` and
`~/Library/LaunchAgents/local.xerox3025.supply-proxy.plist`. User scan documents
and printer queues are never deleted. A successful package uninstaller can be
run repeatedly.

The entry scripts support macOS's stock Bash 3.2. A qualification run exposed
its rejection of an empty argument array under `set -u`; the shipped wrappers
initialize nonempty operation arguments. Regression coverage checks empty and
forwarded arguments using the actual system shell. This correction was accepted
as candidate 04 and is included in the final package. The native runtime is
unchanged by the wrapper correction.

## Build and isolated checks

Extract `corresponding-source.tar.gz`, then run `python3 build.py --offline`
from `printer-modernization/experiments/ipp-supply-proxy`. The source archive
contains the pinned official Go toolchain archive, dependency source, manifests,
license notices and all local code. Ordinary builds use their own local cache.
No system package is installed. `python3 test_maintenance.py` exercises only fake
CUPS queues and temporary Library folders. All 19 maintenance tests passed,
including six argument cases executed by the system shell.

Use `--staging-library /absolute/path/to/temporary/Library` with package
install/uninstall for a file lifecycle test. Staging does not start launchd,
query the printer or change a queue, and cannot undo an actually applied URI.

Hardware results and remaining acceptance gates are summarized in the repository's
`docs/STATUS.md`. Private scans, queue snapshots and generated releases are not
included. The scanner package supplies `uninstall-all` to remove the toner service
first and then the scanner association.
