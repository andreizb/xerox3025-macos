/* SPDX-License-Identifier: GPL-2.0-or-later WITH SANE-exception
 * Compile the actual backend, replacing only its clock/sleep and transport.
 * Exercise the public SANE start/read/cancel entry points without hardware.
 */
#include <time.h>
#include <unistd.h>
static int busy_clock_gettime(clockid_t, struct timespec *);
static int busy_usleep(useconds_t);
#define clock_gettime busy_clock_gettime
#define usleep busy_usleep
#ifndef XEROX_MFP_SOURCE
#define XEROX_MFP_SOURCE "../upstream/sane-backends/backend/xerox_mfp.c"
#endif
#include XEROX_MFP_SOURCE
#undef clock_gettime
#undef usleep

struct fixture {
    int64_t now_ms, phase_start;
    int target, previous, calls[256], cleanup[2], cleanup_failure;
    int cancel_on_busy, clock_calls, fail_clock_at, bad_clock;
    int finite_busy_ms, response_ms, stopped_by_guard;
};
static struct fixture f;

static int busy_clock_gettime(clockid_t clock_id, struct timespec *value)
{
    if (clock_id != CLOCK_MONOTONIC) f.bad_clock = 1;
    if (++f.clock_calls == f.fail_clock_at) { errno = EIO; return -1; }
    value->tv_sec = f.now_ms / 1000;
    value->tv_nsec = (f.now_ms % 1000) * 1000000;
    return 0;
}

static int busy_usleep(useconds_t delay)
{
    f.now_ms += delay / 1000;
    return 0;
}

static int fake_request(struct device *dev, SANE_Byte *cmd, size_t cmdlen,
                        SANE_Byte *reply, size_t *size)
{
    if (!cmd || cmdlen < 4 || !reply || *size < 32) abort();
    const int operation = cmd[2];
    ++f.calls[operation];
    if (operation == CMD_ABORT || operation == CMD_RELEASE_UNIT) {
        ++f.cleanup[operation == CMD_RELEASE_UNIT];
        if (f.cleanup_failure) return SANE_STATUS_IO_ERROR;
    }
    if (operation != f.previous) {
        f.phase_start = f.now_ms;
        f.previous = operation;
    }
    /* Fail a pre-fix infinite loop promptly in virtual time. This guard is
     * independent of the production timeout and must never fire after fixing. */
    if (f.now_ms - f.phase_start > 120000) {
        f.stopped_by_guard = 1;
        return SANE_STATUS_IO_ERROR;
    }
    memset(reply, 0, 32);
    *size = 32;
    reply[0] = RES_CODE;
    reply[2] = 29;
    const int waited_command = operation == CMD_RESERVE_UNIT ||
        operation == CMD_OBJECT_POSITION || operation == CMD_READ;
    const int selected = operation == f.target || (f.target == -1 && waited_command);
    if (selected && (!f.finite_busy_ms || f.now_ms - f.phase_start < f.finite_busy_ms)) {
        reply[1] = STATUS_BUSY;
        f.now_ms += f.response_ms;
        if (f.cancel_on_busy) sane_cancel(dev);
    } else if (operation == CMD_READ) {
        reply[3] = MSG_END_BLOCK;
        reply[7] = 24;
        reply[9] = 2;
        reply[11] = 4;
    }
    return SANE_STATUS_GOOD;
}

/* Linking a fake transport makes accidental network or USB acquisition fail
 * immediately, rather than using a configured real scanner in this test. */
#define TRANSPORT_STUBS(name) \
int name##_dev_request(struct device *d, SANE_Byte *c, size_t n, SANE_Byte *r, size_t *s) \
    { (void)d; (void)c; (void)n; (void)r; (void)s; abort(); } \
SANE_Status name##_dev_open(struct device *d) { (void)d; abort(); } \
void name##_dev_close(struct device *d) { (void)d; abort(); } \
SANE_Status name##_configure_device(const char *n, SANE_Status (*cb)(SANE_String_Const)) \
    { (void)n; (void)cb; abort(); }
TRANSPORT_STUBS(usb)
TRANSPORT_STUBS(tcp)
static transport fake_io = { "fake", fake_request, NULL, NULL, NULL };

static struct device *new_device(void)
{
    memset(&f, 0, sizeof(f));
    struct device *dev = calloc(1, sizeof(*dev));
    if (!dev) abort();
    dev->io = &fake_io;
    dev->sane.model = "WorkCentre 3025";
    dev->max_len_fb = 14000;
    dev->win_x_range.max = SANE_FIX(216);
    dev->win_y_range.max = SANE_FIX(297);
    dev->val[OPT_RESOLUTION].w = 300;
    dev->val[OPT_MODE].s = SANE_VALUE_SCAN_MODE_GRAY;
    dev->val[OPT_SOURCE].s = "Flatbed";
    dev->val[OPT_THRESHOLD].w = SANE_FIX(50);
    dev->val[OPT_SCAN_BR_X].w = SANE_FIX(10);
    dev->val[OPT_SCAN_BR_Y].w = SANE_FIX(10);
    for (int i = OPT_SCAN_TL_X; i <= OPT_SCAN_BR_Y; ++i)
        dev->opt[i].constraint.range = (i - OPT_SCAN_TL_X) % 2 ?
            &dev->win_y_range : &dev->win_x_range;
    return dev;
}

static void free_device(struct device *dev)
{
    if (dev->jpeg_file) fclose(dev->jpeg_file);
    free(dev->data);
    free(dev->decData);
    free(dev);
}

static int report(const char *name, int okay, SANE_Status status)
{
    okay = okay && !f.bad_clock && !f.stopped_by_guard;
    printf("%s %s: status=%d elapsed_ms=%lld reserve=%d position=%d read=%d abort=%d release=%d\n",
        okay ? "PASS" : "FAIL", name, status, (long long)f.now_ms,
        f.calls[CMD_RESERVE_UNIT], f.calls[CMD_OBJECT_POSITION], f.calls[CMD_READ],
        f.cleanup[0], f.cleanup[1]);
    return okay ? 0 : 1;
}

static int timeout_start(const char *name, int target, int cleanup_failure)
{
    struct device *dev = new_device();
    f.target = target;
    f.cleanup_failure = cleanup_failure;
    const int owned = target != CMD_RESERVE_UNIT;
    SANE_Status status = sane_start(dev);
    int result = report(name, status == SANE_STATUS_DEVICE_BUSY &&
        dev->state == SANE_STATUS_DEVICE_BUSY && !dev->reserved && !dev->scanning &&
        f.now_ms == 60000 && f.cleanup[0] == owned && f.cleanup[1] == owned, status);
    free_device(dev);
    return result;
}

static int timeout_read_and_retry(void)
{
    struct device *dev = new_device();
    f.target = CMD_READ;
    dev->reserved = dev->scanning = 1;
    dev->composition = MODE_GRAY8;
    dev->jpeg_file = tmpfile();
    if (!dev->jpeg_file) abort();
    unsigned char pixel;
    SANE_Int count = -1;
    SANE_Status status = sane_read(dev, &pixel, 1, &count);
    int result = report("read timeout releases own session and tempfile", count == 0 &&
        status == SANE_STATUS_DEVICE_BUSY && dev->state == SANE_STATUS_DEVICE_BUSY &&
        !dev->reserved && !dev->scanning && !dev->jpeg_file &&
        f.now_ms == 60000 && f.cleanup[0] == 1 && f.cleanup[1] == 1, status);
    f.target = 0;
    status = sane_start(dev);
    result += report("same handle starts after timeout", status == SANE_STATUS_GOOD &&
        dev->reserved && dev->scanning && f.calls[CMD_RESERVE_UNIT] == 1 &&
        f.cleanup[0] == 1 && f.cleanup[1] == 1, status);
    free_device(dev);
    return result;
}

static int cancelled_start(int owned)
{
    struct device *dev = new_device();
    f.target = owned ? CMD_OBJECT_POSITION : CMD_RESERVE_UNIT;
    f.cancel_on_busy = 1;
    SANE_Status status = sane_start(dev);
    int result = report(owned ? "cancel own reservation before scanning" : "cancel leaves other owner alone",
        status == SANE_STATUS_CANCELLED && dev->state == SANE_STATUS_CANCELLED &&
        !dev->reserved && !dev->scanning && f.cleanup[0] == owned && f.cleanup[1] == owned &&
        f.now_ms < 1000, status);
    free_device(dev);
    return result;
}

static int finite_busy(void)
{
    struct device *dev = new_device();
    f.target = -1;
    f.finite_busy_ms = 45000;
    SANE_Status status = sane_start(dev);
    int result = report("each command receives its own BUSY budget", status == SANE_STATUS_GOOD &&
        dev->reserved && dev->scanning && f.now_ms >= 135000 && f.now_ms < 138000 &&
        !f.cleanup[0] && !f.cleanup[1], status);
    free_device(dev);
    return result;
}

static int clock_failure(int owned, int fail_at)
{
    struct device *dev = new_device();
    dev->reserved = owned;
    f.target = owned ? CMD_OBJECT_POSITION : CMD_RESERVE_UNIT;
    f.fail_clock_at = fail_at;
    SANE_Status status = sane_start(dev);
    int result = report(owned ? "clock failure cleans own reservation" : "clock failure leaves other owner alone",
        status == SANE_STATUS_IO_ERROR && dev->state == SANE_STATUS_IO_ERROR &&
        !dev->reserved && !dev->scanning && f.cleanup[0] == owned && f.cleanup[1] == owned, status);
    free_device(dev);
    return result;
}

static int in_flight_deadline(void)
{
    struct device *dev = new_device();
    f.target = CMD_RESERVE_UNIT;
    f.response_ms = 15000;
    SANE_Status status = sane_start(dev);
    int result = report("BUSY reply arriving past deadline cannot retry", status == SANE_STATUS_DEVICE_BUSY &&
        f.now_ms >= 60000 && f.now_ms < 75000 && f.calls[CMD_RESERVE_UNIT] == 4 &&
        !f.cleanup[0] && !f.cleanup[1], status);
    free_device(dev);
    return result;
}

int main(void)
{
    int failures = 0;
    failures += timeout_start("reservation timeout leaves other owner alone", CMD_RESERVE_UNIT, 0);
    failures += timeout_start("position timeout releases own reservation", CMD_OBJECT_POSITION, 0);
    failures += timeout_start("initial image timeout releases own reservation", CMD_READ, 0);
    failures += timeout_start("failed cleanup preserves timeout status", CMD_READ, 1);
    failures += timeout_read_and_retry();
    failures += cancelled_start(0);
    failures += cancelled_start(1);
    failures += finite_busy();
    failures += clock_failure(0, 1);
    failures += clock_failure(1, 1);
    failures += clock_failure(1, 3);
    failures += in_flight_deadline();
    return failures ? 1 : 0;
}
