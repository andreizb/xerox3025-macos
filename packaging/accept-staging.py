#!/usr/bin/env python3
"""Verify package installation/removal in a temporary Library, without launchd or scanning."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import pathlib
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', type=pathlib.Path)
parser.add_argument('--evidence', type=pathlib.Path, required=True)
args = parser.parse_args()
package = args.package.resolve()
records = []


def command(argv, expected=0, timeout=30):
    result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, timeout=timeout)
    if result.returncode != expected:
        raise RuntimeError(f'{argv[0]}: expected {expected}, got {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result


def check(name, condition):
    assert condition, name
    records.append({'check': name, 'passed': True})


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def simulated_shutdown(work, runtime, stubborn=False):
    """Exercise the shipped supervisor with local fake executables, never SANE."""
    fake = work / ('stubborn-runtime' if stubborn else 'normal-runtime')
    (fake / 'bin').mkdir(parents=True)
    (fake / 'etc').mkdir()
    state = fake / 'state'
    state.mkdir()
    ready = fake / 'ready'
    for name in ('bridge-run', 'service-lock'):
        shutil.copy2(runtime / 'bin' / name, fake / 'bin' / name)
    (fake / 'bin/discover').write_text('#!/bin/sh\nprintf "tcp test.invalid. 9400\\n"\n')
    (fake / 'bin/airsaned').write_text('#!/bin/sh\nprintf "%s\\n" "$$" > "$XEROX_TEST_READY"\n' +
                                     ("trap '' TERM\n" if stubborn else '') + 'exec /bin/sleep 120\n')
    for name in ('discover', 'airsaned'):
        (fake / 'bin' / name).chmod(0o755)
    env = os.environ.copy()
    env['XEROX_TEST_READY'] = str(ready)
    process = subprocess.Popen([str(fake / 'bin/service-lock'), str(state / 'instance.lock'),
                                str(fake / 'bin/bridge-run'), str(state),
                                '00000000-0000-0000-0000-000000000000'], env=env,
                               start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        check('fake daemon started: ' + ('stubborn' if stubborn else 'normal'),
              ready.exists() and process.poll() is None)
        time.sleep(0.1)
        start = time.monotonic()
        process.terminate()
        process.wait(timeout=35 if stubborn else 5)
        check('supervisor shutdown bounded: ' + ('stubborn' if stubborn else 'normal'),
              process.returncode == 0 and time.monotonic() - start < (35 if stubborn else 5))
        command([fake / 'bin/service-lock', state / 'instance.lock', '/usr/bin/true'])
        check('shutdown leaves no child holding lock: ' + ('stubborn' if stubborn else 'normal'), True)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def staged_association_install(work, package, hardware):
    """Exercise owned rollback file handling; staging cannot call real CUPS."""
    spec = importlib.util.spec_from_file_location('staging_association', package / 'maintenance/associate-queue.py')
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    review = work / 'review-fixture'
    review.mkdir(mode=0o700)
    original = ('*PPD-Adobe: "4.3"\n*% PPD created by ipp2ppd (offline fixture)\n'
                f'*PrinterUUID: "{hardware}"\n*APAirPrint: True\n*DefaultPageSize: A4\n').encode()
    generated = original + (f'*APScannerUUID: "{hardware}"\n*APICADriver: True\n'
                            f'*APScannerModulePath: "{module.AIRSCAN}"\n').encode()
    before = {'settings': {'printer-name': 'OfflineFixture', 'printer-uuid': 'urn:uuid:local-fixture',
                          'device-uri': 'dnssd://OfflineFixture._ipp._tcp.local./?uuid=' + hardware},
              'default_destination': 'OfflineFixture', 'effective_options': {},
              'user_lpoptions_sha256': None, 'printer_state': 3}
    manifest = {'format': 1, 'status': 'reviewed', 'review_user_uid': os.geteuid(),
                'queue': 'OfflineFixture', 'hardware_uuid': hardware, 'toner_hook': False,
                'before': before, 'original_sha256': module.sha(original),
                'generated_sha256': module.sha(generated), 'candidate_sha256': module.sha(generated)}
    for name, data in [('original.ppd', original), ('apple-generated.ppd', generated), ('candidate.ppd', generated)]:
        module.private_write(review / name, data)
    module.write_manifest(review, manifest)
    original_manifest = (review / 'manifest.json').read_bytes()
    library = work / 'association staging/Library'
    root = library / 'Application Support/Xerox3025Bridge'
    plist = library / 'LaunchAgents/local.xerox3025.bridge.plist'
    install = [package / 'install', '--staging-library', library, '--association-review', review]
    uninstall = [package / 'uninstall', '--staging-library', library]
    command(install + ['--python', work / 'missing-python'], 69)
    check('missing native maintenance interpreter blocks before install', not root.exists() and not plist.exists())
    command(install + ['--python', sys.executable])
    owned = root / 'association-review'
    check('review copied privately without applying in staging',
          owned.stat().st_mode & 0o777 == 0o700 and
          json.loads((owned / 'manifest.json').read_text())['status'] == 'reviewed')
    check('source review remains unchanged', (review / 'manifest.json').read_bytes() == original_manifest)
    check('only verified maintenance source files installed',
          sorted(p.name for p in (root / 'maintenance').iterdir()) ==
          ['associate-queue.py', 'association-maintenance.py', 'select-python'])
    command(uninstall + ['--python', work / 'missing-python'], 69)
    check('missing interpreter preserves rollback and installed files', owned.is_dir() and plist.is_file())
    manifest['pending_operation'] = 'apply'
    module.write_manifest(owned, manifest)
    command(uninstall, 1)
    check('uncertain association blocks removal and retains rollback', owned.is_dir() and plist.is_file())
    manifest.pop('pending_operation')
    manifest['status'] = 'applied'
    manifest['after'] = before
    module.write_manifest(owned, manifest)
    command(uninstall, 1)
    check('staging cannot remove an applied association', owned.is_dir() and plist.is_file())
    manifest['status'] = 'reviewed'
    module.write_manifest(owned, manifest)
    helper = root / 'maintenance/associate-queue.py'
    helper_bytes = helper.read_bytes()
    helper.write_bytes(helper_bytes + b'\n# deliberate integrity alteration\n')
    command(uninstall, 1)
    check('altered maintenance code blocks removal before execution', owned.is_dir() and plist.is_file())
    helper.write_bytes(helper_bytes)
    command(uninstall)
    check('staged association removal deletes rollback and runtime', not root.exists() and not plist.exists())
    (review / 'candidate.ppd').write_bytes(generated + b'\n# altered review\n')
    command(install + ['--python', sys.executable], 1)
    check('altered review rejected and partial install cleaned', not root.exists() and not plist.exists())


real_library = pathlib.Path.home() / 'Library'
real_paths = [real_library / 'LaunchAgents/local.xerox3025.bridge.plist',
              real_library / 'Application Support/Xerox3025Bridge/receipt']
baseline = {str(p): digest(p) for p in real_paths}
ppds = pathlib.Path('/etc/cups/ppd')
queue_baseline = {p.name: digest(p) for p in ppds.glob('*') if p.is_file()}
report = {'system_install_performed': False, 'autostart_tested': False, 'hardware_acquisition_performed': False,
          'package': str(package), 'checks': records}
try:
    with tempfile.TemporaryDirectory(prefix='xerox-package-acceptance-') as temporary:
        work = pathlib.Path(temporary)
        library = work / "staging folder with spaces & apostrophe ' /Library"
        root = library / 'Application Support/Xerox3025Bridge'
        plist = library / 'LaunchAgents/local.xerox3025.bridge.plist'
        command([package / 'install', '--staging-library', library])
        parsed = plistlib.loads(plist.read_bytes())
        identity = plistlib.loads((package / 'payload/etc/device.plist').read_bytes())
        check('launcher uses staged absolute paths and configured identity', parsed['ProgramArguments'] == [
            str(root / 'runtime/bin/service-lock'), str(root / 'state/instance.lock'),
            str(root / 'runtime/bin/bridge-run'), str(root / 'state'), identity['printer_uuid']])
        check('private installation and state permissions', root.stat().st_mode & 0o777 == 0o700 and
              (root / 'state').stat().st_mode & 0o777 == 0o700)
        command([root / 'runtime/bin/scanimage', '--version'])
        # Upstream AirSane returns -1 (255) for the help-only path.
        help_result = command([root / 'runtime/bin/airsaned', '--help'], 255)
        check('AirSane executes its help-only path', '--listen-port=' in help_result.stdout)
        ctypes.CDLL(str(root / 'runtime/lib/sane/libsane-xerox_mfp.1.so'))
        check('relocated executables and backend load', True)
        for record in json.loads((package / 'architecture.json').read_text()):
            command(['/usr/bin/codesign', '--verify', '--strict', root / 'runtime' / record['file']])
            check('arm64 and valid signature: ' + record['file'], record['architectures'] == 'arm64')
        before = digest(plist)
        command([package / 'install', '--staging-library', library], 73)
        check('second install preserves existing configuration', digest(plist) == before)
        lock = root / 'runtime/bin/service-lock'
        ready = work / 'lock-ready'
        # The marker makes lock acquisition observable before the competing launch.
        child = subprocess.Popen([str(lock), str(root / 'state/instance.lock'), '/bin/sh', '-c',
                                  'touch "$1"; exec /bin/sleep 30', 'sh', str(ready)])
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            check('first service holds lock', ready.exists() and child.poll() is None)
            command([lock, root / 'state/instance.lock', '/usr/bin/true'], 75)
            check('concurrent service rejected', True)
        finally:
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=5)
        command([lock, root / 'state/instance.lock', '/usr/bin/true'])
        check('lock releases after service termination', True)
        simulated_shutdown(work, root / 'runtime')
        simulated_shutdown(work, root / 'runtime', stubborn=True)
        receipt = root / 'receipt'
        original_receipt = receipt.read_bytes()
        receipt.write_text('not an owned installation\n')
        command([package / 'uninstall', '--staging-library', library], 73)
        check('invalid ownership receipt prevents removal', root.is_dir() and plist.is_file())
        receipt.write_bytes(original_receipt)
        command([package / 'uninstall', '--staging-library', library])
        check('uninstall removes all owned files and state', not root.exists() and not plist.exists())
        command([package / 'uninstall', '--staging-library', library])
        check('uninstall is idempotent', True)
        bad = work / 'tampered-package'
        shutil.copytree(package, bad)
        with (bad / 'payload/bin/bridge-run').open('a') as output:
            output.write('\n# deliberate integrity-test alteration\n')
        command([bad / 'install', '--staging-library', library], 1)
        check('altered payload fails before installation', not root.exists() and not plist.exists())
        root.parent.mkdir(parents=True, exist_ok=True)
        root.symlink_to(work / 'missing-target')
        command([package / 'install', '--staging-library', library], 73)
        check('dangling conflicting symlink preserved', root.is_symlink())
        root.unlink()
        staged_association_install(work, package, identity['printer_uuid'])
    check('actual user installation unchanged', baseline == {str(p): digest(p) for p in real_paths})
    check('all existing printer PPDs unchanged', queue_baseline == {p.name: digest(p) for p in ppds.glob('*') if p.is_file()})
    report['passed'] = True
except Exception as error:
    report.update(passed=False, error=str(error))
    raise
finally:
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(report, indent=2) + '\n')
print(f"Passed {len(records)} staging checks; no service was registered and no scan was requested.")
