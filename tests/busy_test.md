# BUSY and reservation regression

Run after the isolated SANE build has produced its support archives:

```sh
bash tests/busy_test.sh
```

This compiles the current `xerox_mfp.c` with AddressSanitizer and
UndefinedBehaviorSanitizer. The harness uses the actual SANE start, read and
cancel entry points. It replaces the clock, sleep and device transport;
attempting real TCP or USB acquisition aborts the test. The release support
archives linked into the harness are not themselves instrumented.

The thirteen checks cover unowned reservation timeout, owned position and image
timeouts, cleanup errors, temporary-file closure, retry using the same handle,
owned/unowned cancellation before scanning starts, independent command budgets,
clock failure and a BUSY reply arriving after the deadline. No physical scanner
or persistent installation is used.

On 9 September 2026 the retained previous source, reconstructed from the pinned
commit plus the previous project patch, failed twelve checks. Its infinite loops
were stopped by a separate 120-second virtual-time test guard. The unchanged
finite-BUSY case passed. The corrected source passed all thirteen checks, with
ordinary BUSY retry expiration at exactly 60 seconds of virtual monotonic time.
The pre-fix and corrected outputs are retained in `build/busy-acceptance`.

The existing twelve `final_band_test.c` cases also passed against a shared
library compiled from this same instrumented backend and fake-transport fixture.
That confirms gray/line-art buffered reads were not disturbed; it is not a
physical crop or optical-geometry result. Final release qualification must also
run that harness against the newly built release backend.

The production change imposes a 60-second retry budget for each command that
returns BUSY. It does not terminate a successful acquisition after 60 seconds.
An already-running transport request and best-effort ABORT/RELEASE cleanup retain
their own transport timeouts, so 60 seconds is not a strict total wall-clock job
limit. Cleanup is sent only for this handle's recorded reservation, and cleanup
errors cannot replace the BUSY/cancellation error returned to the caller.
