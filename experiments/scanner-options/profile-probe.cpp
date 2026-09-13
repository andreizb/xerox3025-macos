// SPDX-License-Identifier: GPL-3.0-or-later
// Offline capability serialization probe. Compiles the complete actual
// scanner.cpp translation unit; invokes only its XML writers with fixture
// state. The linker removes acquisition code. No SANE library is linked.
#include <iostream>
#include <memory>
#include <string>
#include <map>
#include <vector>
#include <mutex>
#include <condition_variable>
#include <atomic>
#include <fstream>
#include <cstdlib>

#define private public
#include "server/scanner.h"
#undef private

#ifndef PROFILE_SOURCE
#error PROFILE_SOURCE must name the reviewed scanner.cpp
#endif
#include PROFILE_SOURCE

// Protocol constants only; do not instantiate HttpServer or a scanner session.
const char* HttpServer::MIME_TYPE_PDF = "application/pdf";
const char* HttpServer::MIME_TYPE_JPEG = "image/jpeg";
const char* HttpServer::MIME_TYPE_PNG = "image/png";

int main(int argc, char** argv)
{
  if (argc != 3) return 64;
  const std::string kind = argv[1];
  Scanner::Private state(nullptr);
  state.mMakeAndModel = "Xerox WorkCentre 3025";
  state.mDeviceInfo.name = "xerox_mfp:tcp scanner.example. 9400";
  state.mUuid = "11111111-2222-3333-4444-555555555555";
  state.mDeviceOptions.serial_number = "EXAMPLE-SERIAL";
  state.mMinResDpi = 75;
  state.mMaxResDpi = 600;
  state.mResStepDpi = 0;
  state.mDiscreteResolutions = {75, 100, 150, 200, 300, 600};
  state.mDocumentFormats = {"application/pdf", "image/jpeg", "image/png"};
  state.mTxtColorSpaces = {"grayscale", "color"};
  state.mLineartScanModeName = "Lineart";
  if (kind == "without-lineart") state.mLineartScanModeName.clear();
  else if (kind == "gray-only") state.mTxtColorSpaces = {"grayscale"};
  else if (kind == "other-model") state.mMakeAndModel = "Other Flatbed";
  else if (kind == "other-backend") state.mDeviceInfo.name = "test:device";
  else if (kind == "with-adf") {
    state.mpAdfSimplex = new Scanner::Private::InputSource(&state);
    state.mpAdfSimplex->mMinWidth = state.mpAdfSimplex->mMinHeight = 0;
    state.mpAdfSimplex->mMaxWidth = state.mpAdfSimplex->mMaxPhysicalWidth = 2551;
    state.mpAdfSimplex->mMaxHeight = state.mpAdfSimplex->mMaxPhysicalHeight = 3509;
    state.mpAdfSimplex->mMaxBits = 8;
  }
  else if (kind != "xerox") return 64;
  state.mpPlaten = new Scanner::Private::InputSource(&state);
  auto* flatbed = state.mpPlaten;
  flatbed->mMinWidth = 0;
  flatbed->mMinHeight = 0;
  flatbed->mMaxWidth = flatbed->mMaxPhysicalWidth = 2551;
  flatbed->mMaxHeight = flatbed->mMaxPhysicalHeight = 3509;
  flatbed->mMaxBits = 8;
  flatbed->mSupportedIntents = {"Preview", "TextAndGraphic", "Photo"};
  std::ofstream output(argv[2], std::ios::binary);
  if (!output) return 1;
  state.writeScannerCapabilitiesXml(output);
  return output.good() ? 0 : 1;
}
