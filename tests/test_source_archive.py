"""Source-export privacy tests. No printer or installed state is accessed."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("source_archive", Path(__file__).resolve().parents[1] / "scripts/source_archive.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "packaging").mkdir()
        (self.root / "packaging/device.example.json").write_text('{"example": true}')
        (self.root / "packaging/device.json").write_text("PRIVATE IDENTITY")
        (self.root / "packaging/custom-printer.json").write_text("ALSO PRIVATE")
        (self.root / "source-files.txt").write_text("packaging/device.example.json\n")

    def test_only_allowlisted_source_is_exported(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            module.add_project_sources(archive, self.root)
        output.seek(0)
        with tarfile.open(fileobj=output) as archive:
            self.assertEqual(archive.getnames(), ["printer-modernization/packaging/device.example.json"])
            self.assertEqual(archive.getmembers()[0].uname, "")
        self.assertNotIn(b"PRIVATE", output.getvalue())

    def test_rejects_private_paths_traversal_duplicates_and_missing_files(self):
        for entry in ("packaging/device.json", "../outside", "/absolute", "missing",
                      "packaging/device.example.json\npackaging/device.example.json"):
            with self.subTest(entry=entry):
                (self.root / "source-files.txt").write_text(entry + "\n")
                with self.assertRaises(ValueError):
                    module.source_paths(self.root)

    def test_rejects_symlinked_source_and_ancestor(self):
        (self.root / "link.json").symlink_to(self.root / "packaging/device.json")
        (self.root / "linked-directory").symlink_to(self.root / "packaging")
        for name in ("link.json", "linked-directory/device.example.json"):
            (self.root / "source-files.txt").write_text(name + "\n")
            with self.assertRaises(ValueError):
                module.source_paths(self.root)

    def test_real_manifest_lists_existing_safe_sources(self):
        self.assertTrue(module.source_paths(Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    unittest.main()
