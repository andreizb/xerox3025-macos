#!/usr/bin/env python3
"""Offline checks for the installed diagnostics report.

No printer, queue, service or network device is used: the bundled scanimage is
replaced by a stub that replays recorded protocol bytes.

SPDX-License-Identifier: MIT
"""
import http.server
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Port 1 is reserved and never listening, so curl fails immediately and the
# report takes the "endpoint unavailable" branch.
CLOSED_ENDPOINT = "http://127.0.0.1:1/eSCL/ScannerCapabilities"


class DiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        root = self.tmp / "Xerox3025Bridge"
        self.runtime = root / "runtime"
        (self.runtime / "bin").mkdir(parents=True)
        (self.runtime / "lib/sane").mkdir(parents=True)
        (root / "state/sane.d").mkdir(parents=True)
        self.state = root / "state"
        (self.runtime / "lib/sane/libsane-xerox_mfp.1.so").write_bytes(b"")
        for name in ("airsaned", "discover", "service-lock"):
            (self.runtime / "bin" / name).write_bytes(b"")
        shutil.copy2(ROOT / "packaging/diagnostics", self.runtime / "bin/diagnostics")
        os.chmod(self.runtime / "bin/diagnostics", 0o755)
        self.marker = self.tmp / "scanimage-was-run"

    def stub_scanimage(self, stdout=""):
        path = self.runtime / "bin/scanimage"
        path.write_text(
            "#!/bin/bash\n"
            f"printf 'ran\\n' > {self.marker}\n"
            f"cat <<'OUT' >&2\n{stdout}\nOUT\n"
        )
        os.chmod(path, 0o755)

    def run_diagnostics(self, endpoint=CLOSED_ENDPOINT):
        env = dict(os.environ, XEROX3025_DIAG_ENDPOINT=endpoint)
        done = subprocess.run([str(self.runtime / "bin/diagnostics")],
                              capture_output=True, text=True, env=env, timeout=180)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_busy_status_is_named_with_its_remedy(self):
        self.stub_scanimage("[xerox_mfp] [70] a8 08 43 00...")
        out = self.run_diagnostics()
        self.assertIn("BUSY", out)
        self.assertIn("scan reservation is held", out)
        self.assertIn("disconnect it from mains power", out)

    def test_check_and_cancel_states_are_distinguished(self):
        self.stub_scanimage("[xerox_mfp] [32] a8 02 1d 20")
        self.assertIn("CHECK condition", self.run_diagnostics())
        self.stub_scanimage("[xerox_mfp] [32] a8 04 1d 00")
        self.assertIn("CANCEL state", self.run_diagnostics())

    def test_unreachable_device_is_not_reported_as_busy(self):
        self.stub_scanimage("scanimage: no SANE devices found")
        out = self.run_diagnostics()
        self.assertIn("no protocol reply", out)
        self.assertNotIn("BUSY", out)

    def test_successful_enumeration_blames_the_bridge_not_the_device(self):
        self.stub_scanimage("device `xerox_mfp:tcp host 9400' is a Xerox "
                            "WorkCentre 3025 multi-function peripheral")
        out = self.run_diagnostics()
        self.assertIn("responding", out)
        self.assertIn("fault is local to the bridge", out)

    def test_device_identity_is_never_printed(self):
        self.stub_scanimage("[xerox_mfp] tcp XRXAABBCCDDEEFF.local. 9400\n"
                            "[xerox_mfp] [70] a8 08 43 00...")
        out = self.run_diagnostics()
        self.assertNotIn("XRXAABBCCDDEEFF", out)
        self.assertNotIn("9400", out)

    def test_healthy_endpoint_does_not_touch_the_single_session_device(self):
        self.stub_scanimage("[xerox_mfp] [70] a8 08 43 00...")
        server = http.server.HTTPServer(("127.0.0.1", 0), _OkHandler)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        out = self.run_diagnostics(f"http://127.0.0.1:{server.server_port}/")
        self.assertIn("scan path: healthy", out)
        self.assertFalse(self.marker.exists(),
                         "diagnostics probed the scanner while it was serving")

    def test_report_survives_an_unusable_lipo(self):
        # Files that lipo rejects must not abort the report before its findings.
        self.stub_scanimage("[xerox_mfp] [70] a8 08 43 00...")
        out = self.run_diagnostics()
        self.assertIn("architecture unavailable", out)
        self.assertIn("BUSY", out)

    def test_service_state_line_is_included_and_bounded(self):
        (self.state / "service.state").write_text("x" * 5000)
        self.stub_scanimage("[xerox_mfp] [70] a8 08 43 00...")
        out = self.run_diagnostics()
        self.assertIn("service state:", out)
        self.assertLess(out.count("x"), 500)


class _OkHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    unittest.main()
