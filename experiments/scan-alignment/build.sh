#!/bin/sh
set -eu
here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$here/build"
/usr/bin/swiftc -O -target arm64-apple-macosx14.0 "$here/deskew.swift" -o "$here/build/xerox-pdf-deskew"
/usr/bin/codesign --force --sign - "$here/build/xerox-pdf-deskew"
/usr/bin/lipo -archs "$here/build/xerox-pdf-deskew"
