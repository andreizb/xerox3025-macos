# Source and license notices

This is an independent interoperability project, not Xerox or Apple software.
This software is based in part on the work of the Independent JPEG Group.

| Component | License | Local changes |
|---|---|---|
| SANE xerox_mfp and DLL frontend | GPL-2.0-or-later; see SANE's stated linking exception and per-file notices | TCP framing, BI sources, WC3025 geometry, bounded JPEG decoding and private temporary storage |
| AirSane | GPL-3.0-or-later | Isolated build, loopback publication, stable identity, 1-bit encoding, serialized cancellation |
| libusb | LGPL-2.1-or-later | None; dynamically linked |
| libjpeg-turbo | IJG and BSD-3-Clause; SIMD notices retained | None; dynamically linked |
| libpng | PNG Reference Library License | None; dynamically linked |

Exact source revisions and archive hashes are in `sources.lock.json`. Full
license notices accompany the binary payload in `licenses`. The candidate
includes `corresponding-source.tar.gz`, containing pristine SANE and AirSane
sources, the actual local patches, build and packaging scripts, and the pinned
dependency archives. Pristine sources in that archive are provided for review
and modification; `scripts/build.py` obtains the same pinned Git revisions when
building normally. All local changes remain available in preferred source form.

The isolated build uses GNU m4, Autoconf, Automake and Autoconf Archive under
their respective GPL licenses and exceptions. Their unmodified source archives
are included; they are build tools and are not installed as runtime dependencies.
Xcode/Apple frameworks and system zlib remain provided by macOS. CMake,
pkg-config, GNU libtool and gettext/autopoint are build prerequisites only.

The optional IPP supply proxy uses OpenPrinting goipp (BSD-2-Clause) and Go
(BSD-3-Clause); exact notices, dependency source and pins live in its directory.
Original native document and deskew sources use the local MIT license. Apple
frameworks and Automator actions are system components and are not redistributed.

Proprietary Xerox firmware, photographs, scans, device identity and private logs
are not included in this repository or the scanner corresponding-source archive.
Build your private identity configuration from `packaging/device.example.json`.
A configured binary installer necessarily contains its target device identity;
keep such installers private. Queue rollback records remain on the installed Mac.
