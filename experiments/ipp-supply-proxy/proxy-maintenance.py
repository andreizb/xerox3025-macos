#!/usr/bin/env python3
"""Review, install or remove the optional native IPP supply proxy.

SPDX-License-Identifier: MIT
Maintenance only; the background service uses Go and native Bonjour discovery.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
import types
import urllib.parse

LABEL = 'local.xerox3025.supply-proxy'
DIRECTORY = 'Xerox3025SupplyProxy'
PROXY_URI = 'ipp://127.0.0.1:18326/ipp/print'
LOCAL_CUPS = '/private/var/run/cupsd'
HERE = Path(__file__).resolve().parent


def load_core():
    path = HERE / 'associate-queue.py'
    if not path.is_file():
        path = HERE.parents[1] / 'scripts/associate-queue.py'
    module = types.ModuleType('proxy_association_core')
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


core = load_core()
require = core.require


class StartupError(core.ReviewError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def write_json(path, data):
    temporary = path.with_name('.' + path.name + '.next')
    core.private_write(temporary, (json.dumps(data, indent=2, sort_keys=True) + '\n').encode())
    os.replace(temporary, path)


def validate_native_python():
    require(sys.version_info >= (3, 9) and platform.machine() == 'arm64',
            'Maintenance requires native ARM64 Python 3.9+. No changes made.')


def prepare_review(queue, hardware, destination):
    queue = core.queue_name(queue)
    hardware = core.normal_uuid(hardware)
    ppd = core.read_regular(core.queue_ppd(queue))
    require(core.one(ppd, 'APAirPrint').lower() == 'true', 'The queue must retain AirPrint.')
    require(core.normal_uuid(core.one(ppd, 'PrinterUUID')) == hardware, 'Wrong printer hardware.')
    before = core.queue_snapshot(queue)
    core.check_identity(before, hardware)
    idle(queue)
    core.guard(core.read_regular(core.queue_ppd(queue)), core.sha(ppd), core.queue_snapshot(queue), before)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    core.verify_private_dir(destination)
    core.private_write(destination / 'original.ppd', ppd)
    write_json(destination / 'manifest.json', {
        'format': 1, 'kind': LABEL, 'status': 'reviewed', 'created_at_utc': core.now(),
        'review_user_uid': os.geteuid(), 'queue': queue, 'hardware_uuid': hardware,
        'before': before, 'original_ppd_sha256': core.sha(ppd), 'proxy_uri': PROXY_URI,
    })
    print('Review prepared. It changes only the queue device URI; printing will depend on the proxy.')
    print(destination)


def load_review(directory):
    directory = directory.absolute()
    core.verify_private_dir(directory)
    manifest = json.loads(core.read_regular(directory / 'manifest.json'))
    require(manifest.get('format') == 1 and manifest.get('kind') == LABEL
            and manifest.get('review_user_uid') == os.geteuid(), 'Wrong review identity or owner.')
    core.queue_name(manifest['queue'])
    require(manifest.get('proxy_uri') == PROXY_URI, 'Unrecognized proxy destination.')
    require(core.sha(core.read_regular(directory / 'original.ppd')) == manifest['original_ppd_sha256'],
            'Original PPD review evidence changed.')
    core.check_identity(manifest['before'], manifest['hardware_uuid'])
    return directory, manifest


def idle(queue):
    require(not core.run(['/usr/bin/lpstat', '-h', LOCAL_CUPS, '-o', queue]).strip(),
            'The queue has unfinished jobs. Wait for them to finish; nothing changed.')


def with_uri(snapshot, uri):
    expected = copy.deepcopy(snapshot)
    expected['settings']['device-uri'] = uri
    return expected


def mutate_uri(directory, restore=False):
    directory, manifest = load_review(directory)
    require(not manifest.get('pending_operation'), 'An uncertain prior write needs review; rollback retained.')
    queue = manifest['queue']
    current = core.queue_snapshot(queue)
    current_ppd = core.read_regular(core.queue_ppd(queue))
    if restore:
        require(manifest['status'] in ('applied', 'needs-review'), 'No applied proxy URI to restore.')
        require(current['settings']['printer-uuid'] == manifest['before']['settings']['printer-uuid'],
                'Queue UUID changed. Refusing to restore another queue.')
        require(current['settings']['device-uri'] == PROXY_URI,
                'Queue URI changed after installation. Working service and rollback retained for review.')
        target = manifest['before']['settings']['device-uri']
    else:
        require(manifest['status'] == 'reviewed', 'Review already used; prepare a fresh one.')
        core.guard(current_ppd, manifest['original_ppd_sha256'], current, manifest['before'])
        target = PROXY_URI
    require(core.one(current_ppd, 'APAirPrint').lower() == 'true', 'AirPrint configuration changed.')
    require(current.get('printer_state') != 4, 'Printer is processing a job.')
    idle(queue)
    core.guard(core.read_regular(core.queue_ppd(queue)), core.sha(current_ppd), core.queue_snapshot(queue), current)
    manifest['pending_operation'] = 'restore' if restore else 'apply'
    manifest['last_attempt_at_utc'] = core.now()
    write_json(directory / 'manifest.json', manifest)
    command_error = None
    try:
        core.run(['/usr/sbin/lpadmin', '-h', LOCAL_CUPS, '-p', queue, '-v', target])
    except (core.ReviewError, subprocess.TimeoutExpired) as error:
        command_error = str(error)
    manifest['last_command_error'] = command_error
    try:
        after = core.queue_snapshot(queue)
        ppd_after = core.sha(core.read_regular(core.queue_ppd(queue)))
    except (core.ReviewError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        manifest['status'] = 'needs-review'
        manifest['postcheck_error'] = str(error)
        write_json(directory / 'manifest.json', manifest)
        raise core.ReviewError('Cannot verify the URI write. Running service and private rollback retained.') from error
    expected = with_uri(current, target)
    changed_exactly = (core.stable_snapshot(after) == core.stable_snapshot(expected)
                       and ppd_after == core.sha(current_ppd))
    unchanged = (core.stable_snapshot(after) == core.stable_snapshot(current)
                 and ppd_after == core.sha(current_ppd))
    manifest['last_actual'] = after
    manifest['last_ppd_sha256'] = ppd_after
    if changed_exactly:
        manifest['status'] = 'restored' if restore else 'applied'
    elif unchanged:
        manifest['status'] = 'applied' if restore else 'reviewed'
    else:
        manifest['status'] = 'needs-review'
    manifest.pop('pending_operation', None)
    write_json(directory / 'manifest.json', manifest)
    require(changed_exactly, 'The exact URI change did not verify. State recorded; do not retry blindly.')
    print('Restored direct Bonjour URI.' if restore else 'Applied the reviewed loopback URI.')
    print('Queue UUID, AirPrint PPD, current preferences and defaults are unchanged.')


def verify_tree(directory, manifest_path):
    expected = json.loads(core.read_regular(manifest_path))
    actual = {}
    require(isinstance(expected, dict) and expected, 'Missing package integrity manifest.')
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(), 'Package/install tree contains a symlink.')
        if path.is_file():
            actual[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
    require(actual == expected, 'Package or maintenance contents changed; nothing removed.')


def paths(library):
    return library / 'Application Support' / DIRECTORY, library / 'LaunchAgents' / (LABEL + '.plist')


def command(argv, timeout=40):
    return core.run(argv, timeout=timeout)


def registered():
    result = subprocess.run(['/bin/launchctl', 'print', f'gui/{os.geteuid()}/{LABEL}'],
                            capture_output=True, timeout=10)
    return result.returncode == 0


def queue_uris():
    text = core.run(['/usr/bin/lpstat', '-h', LOCAL_CUPS, '-v']).decode()
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r'device for ([A-Za-z0-9_-]+): (.+)', line)
        require(match is not None, 'Could not verify all queue destinations.')
        result[match[1]] = match[2]
    return result


def no_remaining_proxy_queues():
    def points_here(uri):
        parsed = urllib.parse.urlsplit(uri)
        return parsed.hostname in ('127.0.0.1', 'localhost') and parsed.port == 18326
    require(not any(points_here(uri) for uri in queue_uris().values()),
            'A queue still points at this proxy. Service and rollback retained.')


def verify_proxy(hardware):
    args = ['/usr/bin/ipptool', '-T', '30', '-X', PROXY_URI,
            '/usr/share/cups/ipptool/get-printer-attributes.test']
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                            env=core.ENV, timeout=35)
    if result.returncode:
        raise StartupError('Read-only IPP startup verification failed; the queue URI was not changed.', {
            'phase': 'identity-and-supply-query', 'exit': result.returncode,
            'stdout': result.stdout[:65536].decode('utf-8', 'replace'),
            'stderr': result.stderr[:8192].decode('utf-8', 'replace'),
        })
    report = plistlib.loads(result.stdout)
    tests = report.get('Tests', [])
    require(len(tests) == 1 and tests[0].get('Successful') is True, 'Proxy IPP query did not pass.')
    attrs = {}
    for group in tests[0]['ResponseAttributes']:
        attrs.update(group)
    require(core.normal_uuid(attrs.get('printer-uuid')) == hardware
            and attrs.get('printer-make-and-model') == 'Xerox WorkCentre 3025',
            'Proxy did not return the reviewed physical printer identity.')
    require(attrs.get('marker-colors') == '#000000'
            and attrs.get('marker-types') in ('toner', 'toner-cartridge')
            and isinstance(attrs.get('marker-names'), str)
            and attrs['marker-names'].startswith('Black Toner')
            and isinstance(attrs.get('marker-levels'), int)
            and -3 <= attrs['marker-levels'] <= 100, 'Expected live black-toner metadata is unavailable.')
    return {'hardware_uuid': hardware, 'model': attrs['printer-make-and-model'],
            'marker_color': attrs['marker-colors'], 'marker_level': attrs['marker-levels']}


def wait_for_proxy(hardware, readiness_seconds=20):
    """Allow cold launch/signature evaluation before the real printer query.

    The health response proves only that this process has opened its listener;
    the actual IPP identity/supply verification remains a separate required gate.
    """
    start = time.monotonic()
    deadline = start + readiness_seconds
    last = None
    while time.monotonic() < deadline:
        result = subprocess.run(['/usr/bin/curl', '--noproxy', '*', '--silent', '--show-error',
                                 '--fail', '--max-time', '1', '--max-filesize', '4096',
                                 'http://127.0.0.1:18326/healthz'], stdin=subprocess.DEVNULL,
                                capture_output=True, env=core.ENV, timeout=3)
        expected = b'process running; printer availability is checked on each request\n'
        if result.returncode == 0 and result.stdout == expected:
            # An initial metadata exchange can fail transiently even after this
            # process is listening. Only these read-only GPA
            # transport failures are retried; wrong identity/data fails at once.
            failed_queries = []
            query_start = time.monotonic()
            for attempt in range(3):
                try:
                    verified = verify_proxy(hardware)
                    return {'passed': True, 'verified': verified, 'failed_queries': failed_queries}
                except StartupError as error:
                    failed_queries.append(error.diagnostics)
                    if attempt == 2 or time.monotonic() - query_start >= 10:
                        raise StartupError('Read-only IPP startup verification did not pass; queue URI unchanged.', {
                            'phase': 'identity-and-supply-retries', 'attempts': failed_queries,
                        }) from error
                    time.sleep(1)
        last = {'exit': result.returncode, 'stdout': result.stdout[:4096].decode('utf-8', 'replace'),
                'stderr': result.stderr[:4096].decode('utf-8', 'replace')}
        if time.monotonic() < deadline:
            time.sleep(0.25)
    raise StartupError('The background proxy did not become ready within the bounded startup wait.', {
        'phase': 'process-readiness', 'elapsed_seconds': time.monotonic() - start, 'last_probe': last,
    })


def record_startup_failure(review, error, started):
    """Preserve private metadata outside an installation that may be removed."""
    evidence = {'failed_at_utc': core.now(), 'error': str(error),
                'query': getattr(error, 'diagnostics', None), 'service_started': started}
    if started:
        try:
            status = subprocess.run(['/bin/launchctl', 'print', f'gui/{os.geteuid()}/{LABEL}'],
                                    capture_output=True, timeout=5)
            evidence['launchd'] = {'exit': status.returncode,
                                  'stdout': status.stdout[:65536].decode('utf-8', 'replace'),
                                  'stderr': status.stderr[:8192].decode('utf-8', 'replace')}
        except (OSError, subprocess.TimeoutExpired) as status_error:
            evidence['launchd_error'] = str(status_error)
    path = review / ('install-failure-' + str(time.time_ns()) + '.json')
    try:
        core.private_write(path, (json.dumps(evidence, indent=2, sort_keys=True) + '\n').encode())
        print('Private startup diagnostics retained: ' + str(path), file=sys.stderr)
    except OSError as evidence_error:
        print('Could not save startup diagnostics: ' + str(evidence_error), file=sys.stderr)


def install(package, source_review, library, staging=False):
    package = package.absolute()
    review, manifest = load_review(source_review)
    require(manifest['status'] == 'reviewed' and not manifest.get('pending_operation'), 'Install requires a fresh review.')
    verify_tree(package / 'runtime', package / 'runtime.json')
    verify_tree(package / 'maintenance', package / 'maintenance.json')
    verify_tree(package / 'licenses', package / 'licenses.json')
    root, plist = paths(library)
    require(not root.exists() and not root.is_symlink() and not plist.exists() and not plist.is_symlink(),
            'Existing installation or conflicting path. Nothing installed.')
    require(staging or not registered(), 'A supply proxy service is already registered.')
    if not staging:
        core.guard(core.read_regular(core.queue_ppd(manifest['queue'])), manifest['original_ppd_sha256'],
                   core.queue_snapshot(manifest['queue']), manifest['before'])
        idle(manifest['queue'])
        no_remaining_proxy_queues()
        busy = subprocess.run(['/usr/sbin/lsof', '-nP', '-iTCP:18326', '-sTCP:LISTEN', '-t'],
                              capture_output=True, timeout=10)
        require(busy.returncode == 1 and not busy.stdout, 'Loopback port 18326 is already occupied or cannot be checked.')
    root.parent.mkdir(parents=True, exist_ok=True)
    plist.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700)
    started = False
    try:
        shutil.copytree(package / 'runtime', root / 'runtime')
        shutil.copytree(package / 'maintenance', root / 'maintenance')
        shutil.copytree(package / 'licenses', root / 'licenses')
        shutil.copy2(package / 'maintenance.json', root / 'maintenance.json')
        shutil.copy2(package / 'maintenance.sha256', root / 'maintenance.sha256')
        shutil.copy2(package / 'uninstall', root / 'uninstall')
        shutil.copy2(package / 'INSTALLATION.md', root / 'INSTALLATION.md')
        core.private_write(root / 'python-path', (str(Path(sys.executable).resolve()) + '\n').encode())
        owned = root / 'review'
        owned.mkdir(mode=0o700)
        for name in ('manifest.json', 'original.ppd'):
            core.private_write(owned / name, core.read_regular(review / name))
        write_json(root / 'receipt.json', {'kind': LABEL, 'format': 1, 'owner': os.geteuid(), 'staging': staging})
        launch = {'Label': LABEL, 'ProgramArguments': [str(root / 'runtime/ipp-supply-proxy'),
                  '-uuid', manifest['hardware_uuid'], '-discover', str(root / 'runtime/discover')],
                  'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 15,
                  'ProcessType': 'Background', 'LimitLoadToSessionType': 'Aqua', 'Umask': 63,
                  'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null'}
        core.private_write(plist, plistlib.dumps(launch))
        if not staging:
            command(['/bin/launchctl', 'bootstrap', f'gui/{os.geteuid()}', str(plist)])
            started = True
            verified = wait_for_proxy(manifest['hardware_uuid'])
            if verified is not None:
                write_json(root / 'startup-verification.json', verified)
                core.private_write(review / ('install-verification-' + str(time.time_ns()) + '.json'),
                                   (json.dumps(verified, indent=2, sort_keys=True) + '\n').encode())
            mutate_uri(owned)
        print(f'Optional supply proxy installed at {root}. Autostart enabled: {not staging}.')
    except Exception as error:
        record_startup_failure(review, error, started)
        retain = False
        if (root / 'review/manifest.json').is_file():
            _, actual = load_review(root / 'review')
            retain = actual['status'] != 'reviewed' or bool(actual.get('pending_operation'))
        if retain:
            print(f'Installation needs review. Running service and rollback retained at {root}.', file=sys.stderr)
            raise
        if started:
            no_remaining_proxy_queues()
            command(['/bin/launchctl', 'bootout', f'gui/{os.geteuid()}/{LABEL}'])
        plist.unlink(missing_ok=True)
        shutil.rmtree(root)
        raise


def uninstall(library, staging=False):
    root, plist = paths(library)
    require(not root.is_symlink() and not plist.is_symlink(), 'Refusing redirected installation paths.')
    if not root.exists() and not plist.exists():
        print('Already uninstalled.')
        return
    core.verify_private_dir(root)
    receipt = json.loads(core.read_regular(root / 'receipt.json'))
    require(receipt == {'kind': LABEL, 'format': 1, 'owner': os.geteuid(), 'staging': staging},
            'Missing/wrong ownership receipt or staging mode. Nothing removed.')
    verify_tree(root / 'maintenance', root / 'maintenance.json')
    review, manifest = load_review(root / 'review')
    require(not manifest.get('pending_operation'), 'Uncertain prior URI write. Working service and rollback retained.')
    if manifest['status'] in ('applied', 'needs-review'):
        require(not staging, 'Staging cannot restore an applied URI.')
        uris = queue_uris()
        if manifest['queue'] in uris:
            mutate_uri(review, restore=True)
        else:
            no_remaining_proxy_queues()
            manifest['status'] = 'queue-deleted-no-proxy-users'
            write_json(review / 'manifest.json', manifest)
    else:
        require(manifest['status'] in ('reviewed', 'restored', 'queue-deleted-no-proxy-users'),
                'Unrecognized review state. Nothing removed.')
    if not staging:
        no_remaining_proxy_queues()
        if registered():
            command(['/bin/launchctl', 'bootout', f'gui/{os.geteuid()}/{LABEL}'])
    plist.unlink(missing_ok=True)
    shutil.rmtree(root)
    print('Direct Bonjour URI restored before unloading. Proxy, autostart and private rollback removed.')
    print('Existing queues, current PPD/preferences and scan documents are retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'install', 'uninstall'))
    parser.add_argument('--queue')
    parser.add_argument('--printer-uuid')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--package-root', type=Path)
    parser.add_argument('--staging-library', type=Path)
    args = parser.parse_args()
    validate_native_python()
    library = args.staging_library or Path.home() / 'Library'
    require(library.is_absolute(), 'Library path must be absolute.')
    if args.operation == 'prepare':
        require(args.queue and args.printer_uuid and args.output and not args.review
                and not args.package_root and not args.staging_library, 'Prepare needs queue, printer UUID and output only.')
        prepare_review(args.queue, args.printer_uuid, args.output.absolute())
    elif args.operation == 'install':
        require(args.review and args.package_root and not args.queue and not args.printer_uuid and not args.output,
                'Install needs package root and an explicit private review.')
        install(args.package_root, args.review, library, bool(args.staging_library))
    else:
        require(not any((args.queue, args.printer_uuid, args.output, args.review, args.package_root)),
                'Uninstall takes only its optional staging Library.')
        uninstall(library, bool(args.staging_library))


if __name__ == '__main__':
    try:
        main()
    except (core.ReviewError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print('Supply proxy maintenance stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
