#!/usr/bin/env python3
"""Review a minimal native AirScan association; apply/restore only explicitly.

SPDX-License-Identifier: MIT
Python is needed for this maintenance tool, never for the background scanner.
The default operation reads the queue and creates a private review directory.
"""

import argparse
import datetime
import difflib
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import stat
import subprocess
import sys
import urllib.parse
import uuid

SCANNER_KEYS = ("APScannerUUID", "APICADriver", "APScannerModulePath")
AIRSCAN = "/System/Library/Image Capture/Devices/AirScanScanner.app"
SUPPLY_TOOL = "/System/Library/Printers/Libraries/snmpInk"
PPD_LIMIT = 4 * 1024 * 1024
LOCAL_CUPS = "/private/var/run/cupsd"
ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}
# Do not let an inherited CUPS_SERVER redirect maintenance to a different host.
ENV.pop("CUPS_SERVER", None)


class ReviewError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ReviewError(message)


def run(args, timeout=30):
    result = subprocess.run([str(x) for x in args], stdin=subprocess.DEVNULL,
                            capture_output=True, env=ENV, timeout=timeout)
    require(result.returncode == 0,
            f"{Path(str(args[0])).name} failed ({result.returncode}): "
            + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def sha(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def queue_name(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,127}", value),
            "Use an existing CUPS queue ID containing only letters, digits, _ or -.")
    return value


def normal_uuid(value):
    try:
        return str(uuid.UUID(value.removeprefix("urn:uuid:")))
    except (AttributeError, ValueError) as exc:
        raise ReviewError("Invalid printer/scanner UUID.") from exc


def read_regular(path, limit=PPD_LIMIT):
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= limit,
                f"Expected a bounded regular file: {path}")
        return stream.read(limit + 1)


def ppd_values(data, key):
    # Parsing only simple scalar metadata avoids interpreting PPD program text.
    text = data.decode("latin-1")
    lines = re.findall(r"^\*" + re.escape(key) + r":([^\r\n]*)", text, re.M)
    result = []
    for raw in lines:
        value = raw.strip()
        if value.startswith('"'):
            require(len(value) >= 2 and value.endswith('"') and '"' not in value[1:-1],
                    f"Invalid scalar PPD field: {key}")
            value = value[1:-1]
        result.append(value)
    return result


def one(data, key):
    values = ppd_values(data, key)
    require(len(values) == 1, f"Expected exactly one {key} in PPD.")
    return values[0]


def derive_ppd(original, generated, toner=False):
    """Copy approved scalars only; preserve every other original byte."""
    require(original.startswith(b'*PPD-Adobe:') and generated.startswith(b'*PPD-Adobe:'),
            "Expected PPD documents.")
    require(b"*% PPD created by ipp2ppd (" in generated,
            "The source must be a PPD saved after macOS Add Printer.")
    hardware = normal_uuid(one(original, "PrinterUUID"))
    require(one(original, "APAirPrint").lower() == "true"
            and one(generated, "APAirPrint").lower() == "true",
            "Both queues must retain Apple's AirPrint configuration.")
    require(normal_uuid(one(generated, "PrinterUUID")) == hardware
            and normal_uuid(one(generated, "APScannerUUID")) == hardware,
            "Printer/scanner hardware UUIDs do not match.")
    require(one(generated, "APICADriver").lower() == "true", "ICA association is not enabled.")
    require(one(generated, "APScannerModulePath") == AIRSCAN,
            "This bridge requires macOS's actual AirScanScanner module.")
    keys = SCANNER_KEYS + (("APPrinterLowInkTool",) if toner else ())
    for key in keys:
        require(len(ppd_values(original, key)) <= 1, f"Duplicate original field: {key}")
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    replacements = {
        "APScannerUUID": f'"{one(generated, "APScannerUUID")}"',
        "APICADriver": "True",
        "APScannerModulePath": f'"{AIRSCAN}"',
    }
    if toner:
        replacements["APPrinterLowInkTool"] = f'"{SUPPLY_TOOL}"'
    output, used = [], set()
    for line in original.splitlines(keepends=True):
        match = re.match(rb"^\*([A-Za-z0-9]+):", line)
        key = match.group(1).decode() if match else None
        if key in replacements:
            output.append(f"*{key}: {replacements[key]}".encode() + newline)
            used.add(key)
        else:
            output.append(line)
    if output and not output[-1].endswith((b"\r", b"\n")):
        output[-1] += newline
    for key in keys:
        if key not in used:
            output.append(f"*{key}: {replacements[key]}".encode() + newline)
    return b"".join(output), hardware


def ppd_raw_line(data, key):
    text = data.decode("latin-1")
    found = re.findall(r"^\*" + re.escape(key) + r":[^\r\n]*", text, re.M)
    require(len(found) <= 1, f"Duplicate field: {key}")
    return found[0] if found else None


def subtract_association(current, original, keys):
    """Undo this tool's association inside the live PPD.

    Overwriting the queue with the snapshot taken at review time also reverts
    whatever macOS changed afterwards, and an OS update that regenerates the
    PPD would otherwise block rollback forever. Restore the reviewed fields to
    their original lines -- dropping those the original never carried -- and
    preserve every other byte exactly as it is now.
    """
    restore_to = {key: ppd_raw_line(original, key) for key in keys}
    newline = b"\r\n" if b"\r\n" in current else b"\n"
    output, used = [], set()
    for line in current.splitlines(keepends=True):
        match = re.match(rb"^\*([A-Za-z0-9]+):", line)
        key = match.group(1).decode() if match else None
        if key in keys:
            if restore_to.get(key) is not None and key not in used:
                output.append(restore_to[key].encode("latin-1") + newline)
                used.add(key)
            continue
        output.append(line)
    if output and not output[-1].endswith((b"\r", b"\n")):
        output[-1] += newline
    for key in keys:
        if restore_to.get(key) is not None and key not in used:
            output.append(restore_to[key].encode("latin-1") + newline)
            used.add(key)
    return b"".join(output)


def validate_system_tools(toner):
    bundle = Path(AIRSCAN)
    require(bundle.is_dir() and str(bundle.resolve()) == AIRSCAN,
            "Apple's real AirScanScanner module is absent or redirected.")
    info = plistlib.loads(read_regular(bundle / "Contents/Info.plist"))
    require(info.get("CFBundleIdentifier") == "com.apple.AirScanScanner",
            "Unexpected AirScan module identity.")
    executable = bundle / "Contents/MacOS/AirScanScanner"
    architectures = run(["/usr/bin/lipo", "-archs", executable]).decode().split()
    require(any(x in architectures for x in ("arm64", "arm64e")),
            "Apple's scanner module has no native ARM architecture.")
    run(["/usr/bin/codesign", "--verify", "--strict", bundle])
    if toner:
        require(Path(SUPPLY_TOOL).is_file() and os.access(SUPPLY_TOOL, os.X_OK),
                "Apple's supply helper is unavailable.")
        architectures = run(["/usr/bin/lipo", "-archs", SUPPLY_TOOL]).decode().split()
        require(any(x in architectures for x in ("arm64", "arm64e")),
                "Apple's supply helper has no native ARM architecture.")
        run(["/usr/bin/codesign", "--verify", "--strict", SUPPLY_TOOL])


def queue_ppd(queue):
    return Path("/etc/cups/ppd") / (queue_name(queue) + ".ppd")


def queue_snapshot(queue):
    uri = "ipp://localhost:631/printers/" + queue_name(queue)
    # The local socket read can activate an idle CUPS service before the TCP query.
    raw_options = run(["/usr/bin/lpoptions", "-h", LOCAL_CUPS, "-p", queue]).decode()
    report = plistlib.loads(run([
        "/usr/bin/ipptool", "-T", "10", "-X", uri,
        "/usr/share/cups/ipptool/get-printer-attributes.test"]))
    tests = report.get("Tests", [])
    require(len(tests) == 1 and tests[0].get("Successful") is True,
            "Could not obtain a complete live queue snapshot.")
    attrs = {}
    for group in tests[0]["ResponseAttributes"]:
        attrs.update(group)
    for name in ("printer-name", "printer-uuid", "device-uri"):
        require(isinstance(attrs.get(name), str), f"Queue does not expose {name}.")
    require(attrs["printer-name"].lower() == queue.lower(), "Unexpected local queue identity.")
    # Retain effective print options, excluding volatile status supplied alongside them.
    options = {}
    for item in shlex.split(raw_options):
        key, _, value = item.partition("=")
        if not key.startswith(("printer-", "marker-")) and key != "device-uri":
            options[key] = value
    stable_names = {
        "printer-name", "printer-uuid", "device-uri", "printer-info", "printer-location",
        "printer-make-and-model", "printer-is-shared", "printer-is-accepting-jobs",
        "printer-error-policy", "printer-op-policy", "job-k-limit", "job-page-limit",
        "job-quota-period", "requesting-user-name-allowed", "requesting-user-name-denied",
    }
    stable = {key: value for key, value in attrs.items()
              if key in stable_names or key.endswith("-default")}
    default = run(["/usr/bin/lpstat", "-h", LOCAL_CUPS, "-d"]).decode().strip()
    local_options = Path.home() / ".cups/lpoptions"
    user_hash = sha(read_regular(local_options)) if local_options.exists() else None
    return {"settings": stable, "effective_options": options, "default_destination": default,
            "user_lpoptions_sha256": user_hash, "printer_state": attrs.get("printer-state")}


def check_identity(snapshot, hardware):
    uri = urllib.parse.urlsplit(snapshot["settings"]["device-uri"])
    # Existing Bonjour identity is required. No guessed IP address or endpoint.
    require(uri.scheme == "dnssd", "This tool requires the existing Bonjour AirPrint queue.")
    ids = urllib.parse.parse_qs(uri.query).get("uuid", [])
    require(len(ids) == 1 and normal_uuid(ids[0]) == hardware,
            "The queue's Bonjour hardware UUID differs from the PPD association.")


def stable_snapshot(snapshot):
    return {key: value for key, value in snapshot.items() if key != "printer_state"}


def guard(current_ppd, expected_hash, current, expected):
    require(sha(current_ppd) == expected_hash,
            "Queue PPD changed since review. Refusing to overwrite it; prepare a fresh review.")
    require(stable_snapshot(current) == stable_snapshot(expected),
            "Queue identity, defaults or user options changed. Prepare a fresh review.")
    require(current.get("printer_state") != 4, "Printer is processing a job; try again when idle.")


def guard_restore(current_ppd, candidate_ppd, keys, current, expected):
    # macOS rewrites this PPD on OS updates, so a whole-file hash stops
    # matching through no fault of the association. What must still hold is
    # that the reviewed fields are exactly the ones this tool wrote; then
    # removing them is safe and every unrelated later edit survives.
    for key in keys:
        require(ppd_values(current_ppd, key) == ppd_values(candidate_ppd, key),
                f"Field {key} was changed after association. Refusing to restore.")
    # printer-uuid is CUPS's own object id and is reissued whenever macOS
    # recreates the queue, which an OS update does on its own. The stable
    # identity is the queue name together with the Bonjour device-uri, and that
    # uri carries the hardware UUID this association was checked against.
    identity = ("printer-name", "device-uri")
    require(all(current["settings"].get(key) == expected["settings"].get(key)
                for key in identity),
            "Queue identity changed after association. Refusing to restore another queue.")
    require(current.get("printer_state") != 4, "Printer is processing a job; try again when idle.")


def private_write(path, data):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(data)


def write_manifest(directory, manifest):
    temp = directory / ".manifest-new.json"
    private_write(temp, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    os.replace(temp, directory / "manifest.json")


def verify_private_dir(directory):
    info = directory.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_mode & 0o077 == 0,
            "Review directory must be owned by this user and private (mode 0700).")


def prepare(args):
    queue = queue_name(args.queue)
    original = read_regular(queue_ppd(queue))
    generated = read_regular(args.generated_ppd)
    candidate, hardware = derive_ppd(original, generated, args.with_toner_hook)
    validate_system_tools(args.with_toner_hook)
    snapshot = queue_snapshot(queue)
    check_identity(snapshot, hardware)
    require(sha(read_regular(queue_ppd(queue))) == sha(original),
            "Queue PPD changed while preparing review; retry.")
    require(candidate != original, "This exact association is already present; nothing to apply.")
    directory = args.output.absolute()
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    verify_private_dir(directory)
    private_write(directory / "original.ppd", original)
    private_write(directory / "apple-generated.ppd", generated)
    private_write(directory / "candidate.ppd", candidate)
    diff = "".join(difflib.unified_diff(original.decode("latin-1").splitlines(True),
                                     candidate.decode("latin-1").splitlines(True),
                                     fromfile="original.ppd", tofile="candidate.ppd"))
    private_write(directory / "changes.patch", diff.encode("latin-1"))
    validation = run(["/usr/bin/cupstestppd", "-v", directory / "candidate.ppd"])
    private_write(directory / "ppd-validation.txt", validation)
    manifest = {"format": 1, "status": "reviewed", "created_at_utc": now(),
                "review_user_uid": os.geteuid(), "queue": queue, "hardware_uuid": hardware,
                "toner_hook": args.with_toner_hook, "before": snapshot,
                "original_sha256": sha(original), "candidate_sha256": sha(candidate),
                "generated_sha256": sha(generated)}
    write_manifest(directory, manifest)
    print(f"Review prepared: {directory}\nNo queue changes made. Inspect changes.patch before --apply.")


def load_plan(directory):
    directory = directory.absolute()
    verify_private_dir(directory)
    manifest = json.loads(read_regular(directory / "manifest.json"))
    require(manifest.get("format") == 1 and manifest.get("review_user_uid") == os.geteuid(),
            "Unsupported review format or different maintenance user.")
    require(isinstance(manifest.get("toner_hook"), bool), "Invalid supply-hook review value.")
    queue_name(manifest["queue"])
    original = read_regular(directory / "original.ppd")
    generated = read_regular(directory / "apple-generated.ppd")
    candidate = read_regular(directory / "candidate.ppd")
    require(sha(original) == manifest["original_sha256"]
            and sha(generated) == manifest["generated_sha256"]
            and sha(candidate) == manifest["candidate_sha256"], "Review files changed after preparation.")
    derived, hardware = derive_ppd(original, generated, manifest["toner_hook"])
    require(derived == candidate and hardware == manifest["hardware_uuid"],
            "Candidate contains changes outside the reviewed scanner/supply fields.")
    check_identity(manifest["before"], hardware)
    return directory, manifest, original, candidate


def mutate(directory, restore=False):
    directory, manifest, original, candidate = load_plan(directory)
    queue = manifest["queue"]
    keys = SCANNER_KEYS + (("APPrinterLowInkTool",) if manifest["toner_hook"] else ())
    current_ppd = read_regular(queue_ppd(queue))
    if restore:
        require(manifest["status"] in ("applied", "needs-review"),
                "There is no recorded applied change to restore.")
        expected = manifest.get("after")
        require(expected is not None, "Post-apply settings were not captured; manual review is required.")
        expected_hash, target = None, subtract_association(current_ppd, original, keys)
    else:
        require(manifest["status"] == "reviewed" and not manifest.get("pending_operation"),
                "This review was already applied, restored, or has an uncertain pending operation.")
        expected, expected_hash, target = manifest["before"], manifest["original_sha256"], candidate
        validate_system_tools(manifest["toner_hook"])
    current = queue_snapshot(queue)
    if restore:
        guard_restore(current_ppd, candidate, keys, current, expected)
    else:
        guard(current_ppd, expected_hash, current, expected)
    # No active or queued jobs may be present at the checked instant.
    jobs = run(["/usr/bin/lpstat", "-h", LOCAL_CUPS, "-o", queue]).strip()
    require(not jobs, "The queue has unfinished jobs; try again after they finish.")
    filename = "rollback.ppd" if restore else "candidate.ppd"
    if restore:
        # The rollback is derived from the live queue, so it is written out for
        # inspection and retained with the rest of the review.
        rollback_path = directory / filename
        if rollback_path.exists():
            rollback_path.unlink()
        private_write(rollback_path, target)
    # Validate immediately before the sole mutating command. No -v, -d, -E or -x.
    run(["/usr/bin/cupstestppd", directory / filename])
    # Restore accepts preferences changed since installation, then requires
    # that exact current state to remain stable across this one operation.
    require(sha(read_regular(queue_ppd(queue))) == sha(current_ppd),
            "Queue PPD changed while preparing this operation; nothing was written.")
    require(stable_snapshot(queue_snapshot(queue)) == stable_snapshot(current),
            "Queue identity, defaults or user options changed; nothing was written.")
    manifest["pending_operation"] = "restore" if restore else "apply"
    manifest["last_attempt_at_utc"] = now()
    write_manifest(directory, manifest)
    error = None
    try:
        # macOS authenticates the local user through its CUPS Unix socket.
        # TCP localhost can reject that same authorized local administration.
        run(["/usr/sbin/lpadmin", "-h", LOCAL_CUPS, "-p", queue,
             "-P", directory / filename])
    except (ReviewError, subprocess.TimeoutExpired) as exc:
        error = str(exc)
    # Record actual state even after an uncertain command result. Never retry a write blindly.
    manifest["last_operation"] = "restore" if restore else "apply"
    manifest["last_command_error"] = error
    try:
        after = queue_snapshot(queue)
        actual_hash = sha(read_regular(queue_ppd(queue)))
    except (ReviewError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        manifest["status"] = "needs-review"
        manifest["postcheck_error"] = str(exc)
        if not restore:
            manifest["after"] = None
        write_manifest(directory, manifest)
        raise ReviewError("Could not verify CUPS after the command; pending operation recorded. "
                          "Inspect the retained review before further queue changes.") from exc
    manifest["last_actual_ppd_sha256"] = actual_hash
    unchanged = stable_snapshot(after) == stable_snapshot(current)
    matched = actual_hash == sha(target)
    if not restore:
        manifest["after"] = after
    manifest["status"] = (("restored" if restore else "applied")
                          if matched and unchanged else "needs-review")
    if not matched and unchanged and actual_hash == expected_hash:
        # A rejected operation with demonstrably unchanged state is safe to retry.
        manifest["status"] = "applied" if restore else "reviewed"
    manifest.pop("pending_operation", None)
    write_manifest(directory, manifest)
    require(matched and unchanged,
            "CUPS did not preserve the exact reviewed PPD/settings. Evidence retained; do not retry blindly.")
    print(("Restored" if restore else "Applied") +
          " the exact PPD; queue identity, printing defaults and default destination are unchanged.")
    if not restore:
        print("Native Open Scanner and Supply Levels still require UI/physical acceptance.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", type=Path, metavar="REVIEW_DIRECTORY")
    mode.add_argument("--restore", type=Path, metavar="REVIEW_DIRECTORY")
    parser.add_argument("--queue", help="existing CUPS queue ID; never creates a queue")
    parser.add_argument("--generated-ppd", type=Path, help="PPD saved after native Add Printer")
    parser.add_argument("--output", type=Path, help="new private review directory (parent must exist)")
    parser.add_argument("--with-toner-hook", action="store_true",
                        help="also select Apple's snmpInk; use only after native toner acceptance")
    args = parser.parse_args(argv)
    if args.apply or args.restore:
        require(not any((args.queue, args.generated_ppd, args.output, args.with_toner_hook)),
                "Apply/restore takes only a previously prepared review directory.")
        mutate(args.restore or args.apply, restore=bool(args.restore))
    else:
        require(all((args.queue, args.generated_ppd, args.output)),
                "Review requires --queue, --generated-ppd and --output.")
        prepare(args)
    print("Compatibility: lpadmin -P is available on this Mac but deprecated upstream; future macOS needs retesting.")


if __name__ == "__main__":
    try:
        main()
    except (ReviewError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"Queue association stopped: {exc}", file=sys.stderr)
        sys.exit(1)
