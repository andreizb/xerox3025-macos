#!/usr/bin/env python3
"""Offline safety tests: no printer, CUPS changes, or installed components."""
import importlib.util
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "associate_queue", Path(__file__).resolve().parents[1] / "scripts/associate-queue.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
maintenance_spec = importlib.util.spec_from_file_location(
    'association_maintenance', Path(__file__).resolve().parents[1] / 'packaging/association-maintenance.py')
maintenance = importlib.util.module_from_spec(maintenance_spec)
maintenance_spec.loader.exec_module(maintenance)

UUID = "11111111-2222-3333-4444-555555555555"
ORIGINAL = f'''*PPD-Adobe: "4.3"
*% PPD created by ipp2ppd (test)
*PrinterUUID: "{UUID}"
*APAirPrint: True
*DefaultPageSize: A4
*DefaultResolution: 600x600dpi
*cupsFilter2: "image/urf image/urf 10 -"
*APPrinterPreset Saved: "
  *ColorModel Gray
  *PageSize A4"
*End
'''.encode()
GENERATED = ORIGINAL + f'''*APScannerUUID: "{UUID}"
*APICADriver: True
*APScannerModulePath: "{module.AIRSCAN}"
'''.encode()


def snapshot():
    return {"settings": {
        "printer-name": "Test", "printer-uuid": "urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "device-uri": "dnssd://Example._ipp._tcp.local./?uuid=" + UUID,
        "media-col-default": {"media-size": {"x-dimension": 21000, "y-dimension": 29700}},
        "copies-default": 2,
    }, "effective_options": {"copies": "3"}, "default_destination": "Test",
        "user_lpoptions_sha256": "some-hash", "printer_state": 3}


class QueueSnapshotTests(unittest.TestCase):
    def test_cold_cups_uses_local_socket_before_tcp_and_preserves_settings(self):
        expected = snapshot()
        user_options = b'Dest Test copies=3\n'
        expected['user_lpoptions_sha256'] = module.sha(user_options)
        attrs = {**copy.deepcopy(expected['settings']), 'printer-state': 3,
                 'printer-state-reasons': ['none'], 'marker-levels': [39]}
        report = module.plistlib.dumps({'Tests': [
            {'Successful': True, 'ResponseAttributes': [attrs]}]})
        socket_read = ['/usr/bin/lpoptions', '-h', module.LOCAL_CUPS, '-p', 'Test']
        tcp_read = ['/usr/bin/ipptool', '-T', '10', '-X',
                    'ipp://localhost:631/printers/Test',
                    '/usr/share/cups/ipptool/get-printer-attributes.test']
        default_read = ['/usr/bin/lpstat', '-h', module.LOCAL_CUPS, '-d']
        local_ready, calls = False, []

        def fake_run(args, timeout=30):
            nonlocal local_ready
            calls.append(args)
            if args == socket_read:
                local_ready = True
                return b'copies=3 printer-state=3 marker-levels=39 device-uri=ignored\n'
            if args == tcp_read:
                if not local_ready:
                    raise module.ReviewError('Fake cold CUPS TCP listener is unavailable.')
                return report
            if args == default_read:
                return expected['default_destination'].encode() + b'\n'
            self.fail('Unexpected external command: ' + repr(args))

        with tempfile.TemporaryDirectory(prefix='xerox-cold-cups-') as temporary:
            home = Path(temporary)
            (home / '.cups').mkdir()
            (home / '.cups/lpoptions').write_bytes(user_options)
            with mock.patch.object(module.Path, 'home', return_value=home), \
                    mock.patch.object(module, 'run', side_effect=fake_run):
                actual = module.queue_snapshot('Test')
        self.assertEqual(actual, expected)
        self.assertEqual(calls, [socket_read, tcp_read, default_read])


class QueueAssociationTests(unittest.TestCase):
    def test_preserves_every_printing_byte(self):
        candidate, identity = module.derive_ppd(ORIGINAL, GENERATED)
        self.assertEqual(candidate, GENERATED)
        self.assertEqual(identity, UUID)
        self.assertNotIn(b"APPrinterLowInkTool", candidate)

    def test_generated_defaults_and_filter_cannot_replace_original(self):
        different = GENERATED.replace(b"*DefaultPageSize: A4", b"*DefaultPageSize: Letter")
        different = different.replace(b'image/urf image/urf 10 -', b'application/pdf 0 malicious')
        candidate, _ = module.derive_ppd(ORIGINAL, different)
        self.assertEqual(candidate, GENERATED)

    def test_crlf_and_non_ascii_preserved(self):
        original = ORIGINAL.replace(b"\n", b"\r\n") + b"*% Pr\xe9serv\xe9\r\n"
        candidate, _ = module.derive_ppd(original, GENERATED)
        self.assertTrue(candidate.startswith(original))
        self.assertNotIn(b"\n", candidate.replace(b"\r\n", b""))

    def test_replaces_only_existing_scanner_fields(self):
        # Keep original printer identity; only the old scanner identity differs.
        old = GENERATED.replace(b'*APScannerUUID: "' + UUID.encode(),
                                b'*APScannerUUID: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
        candidate, _ = module.derive_ppd(old, GENERATED)
        self.assertEqual(candidate, GENERATED)

    def test_mismatched_scanner_and_printer_identity_rejected(self):
        for field in (b"APScannerUUID", b"PrinterUUID"):
            bad = GENERATED.replace(b'*' + field + b': "' + UUID.encode(),
                                    b'*' + field + b': "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
            with self.subTest(field=field), self.assertRaises(module.ReviewError):
                module.derive_ppd(ORIGINAL, bad)

    def test_non_apple_or_missing_module_path_rejected(self):
        for path in (b"/Library/Image Capture/Devices/OldIntel.app", b"/tmp/AirScanScanner.app", b""):
            with self.subTest(path=path), self.assertRaises(module.ReviewError):
                module.derive_ppd(ORIGINAL, GENERATED.replace(module.AIRSCAN.encode(), path))

    def test_duplicate_key_and_false_ica_rejected(self):
        for bad in (GENERATED + b'*APICADriver: True\n',
                    GENERATED.replace(b'*APICADriver: True', b'*APICADriver: False')):
            with self.assertRaises(module.ReviewError):
                module.derive_ppd(ORIGINAL, bad)

    def test_supply_hook_is_explicit_and_does_not_change_print_filters(self):
        candidate, _ = module.derive_ppd(ORIGINAL, GENERATED, toner=True)
        self.assertEqual(candidate, GENERATED +
                         f'*APPrinterLowInkTool: "{module.SUPPLY_TOOL}"\n'.encode())

    def test_bonjour_hardware_identity_required(self):
        current = snapshot()
        module.check_identity(current, UUID)
        for uri in ("ipp://192.0.2.1/ipp/print", "dnssd://Example._ipp._tcp.local./",
                    "dnssd://Example._ipp._tcp.local./?uuid=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"):
            current["settings"]["device-uri"] = uri
            with self.assertRaises(module.ReviewError):
                module.check_identity(current, UUID)

    def test_stale_defaults_uuid_and_hash_block_before_mutation(self):
        expected = snapshot()
        for field in ("copies-default", "media-col-default", "printer-uuid", "device-uri"):
            current = snapshot()
            current["settings"][field] = "changed"
            with self.subTest(field=field), self.assertRaises(module.ReviewError):
                module.guard(ORIGINAL, module.sha(ORIGINAL), current, expected)
        with self.assertRaises(module.ReviewError):
            module.guard(ORIGINAL + b"\n", module.sha(ORIGINAL), expected, expected)

    def test_default_destination_and_user_options_changes_block(self):
        expected = snapshot()
        for field in ("default_destination", "effective_options", "user_lpoptions_sha256"):
            current = snapshot()
            current[field] = "changed"
            with self.subTest(field=field), self.assertRaises(module.ReviewError):
                module.guard(ORIGINAL, module.sha(ORIGINAL), current, expected)

    def test_busy_queue_and_unsafe_queue_ids_block(self):
        current = snapshot()
        current["printer_state"] = 4
        with self.assertRaises(module.ReviewError):
            module.guard(ORIGINAL, module.sha(ORIGINAL), current, snapshot())
        for queue in ("../printer", "name/instance", "$(touch example)", "-p other", ""):
            with self.subTest(queue=queue), self.assertRaises(module.ReviewError):
                module.queue_name(queue)

    def test_restore_accepts_new_preferences_but_requires_same_identity_and_ppd(self):
        expected = snapshot()
        current = snapshot()
        current['default_destination'] = 'Another printer'
        current['effective_options'] = {'copies': '4'}
        current['user_lpoptions_sha256'] = 'new-user-preferences'
        current['settings']['copies-default'] = 4
        keys = module.SCANNER_KEYS
        module.guard_restore(GENERATED, GENERATED, keys, current, expected)
        for key in ('printer-name', 'device-uri'):
            changed = copy.deepcopy(current)
            changed['settings'][key] = 'different'
            with self.subTest(key=key), self.assertRaises(module.ReviewError):
                module.guard_restore(GENERATED, GENERATED, keys, changed, expected)
        # CUPS reissues its own printer-uuid when macOS recreates the queue.
        # That is not a different printer, and must not strand the rollback.
        reissued = copy.deepcopy(current)
        reissued['settings']['printer-uuid'] = 'urn:uuid:99999999-9999-9999-9999-999999999999'
        module.guard_restore(GENERATED, GENERATED, keys, reissued, expected)
        # macOS regenerates this PPD on OS updates. Bytes outside the reviewed
        # fields may therefore differ, and that alone must not block rollback.
        module.guard_restore(GENERATED + b'*% Regenerated by the OS\n', GENERATED,
                             keys, current, expected)
        # The reviewed fields themselves must still be exactly what was written.
        tampered = GENERATED.replace(b'*APICADriver: True', b'*APICADriver: False')
        with self.assertRaises(module.ReviewError):
            module.guard_restore(tampered, GENERATED, keys, current, expected)


class FakeCUPSRoundTripTests(unittest.TestCase):
    """Run actual apply/restore logic against files and an in-memory CUPS state."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='xerox-fake-cups-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.review = self.root / 'review'
        self.review.mkdir(mode=0o700)
        self.ppd = self.root / 'fake-queue.ppd'
        self.ppd.write_bytes(ORIGINAL)
        self.current = snapshot()
        self.calls = []
        self.fail_apply = False
        self.alter_preferences_during_write = False
        for name, data in [('original.ppd', ORIGINAL), ('apple-generated.ppd', GENERATED), ('candidate.ppd', GENERATED)]:
            module.private_write(self.review / name, data)
        self.manifest = {'format': 1, 'status': 'reviewed', 'review_user_uid': os.geteuid(),
                         'queue': 'Test', 'hardware_uuid': UUID, 'toner_hook': False,
                         'before': snapshot(), 'original_sha256': module.sha(ORIGINAL),
                         'candidate_sha256': module.sha(GENERATED), 'generated_sha256': module.sha(GENERATED)}
        module.write_manifest(self.review, self.manifest)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(module, 'queue_ppd', return_value=self.ppd).start()
        mock.patch.object(module, 'queue_snapshot', side_effect=lambda _: copy.deepcopy(self.current)).start()
        mock.patch.object(module, 'validate_system_tools').start()
        mock.patch.object(module, 'run', side_effect=self.fake_run).start()

    def fake_run(self, args, timeout=30):
        args = [str(x) for x in args]
        self.calls.append(args)
        if args[0] == '/usr/sbin/lpadmin':
            self.assertEqual(args[1:6], ['-h', '/private/var/run/cupsd', '-p', 'Test', '-P'])
            if self.fail_apply:
                raise module.ReviewError('simulated authorization failure')
            self.ppd.write_bytes(Path(args[6]).read_bytes())
            if self.alter_preferences_during_write:
                self.current['default_destination'] = 'Unexpected concurrent change'
        elif args[0] not in ('/usr/bin/lpstat', '/usr/bin/cupstestppd'):
            self.fail('Unexpected external command: ' + str(args))
        return b''

    def test_apply_then_restore_preserves_later_ordinary_preferences(self):
        module.mutate(self.review)
        self.assertEqual(self.ppd.read_bytes(), GENERATED)
        self.current['default_destination'] = 'Another printer'
        self.current['effective_options'] = {'copies': '9'}
        self.current['user_lpoptions_sha256'] = 'new-prefs'
        self.current['settings']['copies-default'] = 9
        before_restore = copy.deepcopy(self.current)
        module.mutate(self.review, restore=True)
        self.assertEqual(self.ppd.read_bytes(), ORIGINAL)
        self.assertEqual(self.current, before_restore)
        self.assertEqual(json.loads((self.review / 'manifest.json').read_text())['status'], 'restored')
        self.assertEqual(sum(call[0] == '/usr/sbin/lpadmin' for call in self.calls), 2)

    def test_restore_keeps_later_unrelated_ppd_edits(self):
        # An OS update that rewrites unrelated lines used to block rollback for
        # good, and overwriting with the reviewed snapshot would have discarded
        # those lines. Rollback now subtracts only the fields it added.
        module.mutate(self.review)
        self.ppd.write_bytes(GENERATED + b'*% Later user edit\n')
        module.mutate(self.review, restore=True)
        self.assertEqual(self.ppd.read_bytes(), ORIGINAL + b'*% Later user edit\n')
        for key in module.SCANNER_KEYS:
            self.assertEqual(module.ppd_values(self.ppd.read_bytes(), key), [])
        self.assertEqual(json.loads((self.review / 'manifest.json').read_text())['status'], 'restored')

    def test_restore_rejects_edited_association_fields_without_another_write(self):
        module.mutate(self.review)
        self.ppd.write_bytes(GENERATED.replace(b'*APICADriver: True', b'*APICADriver: False'))
        with self.assertRaises(module.ReviewError):
            module.mutate(self.review, restore=True)
        self.assertEqual(sum(call[0] == '/usr/sbin/lpadmin' for call in self.calls), 1)

    def test_subtract_association_is_the_exact_inverse_of_derive(self):
        self.assertEqual(module.subtract_association(GENERATED, ORIGINAL, module.SCANNER_KEYS),
                         ORIGINAL)
        # A field the original already carried returns to its original line.
        original = ORIGINAL.replace(b'*APAirPrint: True',
                                    b'*APAirPrint: True\n*APICADriver: False')
        derived, _ = module.derive_ppd(original, GENERATED)
        self.assertEqual(module.subtract_association(derived, original, module.SCANNER_KEYS),
                         original)

    def test_restore_rejects_replaced_queue_identity_without_another_write(self):
        module.mutate(self.review)
        self.current['settings']['device-uri'] = 'dnssd://Other._ipp._tcp.local./?uuid=' + UUID
        with self.assertRaises(module.ReviewError):
            module.mutate(self.review, restore=True)
        self.assertEqual(sum(call[0] == '/usr/sbin/lpadmin' for call in self.calls), 1)

    def test_restore_survives_a_cups_reissued_printer_uuid(self):
        # macOS recreates the queue during an OS update and CUPS hands it a new
        # object id. The printer is the same one, so rollback must still work.
        module.mutate(self.review)
        self.current['settings']['printer-uuid'] = 'urn:uuid:reissued-by-cups'
        module.mutate(self.review, restore=True)
        self.assertEqual(self.ppd.read_bytes(), ORIGINAL)
        self.assertEqual(json.loads((self.review / 'manifest.json').read_text())['status'], 'restored')

    def test_apply_still_rejects_changed_preferences(self):
        self.current['default_destination'] = 'Another printer'
        with self.assertRaises(module.ReviewError):
            module.mutate(self.review)
        self.assertFalse(any(call[0] == '/usr/sbin/lpadmin' for call in self.calls))

    def test_rejected_write_retains_unapplied_review_and_original(self):
        self.fail_apply = True
        with self.assertRaises(module.ReviewError):
            module.mutate(self.review)
        manifest = json.loads((self.review / 'manifest.json').read_text())
        self.assertEqual(manifest['status'], 'reviewed')
        self.assertNotIn('pending_operation', manifest)
        self.assertEqual(self.ppd.read_bytes(), ORIGINAL)

    def test_restore_records_unexpected_post_write_preference_change(self):
        module.mutate(self.review)
        self.alter_preferences_during_write = True
        with self.assertRaises(module.ReviewError):
            module.mutate(self.review, restore=True)
        manifest = json.loads((self.review / 'manifest.json').read_text())
        self.assertEqual(manifest['status'], 'needs-review')
        self.assertEqual(self.ppd.read_bytes(), ORIGINAL)
        self.assertTrue((self.review / 'candidate.ppd').is_file())

    def test_owned_review_apply_restore_and_repeat_removal(self):
        owned = self.root / 'owned-review'
        source_manifest = (self.review / 'manifest.json').read_bytes()
        maintenance.stage(module, self.review, owned, UUID)
        maintenance.apply(module, owned)
        self.current['default_destination'] = 'Another printer'
        maintenance.restore(module, owned)
        maintenance.restore(module, owned)
        self.assertEqual(self.ppd.read_bytes(), ORIGINAL)
        self.assertEqual(self.current['default_destination'], 'Another printer')
        self.assertEqual((self.review / 'manifest.json').read_bytes(), source_manifest)
        self.assertEqual(sum(call[0] == '/usr/sbin/lpadmin' for call in self.calls), 2)

    def test_owned_review_wrong_hardware_rejected_before_copy(self):
        owned = self.root / 'owned-review'
        with self.assertRaises(module.ReviewError):
            maintenance.stage(module, self.review, owned, 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
        self.assertFalse(owned.exists())
        self.assertEqual(self.calls, [])

    def test_owned_review_experimental_toner_rejected(self):
        self.manifest['toner_hook'] = True
        candidate, _ = module.derive_ppd(ORIGINAL, GENERATED, toner=True)
        (self.review / 'candidate.ppd').write_bytes(candidate)
        self.manifest['candidate_sha256'] = module.sha(candidate)
        module.write_manifest(self.review, self.manifest)
        with self.assertRaisesRegex(module.ReviewError, 'experimental toner'):
            maintenance.stage(module, self.review, self.root / 'owned-review', UUID)
        self.assertEqual(self.calls, [])

    def test_uncertain_owned_state_retained_without_blind_restore(self):
        self.manifest['pending_operation'] = 'apply'
        module.write_manifest(self.review, self.manifest)
        with self.assertRaises(module.ReviewError):
            maintenance.restore(module, self.review)
        self.assertEqual(self.calls, [])
        self.assertTrue((self.review / 'original.ppd').is_file())

    def test_staged_removal_never_restores_an_applied_association(self):
        module.mutate(self.review)
        with self.assertRaises(module.ReviewError):
            maintenance.restore(module, self.review, staging=True)
        self.assertEqual(self.ppd.read_bytes(), GENERATED)
        self.assertEqual(sum(call[0] == '/usr/sbin/lpadmin' for call in self.calls), 1)


if __name__ == "__main__":
    unittest.main()
