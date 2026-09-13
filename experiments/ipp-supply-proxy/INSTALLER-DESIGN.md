# Optional supply proxy installation design

Implemented as a separate reviewable add-on, 9 September 2026. No original queue
has been changed by this lane. This component remains separate from the scanner
package. Native Supply Levels passes; installation and printing acceptance are
tracked by the parent task.

The owner would explicitly review a separate add-on. It preserves the existing
queue, AirPrint PPD and print settings, but changes its device URI from the
physical Bonjour printer to `ipp://127.0.0.1:18326/ipp/print`. Printing then depends
on this background process being available. The scanner association is installed
first; this optional URI change is installed afterward.

## Owned files and prerequisites

- Per-user runtime and private rollback under
  `~/Library/Application Support/Xerox3025SupplyProxy/`.
- One separate LaunchAgent, `local.xerox3025.supply-proxy`, with the bundled native
  proxy, native Bonjour discovery executable, stable hardware UUID and fixed
  numeric loopback listener. No frontend or menu-bar app.
- ARM64 binaries, system-only runtime imports, verified signatures and payload
  hashes. Include preferred source, pinned toolchain/dependency hashes, vendored
  OpenPrinting source and all applicable license notices.
- Python may be used by maintenance only, with the same explicit native
  interpreter checks as scanner association maintenance. No Python network
  forwarding, alternate binary identity or firewall change.
- All CUPS administration uses the normal authenticated local socket explicitly,
  `/private/var/run/cupsd`; the TCP `localhost` endpoint required separate
  credentials in the observed test.

## Installation transaction

1. Read an explicit private review containing the queue name, CUPS queue UUID,
   hardware UUID, original Bonjour URI, AirPrint PPD digest, effective settings,
   user preferences and selected default. Refuse unapplied review drift, another
   queue, another printer or any unfinished print job.
2. Verify and copy the complete runtime. Refuse an existing installation,
   LaunchAgent or occupied listener. Start this owned service while the original
   direct AirPrint URI remains active.
3. Query the actual proxy IPP endpoint. Require the configured hardware UUID and
   contemporaneous corrected black-toner metadata; a process health response is
   insufficient. Failed discovery, network access, identity or metadata leaves
   the original URI intact and removes only this attempted installation.
   Allow a bounded cold-start readiness wait first. Preserve query stdout/stderr
   and launchd metadata in the original private review if startup fails.
4. Immediately recheck the queue and absence of jobs, record a pending operation,
   then make the single URI change. Never recreate the queue or change its PPD.
   Snapshot the actual result even if the administration command fails or times
   out. Do not blindly retry an uncertain write.
5. Require the exact URI change with identical queue UUID, current PPD, options,
   defaults and user preferences. If uncertain, retain rollback and the running
   service until the actual state can be reviewed. Do not leave a queue pointing
   at a stopped process.

## Uninstall and rollback

Uninstall this optional proxy **before** removing the scanner association. The
scanner association's restore guard expects its original Bonjour device URI.

Require the same queue UUID and the currently owned loopback URI, with no active
or queued jobs. Save the *current* PPD, preferences and defaults, restore only the
recorded original Bonjour URI, then verify that every other current setting is
unchanged. A later unrelated PPD/default edit is preserved; a later URI change
requires review. Restore the URI before unloading the LaunchAgent, stopping the
proxy or deleting runtime/rollback files. A rejected or uncertain restore keeps
the working service and evidence in place.

If the queue has been deleted, verify that no remaining queue points at this
listener before removing an orphaned service. Never delete a queue as rollback.
Make successful repeated uninstall a no-op. Retain all user scan documents and
printer network configuration.

## Qualification

Offline synthetic HTTP, streaming, shutdown and lifecycle tests cover software
behavior. Actual native Supply Levels, physical printing and combined rollback
were separately accepted on the original Mac. See `docs/STATUS.md` at the
repository root for the current limits. New-machine, logout/login and broader
compatibility acceptance must not be inferred from the offline suite.
