# Uninstalled scanner setting-profile candidate

The production build does not apply this experiment's extra AirSane patch.
It groups common formats in the first profile for the WC3025 flatbed while
retaining the existing set of mode/format/resolution combinations. No threshold,
halftone, 1200 dpi, ADF or fax support is promised by this candidate.

After building the production source tree, `python3 test-profiles.py` prepares
an isolated candidate and exercises the actual baseline/candidate XML writers
with synthetic devices. It does not open a scanner or install a service.
The probe uses synthetic identity values. Generated source, binaries and evidence
are ignored. A full native acquisition/UI test is still required before adoption.

`python3 test-backend.py --inquiry /absolute/private/inquiry.json` checks actual
backend option/inquiry/window routines using a disconnected recorder. Supply a
complete 70-byte response from `scripts/probe-inquiry.py`; private device inquiry
captures are intentionally absent from Git. This is protocol construction
coverage, not acquisition or firmware compatibility acceptance.

AirSane-derived work retains GPL-3.0-or-later. SANE-derived tests retain its GPL
and exception notices. Private Apple implementation inspection is not distributed.
