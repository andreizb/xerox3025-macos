/* SPDX-License-Identifier: GPL-2.0-or-later WITH SANE-exception
 * Compile unmodified inquiry/options/window routines extracted from the
 * retained actual backend. Only dev_cmd/dev_command are replaced by a
 * local byte fixture and command recorder. No transport code is linked.
 */
#include <assert.h>
#include <ctype.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sane/sane.h>
#include <sane/saneopts.h>

#define __sane_unused__ __attribute__((unused))
#define DBG(...) ((void)0)
#define MM_PER_INCH 25.4
#include "backend-types.inc"
#include "xerox_mfp.h"

static unsigned char inquiry[70], captured[25];
static int captured_calls, passed;
static int isJPEGEnabled(struct device *dev) { return dev->compressionEnabled; }

static int dev_cmd(struct device *dev, int command)
{
  assert(command == CMD_INQUIRY);
  memcpy(dev->res, inquiry, sizeof(inquiry));
  return 1;
}

static int dev_command(struct device *dev, SANE_Byte *cmd, int response_size)
{
  (void)dev;
  assert(cmd[2] == CMD_SET_WINDOW && response_size == 32);
  memcpy(captured, cmd, sizeof(captured));
  ++captured_calls;
  return 1;
}

#include "backend-routines.inc"

static void check(int result, const char *name)
{
  if (!result) { fprintf(stderr, "FAIL: %s\n", name); exit(1); }
  ++passed;
}

static void clear(struct device *dev)
{
  free((void*)dev->sane.vendor);
  free((void*)dev->sane.model);
  free((void*)dev->sane.type);
}

int main(int argc, char **argv)
{
  if (argc != 2) return 64;
  FILE *input = fopen(argv[1], "rb");
  if (!input) return 1;
  if (fread(inquiry, 1, sizeof(inquiry), input) != sizeof(inquiry) || fgetc(input) != EOF) return 1;
  fclose(input);
  struct device dev = {0};
  check(dev_inquiry(&dev) == SANE_STATUS_GOOD, "saved device inquiry parses");
  const int expected[] = {6, 75, 100, 150, 200, 300, 600};
  check(memcmp(dev.dpi_list, expected, sizeof(expected)) == 0, "real inquiry exposes six resolutions");
  check((dev.resolutions & (1 << 11)) == 0, "real inquiry omits the upstream 1200 dpi bit");
  check(dpi_to_code(1200) == 8, "backend already knows 1200 dpi code");
  check(!dev.has_adf, "saved inquiry identifies no ADF");
  check(dev.compositions == 0x2b, "saved composition mask includes Lineart, Halftone, Gray and RGB");
  check(!strcmp(dev.opt[OPT_THRESHOLD].name, "highlight"), "backend threshold is named highlight");
  check(dev.opt[OPT_THRESHOLD].unit == SANE_UNIT_PERCENT, "threshold unit is percent");
  check(SANE_UNFIX(dev.opt[OPT_THRESHOLD].constraint.range->min) == 30 &&
        SANE_UNFIX(dev.opt[OPT_THRESHOLD].constraint.range->max) == 70 &&
        SANE_UNFIX(dev.opt[OPT_THRESHOLD].constraint.range->quant) == 10,
        "threshold descriptor is 30..70 in steps of 10");
  check(SANE_UNFIX(dev.val[OPT_THRESHOLD].w) == 50, "threshold default is 50 percent");
  for (int index = 0; index < 4; ++index) {
    dev.val[OPT_MODE].s = (SANE_String)scan_modes[index];
    dev.val[OPT_RESOLUTION].w = 300;
    check(fix_window(&dev), "mode window resolves");
    check(((dev.opt[OPT_THRESHOLD].cap & SANE_CAP_INACTIVE) == 0) == (index < 2),
          "threshold active only in Lineart and Halftone");
    check(dev_set_window(&dev), "mode command constructs");
    check(captured[0x13] == (unsigned char[]){0, 1, 3, 5}[index], "distinct native mode command code");
  }
  for (int mode = 0; mode < 2; ++mode) {
    dev.val[OPT_MODE].s = (SANE_String)scan_modes[mode];
    for (int percent = 0; percent <= 100; ++percent) {
      dev.val[OPT_THRESHOLD].w = SANE_FIX(percent);
      int clamped = percent < 30 ? 30 : percent > 70 ? 70 : percent;
      const int code = (clamped - 30) / 10;
      check(dev_set_window(&dev), "threshold window command constructs");
      check(captured[0x16] == code, "threshold byte follows five-level encoding");
      check(captured[0x13] == mode, "threshold changes keep composition distinct");
      check(SANE_UNFIX(dev.val[OPT_THRESHOLD].w) == 30 + code * 10,
            "accepted threshold records actual quantized value");
    }
  }
  clear(&dev);
  memset(&dev, 0, sizeof(dev));
  inquiry[0x24] |= 0x08; /* Local counterfactual only; never transmitted. */
  check(dev_inquiry(&dev) == SANE_STATUS_GOOD, "counterfactual inquiry parses");
  check(dev.dpi_list[0] == 7 && dev.dpi_list[7] == 1200,
        "same upstream decoder exposes 1200 when inquiry bit is present");
  clear(&dev);
  printf("{\"passed\":true,\"checks\":%d,\"captured_window_commands\":%d,"
         "\"hardware_contact\":false,\"actual_backend_routines\":true,"
         "\"physical_threshold_response\":\"unqualified\","
         "\"resolutions_from_saved_inquiry\":[75,100,150,200,300,600],"
         "\"threshold_percent\":[30,40,50,60,70],\"threshold_wire_codes\":[0,1,2,3,4]}\n",
         passed, captured_calls);
  return 0;
}
