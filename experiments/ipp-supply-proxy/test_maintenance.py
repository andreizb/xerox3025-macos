#!/usr/bin/env python3
"""Exercise URI rollback and file lifecycle with fake queues only.

SPDX-License-Identifier: MIT
No real CUPS, launchd, printer or network calls occur in these tests.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('proxy_maintenance', HERE / 'proxy-maintenance.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
HARDWARE = '00000000-0000-1000-8000-000000000001'
QUEUE = 'OfflineSupplyFixture'
DIRECT = 'dnssd://OfflineFixture._ipp._tcp.local./?uuid=' + HARDWARE


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='xerox-proxy-maintenance-test-')
        self.work = Path(self.temporary.name)
        self.ppd = self.work / 'current.ppd'
        self.ppd.write_text('*PPD-Adobe: "4.3"\n*APAirPrint: True\n*PrinterUUID: "' + HARDWARE + '"\n')
        self.current = {'settings': {'printer-name': QUEUE, 'printer-uuid': 'urn:uuid:local-fixture',
                                    'device-uri': DIRECT, 'copies-default': 1},
                        'effective_options': {'copies': '1'}, 'default_destination': QUEUE,
                        'user_lpoptions_sha256': None, 'printer_state': 3}
        self.events, self.jobs, self.other_uris = [], False, {}
        self.failure, self.postcheck_failure, self.wrote = None, False, False
        self.active = False
        self.patches = [patch.object(m.core, 'queue_ppd', lambda queue: self.ppd),
                        patch.object(m.core, 'queue_snapshot', self.snapshot),
                        patch.object(m.core, 'run', self.fake_cups)]
        for item in self.patches:
            item.start()
        self.review = self.work / 'review'
        m.prepare_review(QUEUE, HARDWARE, self.review)
        self.original = copy.deepcopy(self.current)
        self.original_ppd = self.ppd.read_bytes()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def snapshot(self, queue):
        if self.current is None or (self.postcheck_failure and self.wrote):
            raise m.core.ReviewError('deliberate post-write read failure')
        return copy.deepcopy(self.current)

    def fake_cups(self, args, timeout=30):
        if args[0] == '/usr/bin/lpstat' and '-o' in args:
            return b'OfflineFixture-42 pending\n' if self.jobs else b''
        if args[0] == '/usr/bin/lpstat' and '-v' in args:
            uris = dict(self.other_uris)
            if self.current is not None:
                uris[QUEUE] = self.current['settings']['device-uri']
            return ''.join(f'device for {queue}: {uri}\n' for queue, uri in uris.items()).encode()
        if args[0] == '/usr/sbin/lpadmin':
            self.assertEqual(args[:6], ['/usr/sbin/lpadmin', '-h', m.LOCAL_CUPS, '-p', QUEUE, '-v'])
            self.assertEqual(len(args), 7)
            self.events.append('uri:' + args[-1])
            if self.failure == 'before':
                raise m.core.ReviewError('deliberately rejected')
            self.current['settings']['device-uri'] = args[-1]
            self.wrote = True
            if self.failure == 'after':
                raise subprocess.TimeoutExpired(args, 30)
            return b''
        raise AssertionError('Unexpected external command: ' + repr(args))

    def manifest(self, directory=None):
        return json.loads(((directory or self.review) / 'manifest.json').read_text())

    def test_exact_uri_roundtrip_preserves_every_other_setting(self):
        m.mutate_uri(self.review)
        self.assertEqual(self.current, m.with_uri(self.original, m.PROXY_URI))
        m.mutate_uri(self.review, restore=True)
        self.assertEqual(self.current, self.original)
        self.assertEqual(self.ppd.read_bytes(), self.original_ppd)
        self.assertEqual(self.manifest()['status'], 'restored')

    def test_later_preferences_and_ppd_edits_survive_restore(self):
        m.mutate_uri(self.review)
        self.current['settings']['copies-default'] = 2
        self.current['effective_options']['copies'] = '2'
        self.current['default_destination'] = 'OtherPrinter'
        self.current['user_lpoptions_sha256'] = 'changed-by-user'
        self.ppd.write_bytes(self.original_ppd + b'*% Later scanner association or user setting\n')
        expected, expected_ppd = m.with_uri(self.current, DIRECT), self.ppd.read_bytes()
        m.mutate_uri(self.review, restore=True)
        self.assertEqual(self.current, expected)
        self.assertEqual(self.ppd.read_bytes(), expected_ppd)

    def test_review_drift_and_jobs_block_before_write(self):
        self.current['settings']['copies-default'] = 2
        with self.assertRaises(m.core.ReviewError):
            m.mutate_uri(self.review)
        self.current = copy.deepcopy(self.original)
        self.jobs = True
        with self.assertRaises(m.core.ReviewError):
            m.mutate_uri(self.review)
        self.assertEqual(self.events, [])

    def test_later_uri_or_queue_identity_blocks_restore(self):
        m.mutate_uri(self.review)
        self.events.clear()
        self.current['settings']['device-uri'] = 'ipp://changed.invalid/ipp/print'
        with self.assertRaises(m.core.ReviewError):
            m.mutate_uri(self.review, restore=True)
        self.current['settings']['device-uri'] = m.PROXY_URI
        self.current['settings']['printer-uuid'] = 'new-queue'
        with self.assertRaises(m.core.ReviewError):
            m.mutate_uri(self.review, restore=True)
        self.assertEqual(self.events, [])

    def test_rejected_write_is_recorded_without_retry(self):
        self.failure = 'before'
        with self.assertRaises(m.core.ReviewError):
            m.mutate_uri(self.review)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.current, self.original)
        self.assertEqual(self.manifest()['status'], 'reviewed')
        self.assertNotIn('pending_operation', self.manifest())

    def test_timeout_after_success_is_verified_without_retry(self):
        self.failure = 'after'
        m.mutate_uri(self.review)
        self.assertEqual(self.manifest()['status'], 'applied')
        self.assertEqual(len(self.events), 1)
        self.assertIn('timed out', self.manifest()['last_command_error'])

    def test_failed_postcheck_retains_uncertain_write_and_prevents_repeat(self):
        self.postcheck_failure = True
        with self.assertRaises(m.core.ReviewError):
            m.mutate_uri(self.review)
        self.assertEqual(self.manifest()['status'], 'needs-review')
        self.assertEqual(self.manifest()['pending_operation'], 'apply')
        with self.assertRaises(m.core.ReviewError):
            m.mutate_uri(self.review, restore=True)
        self.assertEqual(len(self.events), 1)

    def package(self):
        package = self.work / 'package fixture'
        for part in ('runtime', 'maintenance', 'licenses'):
            (package / part).mkdir(parents=True)
            (package / part / 'fixture').write_text('isolated file lifecycle fixture')
            hashes = {'fixture': hashlib.sha256((package / part / 'fixture').read_bytes()).hexdigest()}
            (package / (part + '.json')).write_text(json.dumps(hashes))
        (package / 'maintenance.sha256').write_text('fixture checksum placeholder for file-copy test')
        shutil.copy2(HERE / 'uninstall', package / 'uninstall')
        shutil.copy2(HERE / 'INSTALLATION.md', package / 'INSTALLATION.md')
        return package

    def test_staging_install_remove_and_conflict_guards(self):
        package = self.package()
        library = self.work / "staging folder & apostrophe ' /Library"
        m.install(package, self.review, library, staging=True)
        root, plist = m.paths(library)
        self.assertTrue(root.is_dir() and plist.is_file())
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.manifest(root / 'review')['status'], 'reviewed')
        self.assertEqual(self.events, [])
        with self.assertRaises(m.core.ReviewError):
            m.install(package, self.review, library, staging=True)
        owned = self.manifest(root / 'review')
        owned['pending_operation'] = 'apply'
        m.write_json(root / 'review/manifest.json', owned)
        with self.assertRaises(m.core.ReviewError):
            m.uninstall(library, staging=True)
        self.assertTrue(root.is_dir() and plist.is_file())
        owned.pop('pending_operation')
        m.write_json(root / 'review/manifest.json', owned)
        (root / 'maintenance/fixture').write_text('altered maintenance source')
        with self.assertRaises(m.core.ReviewError):
            m.uninstall(library, staging=True)
        shutil.copy2(package / 'maintenance/fixture', root / 'maintenance/fixture')
        m.uninstall(library, staging=True)
        m.uninstall(library, staging=True)
        self.assertFalse(root.exists() or plist.exists())
        self.assertEqual(self.events, [])

    def fake_launch(self, args, timeout=40):
        self.assertEqual(args[0], '/bin/launchctl')
        self.events.append(args[1])
        self.active = args[1] == 'bootstrap'
        return b''

    def launch_patches(self):
        return (patch.object(m, 'registered', lambda: self.active),
                patch.object(m, 'command', self.fake_launch),
                patch.object(m, 'wait_for_proxy', lambda hardware: self.events.append('identity-query')),
                patch.object(m.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 1, b'', b'')))

    def test_uri_restored_before_unload_and_reinstall_works(self):
        package, library = self.package(), self.work / 'Library'
        patches = self.launch_patches()
        for item in patches:
            item.start()
        try:
            m.install(package, self.review, library)
            self.assertEqual(self.events, ['bootstrap', 'identity-query', 'uri:' + m.PROXY_URI])
            m.uninstall(library)
            self.assertEqual(self.events[-2:], ['uri:' + DIRECT, 'bootout'])
            self.assertEqual(self.current, self.original)
            second_review = self.work / 'second-review'
            m.prepare_review(QUEUE, HARDWARE, second_review)
            m.install(package, second_review, library)
            m.uninstall(library)
        finally:
            for item in reversed(patches):
                item.stop()

    def test_restore_failure_keeps_running_service_and_rollback(self):
        package, library = self.package(), self.work / 'Library'
        patches = self.launch_patches()
        for item in patches:
            item.start()
        try:
            m.install(package, self.review, library)
            self.failure = 'before'
            with self.assertRaises(m.core.ReviewError):
                m.uninstall(library)
            root, plist = m.paths(library)
            self.assertTrue(root.is_dir() and plist.is_file() and self.active)
            self.assertEqual(self.current['settings']['device-uri'], m.PROXY_URI)
            self.assertNotIn('bootout', self.events)
        finally:
            for item in reversed(patches):
                item.stop()

    def test_missing_runtime_can_still_restore_uri_and_uninstall(self):
        package, library = self.package(), self.work / 'Library'
        patches = self.launch_patches()
        for item in patches:
            item.start()
        try:
            m.install(package, self.review, library)
            root, plist = m.paths(library)
            shutil.rmtree(root / 'runtime')
            m.uninstall(library)
            self.assertEqual(self.current, self.original)
            self.assertFalse(root.exists() or plist.exists())
        finally:
            for item in reversed(patches):
                item.stop()

    def test_other_localhost_queue_retains_service_after_owned_uri_restore(self):
        package, library = self.package(), self.work / 'Library'
        patches = self.launch_patches()
        for item in patches:
            item.start()
        try:
            m.install(package, self.review, library)
            self.other_uris['OtherFixture'] = 'ipp://localhost:18326/ipp/print'
            with self.assertRaises(m.core.ReviewError):
                m.uninstall(library)
            root, plist = m.paths(library)
            self.assertTrue(root.exists() and plist.exists() and self.active)
            self.assertEqual(self.current, self.original)
            self.assertEqual(self.manifest(root / 'review')['status'], 'restored')
        finally:
            for item in reversed(patches):
                item.stop()

    def test_cold_start_waits_past_old_eight_tenths_second_limit(self):
        elapsed, probes, identity = [0.0], [], []
        def probe(args, **kwargs):
            self.assertEqual(args[0], '/usr/bin/curl')
            probes.append(elapsed[0])
            ready = elapsed[0] >= 2.0
            return subprocess.CompletedProcess(args, 0 if ready else 7,
                b'process running; printer availability is checked on each request\n' if ready else b'',
                b'' if ready else b'connection refused during cold launch')
        with patch.object(m.time, 'monotonic', lambda: elapsed[0]), \
             patch.object(m.time, 'sleep', lambda amount: elapsed.__setitem__(0, elapsed[0] + amount)), \
             patch.object(m.subprocess, 'run', probe), \
             patch.object(m, 'verify_proxy', lambda hardware: identity.append((hardware, elapsed[0]))):
            m.wait_for_proxy(HARDWARE)
        self.assertEqual(identity, [(HARDWARE, 2.0)])
        self.assertGreater(len(probes), 3)

    def test_unready_process_is_bounded_and_never_accepted_as_printer(self):
        elapsed = [0.0]
        with patch.object(m.time, 'monotonic', lambda: elapsed[0]), \
             patch.object(m.time, 'sleep', lambda amount: elapsed.__setitem__(0, elapsed[0] + amount)), \
             patch.object(m.subprocess, 'run', lambda args, **kw: subprocess.CompletedProcess(args, 7, b'', b'not ready')), \
             patch.object(m, 'verify_proxy') as identity:
            with self.assertRaises(m.StartupError) as caught:
                m.wait_for_proxy(HARDWARE, readiness_seconds=1)
        identity.assert_not_called()
        self.assertEqual(elapsed[0], 1.0)
        self.assertEqual(caught.exception.diagnostics['phase'], 'process-readiness')

    def test_failed_ipp_probe_preserves_stdout_diagnostic(self):
        result = subprocess.CompletedProcess([], 1, b'<plist>IPP response details</plist>', b'(null)')
        with patch.object(m.subprocess, 'run', lambda *args, **kw: result):
            with self.assertRaises(m.StartupError) as caught:
                m.verify_proxy(HARDWARE)
        self.assertIn('IPP response details', caught.exception.diagnostics['stdout'])
        self.assertEqual(caught.exception.diagnostics['stderr'], '(null)')

    def test_transient_ipp_failure_retries_full_identity_gate_and_keeps_evidence(self):
        ready = subprocess.CompletedProcess([], 0,
                    b'process running; printer availability is checked on each request\n', b'')
        errors = [m.StartupError('empty first response', {'phase': 'identity-and-supply-query', 'exit': 1}),
                  {'hardware_uuid': HARDWARE, 'marker_color': '#000000', 'marker_level': 39}]
        with patch.object(m.subprocess, 'run', lambda *args, **kw: ready), \
             patch.object(m.time, 'sleep'), patch.object(m, 'verify_proxy', side_effect=errors) as identity:
            result = m.wait_for_proxy(HARDWARE)
        self.assertEqual(identity.call_count, 2)
        self.assertTrue(result['passed'])
        self.assertEqual(result['verified']['hardware_uuid'], HARDWARE)
        self.assertEqual(result['failed_queries'], [{'phase': 'identity-and-supply-query', 'exit': 1}])

    def test_wrong_identity_is_not_retried_or_accepted(self):
        ready = subprocess.CompletedProcess([], 0,
                    b'process running; printer availability is checked on each request\n', b'')
        with patch.object(m.subprocess, 'run', lambda *args, **kw: ready), \
             patch.object(m, 'verify_proxy', side_effect=m.core.ReviewError('wrong physical UUID')) as identity:
            with self.assertRaises(m.core.ReviewError):
                m.wait_for_proxy(HARDWARE)
        self.assertEqual(identity.call_count, 1)

    def test_startup_failure_cleans_install_and_retains_diagnostic_in_review(self):
        package, library = self.package(), self.work / 'Library'
        patches = self.launch_patches()
        for item in patches:
            item.start()
        try:
            with patch.object(m, 'wait_for_proxy', side_effect=m.StartupError('fixture failure', {'phase': 'fixture'})):
                with self.assertRaises(m.StartupError):
                    m.install(package, self.review, library)
            root, plist = m.paths(library)
            self.assertFalse(root.exists() or plist.exists() or self.active)
            self.assertEqual(self.current, self.original)
            diagnostics = list(self.review.glob('install-failure-*.json'))
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(json.loads(diagnostics[0].read_text())['query'], {'phase': 'fixture'})
            self.assertNotIn('uri:' + m.PROXY_URI, self.events)
        finally:
            for item in reversed(patches):
                item.stop()


class ShellEntryPointTests(unittest.TestCase):
    def test_system_bash_dispatches_empty_and_forwarded_arguments(self):
        # Exercise the shipped wrappers under Apple's Bash, with a harmless
        # recorder instead of maintenance. Python-only tests miss shell errors.
        with tempfile.TemporaryDirectory(prefix='xerox-wrapper-test-') as temporary:
            package = Path(temporary) / 'package with spaces'
            maintenance = package / 'maintenance'
            maintenance.mkdir(parents=True)
            selector = maintenance / 'select-python'
            selector.write_text('#!/bin/bash\nprintf "%s\\n" ' + shlex.quote(sys.executable) + '\n')
            recorder = maintenance / 'proxy-maintenance.py'
            recorder.write_text('import json, sys\nprint(json.dumps(sys.argv[1:]))\n')
            (package / 'maintenance.sha256').write_text(''.join(
                hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                for p in (selector, recorder)))
            for operation in ('install', 'uninstall'):
                wrapper = package / operation
                shutil.copy2(HERE / operation, wrapper)
                prefix = [operation] + (['--package-root', str(package.resolve())] if operation == 'install' else [])
                for arguments, forwarded in (([], []), (['--python', sys.executable], []),
                        (['--staging-library', str(package / 'test Library')],
                         ['--staging-library', str(package / 'test Library')])):
                    with self.subTest(operation=operation, arguments=arguments):
                        result = subprocess.run(['/bin/bash', str(wrapper), *arguments],
                                                capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(json.loads(result.stdout.splitlines()[-1]), prefix + forwarded)


if __name__ == '__main__':
    unittest.main(verbosity=2)
