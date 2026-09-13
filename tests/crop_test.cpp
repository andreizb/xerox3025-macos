// SPDX-License-Identifier: GPL-3.0-or-later
// No scanner access. Test the same coordinate/raster helpers used by AirSane.
#include "server/xeroxcrop.h"
#include <functional>
#include <iostream>
#include <random>

static int checks = 0;
static void check(bool value, const char* reason)
{
  ++checks;
  if (!value) throw std::runtime_error(reason);
}

static void rejects(const std::function<void()>& fn, const char* reason)
{
  bool rejected = false;
  try { fn(); } catch (const std::runtime_error&) { rejected = true; }
  check(rejected, reason);
}

static void testGeometry()
{
  using namespace xeroxcrop;
  check(applies("xerox_mfp:tcp printer.local 9400", "Xerox WorkCentre 3025", true, false),
        "verified model must use overscan");
  check(!applies("xerox_mfp:usb 1", "Xerox WorkCentre 3025", true, true),
        "unverified feeder variant must be excluded");
  check(!applies("other:tcp host", "Xerox WorkCentre 3025", true, false),
        "a model label alone must not select protocol geometry");
  check(!applies("xerox_mfp:tcp host", "Xerox WorkCentre 3210", true, false),
        "other xerox_mfp hardware must be unchanged");

  // Physical proof used logical (165,159,10,4) mm at 300 dpi. These expected
  // dimensions come from the real 118x47 crop, not the old mm-rounded encoder.
  const auto x = acquisitionAxis(165 * 300 / 25.4, 10 * 300 / 25.4, 300, 0, 216);
  const auto y = acquisitionAxis(159 * 300 / 25.4, 4 * 300 / 25.4, 300, 0, 297);
  check(x.beginMm < 162.001 && x.endMm >= 178,
        "interior horizontal acquisition needs 3 mm margin");
  check(y.beginMm < 156.001 && y.endMm >= 166,
        "interior vertical acquisition needs 3 mm margin");
  const auto crop = raster(165 * 300 / 25.4, 159 * 300 / 25.4,
      10 * 300 / 25.4, 4 * 300 / 25.4, 300,
      fixedMm(x.beginMm), fixedMm(y.beginMm),
      backendPixels(fixedMm(x.endMm) - fixedMm(x.beginMm), 300),
      backendPixels(fixedMm(y.endMm) - fixedMm(y.beginMm), 300));
  check(crop.width == 118 && crop.height == 47, "physical proof crop dimensions");
  check(crop.left > 23 && crop.top > 23,
        "interior pixels must start after the demonstrated 23 erased pixels");
  check(!crop.containsRow(crop.top - 1) && crop.containsRow(crop.top) &&
        crop.containsRow(crop.top + 46) && !crop.containsRow(crop.top + 47),
        "the streaming row selector must not write top/bottom overscan");

  // A protocol origin such as 162 mm is truncated to 6.37 in (161.798 mm),
  // so assuming the requested SANE mm value would shift the native crop.
  check(std::abs(encodedOriginMm(162) - 161.798) < 1e-7,
        "hundredth-inch backend origin truncation");
  const auto quantized = raster(165 * 300 / 25.4, 159 * 300 / 25.4,
      10 * 300 / 25.4, 4 * 300 / 25.4, 300, 162, 156, 188, 118);
  check(quantized.left == 37 && quantized.top == 35,
        "read-back physical origin must determine crop offsets");

  // SANE fixed-point maxima do not imply that an upward-rounded final pixel
  // exists. Full-bed and bottom/right crops must fit at every shipped DPI.
  const double bedWidth = fixedMm(10208 * 25.4 / 1200.0);
  const double bedHeight = fixedMm(14040 * 25.4 / 1200.0);
  const int width300 = backendPixels(bedWidth, 300);
  const int height300 = backendPixels(bedHeight, 300);
  check(width300 == 2551 && height300 == 3509,
        "advertised maxima must exclude the unacquired boundary pixel");
  std::mt19937 random(3025);
  for (int dpi : {75, 100, 150, 200, 300, 600}) {
    const double maxWidth = width300 * dpi / 300.0;
    const double maxHeight = height300 * dpi / 300.0;
    for (int sample = 0; sample < 300; ++sample) {
      const double w = sample == 0 ? maxWidth : 1.0 + random() % 500 / 2.0;
      const double h = sample == 0 ? maxHeight : 1.0 + random() % 700 / 2.0;
      const double left = sample < 2 ? 0 :
          sample % 2 ? maxWidth - w : (maxWidth - w) * (random() % 1000) / 1000;
      const double top = sample < 2 ? 0 :
          sample % 2 ? maxHeight - h : (maxHeight - h) * (random() % 1000) / 1000;
      const auto ax = acquisitionAxis(left, w, dpi, 0, bedWidth);
      const auto ay = acquisitionAxis(top, h, dpi, 0, bedHeight);
      check(ax.beginMm >= 0 && ay.beginMm >= 0 &&
            ax.endMm <= bedWidth && ay.endMm <= bedHeight,
            "overscan must stay inside bed on all edges");
      const int acquiredW = backendPixels(fixedMm(ax.endMm) - fixedMm(ax.beginMm), dpi);
      const int acquiredH = backendPixels(fixedMm(ay.endMm) - fixedMm(ay.beginMm), dpi);
      const auto r = raster(left, top, w, h, dpi,
          fixedMm(ax.beginMm), fixedMm(ay.beginMm), acquiredW, acquiredH);
      check(r.width == int(w) && r.height == int(h),
            "noninteger native sizes use complete requested pixels");
      check(r.left + r.width <= acquiredW && r.top + r.height <= acquiredH,
            "logical crop must fit real source without padding");
    }
  }
  rejects([] { acquisitionAxis(0, 0.5, 300, 0, 216); }, "subpixel width");
  rejects([] { acquisitionAxis(-1, 10, 300, 0, 216); }, "negative crop");
  rejects([] { acquisitionAxis(2550, 20, 300, 0, 216); }, "past right edge");
  rejects([] { acquisitionAxis(0, 10, 0, 0, 216); }, "zero DPI");
  rejects([] { acquisitionAxis(NAN, 10, 300, 0, 216); }, "NaN crop");
  rejects([] { raster(0, 0, 100, 50, 300, 0, 0, 99, 50); }, "short acquired width");
  rejects([] { raster(0, 0, 100, 50, 300, 0, 0, 100, 49); }, "short acquired height");
}

static void testRaster()
{
  using namespace xeroxcrop;
  for (int depth : {8, 16}) {
    for (int components : {1, 3}) {
      const int sourceWidth = 41, bytesPerPixel = components * depth / 8;
      std::vector<char> source(sourceWidth * bytesPerPixel + 7, char(0xee));
      for (int x = 0; x < sourceWidth; ++x)
        for (int byte = 0; byte < bytesPerPixel; ++byte)
          source[x * bytesPerPixel + byte] = char((x * 31 + byte * 43) & 255);
      for (int left = 0; left < sourceWidth; ++left) {
        const int width = sourceWidth - left;
        std::vector<char> output;
        cropRow(source, sourceWidth, left, width, components, depth, output);
        check(output.size() == size_t(width * bytesPerPixel), "byte-mode width and depth");
        for (int x = 0; x < width; ++x)
          for (int byte = 0; byte < bytesPerPixel; ++byte)
            check((unsigned char)output[x * bytesPerPixel + byte] ==
                  ((left + x) * 31 + byte * 43) % 256,
                  "gray/RGB crop must preserve samples and channel order");
      }
    }
  }
  // Build SANE's 1=black pattern, apply the production polarity conversion,
  // and test every bit alignment with widths that do not fit whole bytes.
  for (int pattern = 0; pattern < 5; ++pattern) {
    const int sourceWidth = 83;
    const auto black = [pattern](int x) { return ((x * 7 + pattern * 3) % 11) < 5; };
    std::vector<char> source((sourceWidth + 7) / 8, 0);
    for (int x = 0; x < sourceWidth; ++x)
      if (black(x)) source[x / 8] = char((unsigned char)source[x / 8] | (0x80 >> (x % 8)));
    for (auto& byte : source) byte = char(~(unsigned char)byte);
    for (int left = 0; left < 32; ++left) {
      for (int width = 1; width < 43; ++width) {
        std::vector<char> output;
        cropRow(source, sourceWidth, left, width, 1, 1, output);
        check(output.size() == size_t((width + 7) / 8), "packed row stride rounds up");
        for (int x = 0; x < width; ++x) {
          const bool isWhite = (unsigned char)output[x / 8] & (0x80 >> (x % 8));
          check(isWhite == !black(left + x), "packed crop position and polarity");
        }
        for (int x = width; x < int(output.size()) * 8; ++x)
          check((unsigned char)output[x / 8] & (0x80 >> (x % 8)), "unused bits are white");
      }
    }
  }
  std::vector<char> input(10), output;
  rejects([&] { cropRow(input, 11, 0, 4, 1, 8, output); }, "truncated gray row");
  rejects([&] { cropRow(input, 10, 9, 2, 1, 8, output); }, "crop crosses row end");
  rejects([&] { cropRow(input, 10, 0, 4, 1, 8, input); }, "in-place aliasing");
  rejects([&] { cropRow(input, 10, 0, 4, 3, 1, output); }, "unsupported packed RGB");
}

int main()
{
  try {
    testGeometry();
    testRaster();
    std::cout << "PASS: " << checks << " coordinate/raster assertions; no device access\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "FAIL after " << checks << " assertions: " << e.what() << '\n';
    return 1;
  }
}
