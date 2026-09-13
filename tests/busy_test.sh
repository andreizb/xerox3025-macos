#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later WITH SANE-exception
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build/busy-acceptance
clang -arch arm64 -O1 -g -fsanitize=address,undefined \
  -Ibuild/sane/backend -Ibuild/sane/include -Iupstream/sane-backends/include \
  -Iprefix/include tests/busy_test.c \
  build/sane/sanei/.libs/libsanei.a build/sane/lib/.libs/liblib.a \
  build/sane/backend/.libs/sane_strstatus.o \
  -Lprefix/lib -ljpeg -lusb-1.0 -lm -lobjc \
  -framework CoreFoundation -framework IOKit \
  -Wl,-rpath,"$PWD/prefix/lib" -o build/busy-acceptance/busy-test
build/busy-acceptance/busy-test
