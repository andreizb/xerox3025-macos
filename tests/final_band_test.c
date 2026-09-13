/* SPDX-License-Identifier: GPL-2.0-or-later WITH SANE-exception
 * Exercise the actual built backend's sane_read with a synthetic final band.
 * No device connection and no scanner reservation are made.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <sane/sane.h>
#define BACKEND_NAME final_band_test
#include <sane/sanei_backend.h>
#include "xerox_mfp.h"

typedef SANE_Status (*read_fn)(SANE_Handle, SANE_Byte *, SANE_Int, SANE_Int *);

static int check(read_fn read_backend, int mode, int chunk, int wrap) {
    struct device *dev = calloc(1, sizeof(*dev));
    if (!dev) return 1;
    dev->data = calloc(1, DATASIZE);
    if (!dev->data) { free(dev); return 1; }
    const int stride = 8, width = 5, rows = 7, prior_rows = 10;
    dev->scanning = 1;
    dev->final_block = 1;
    dev->composition = mode;
    dev->vertical = rows;
    dev->horizontal = stride;
    dev->bytes_per_line = stride;
    dev->para.bytes_per_line = width;
    dev->para.pixels_per_line = mode == MODE_LINEART ? width * 8 : width;
    dev->para.depth = mode == MODE_LINEART ? 1 : 8;
    dev->para.format = SANE_FRAME_GRAY;
    dev->para.lines = prior_rows + rows;
    dev->y_off = prior_rows;
    dev->total_img_size = dev->para.lines * width;
    dev->total_out_size = prior_rows * width;
    dev->datalen = stride * rows;
    dev->dataoff = wrap ? DATASIZE - 3 : 0;
    unsigned char expected[35], output[80];
    for (int y = 0; y < rows; ++y) {
        for (int x = 0; x < stride; ++x) {
            unsigned char value = x < width ? (13 + y * 17 + x) : 250;
            dev->data[(dev->dataoff + y * stride + x) & DATAMASK] = value;
            if (x < width) expected[y * width + x] = value;
        }
    }
    int total = 0, failed = 0, eof = 0;
    for (int calls = 0; calls < 100 && !eof; ++calls) {
        unsigned char block[64];
        SANE_Int count = -1;
        SANE_Status status = read_backend(dev, block, chunk, &count);
        if (count < 0 || count > chunk || total + count > (int)sizeof(output)) {
            failed = 1; break;
        }
        memcpy(output + total, block, count); total += count;
        if (status == SANE_STATUS_EOF) eof = 1;
        else if (status != SANE_STATUS_GOOD) { failed = 1; break; }
    }
    if (!eof || total != (int)sizeof(expected) || memcmp(output, expected, sizeof(expected))) failed = 1;
    printf("%s mode=%s chunk=%d wrapped=%d bytes=%d expected=%zu\n",
           failed ? "FAIL" : "PASS", mode == MODE_LINEART ? "lineart" : "gray",
           chunk, wrap, total, sizeof(expected));
    free(dev->data); free(dev);
    return failed;
}

int main(int argc, char **argv) {
    if (argc != 2) return 64;
    void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    read_fn read_backend = (read_fn)dlsym(library, "sane_xerox_mfp_read");
    if (!read_backend) return 1;
    int failures = 0;
    const int chunks[] = {1, 5, 13};
    for (int mode = 0; mode < 2; ++mode)
        for (int wrap = 0; wrap < 2; ++wrap)
            for (unsigned i = 0; i < sizeof(chunks) / sizeof(chunks[0]); ++i)
                failures += check(read_backend, mode ? MODE_LINEART : MODE_GRAY8, chunks[i], wrap);
    dlclose(library);
    return failures ? 1 : 0;
}
