import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.backup import BackupError, digest, inspect_media, load_manifest


class BackupArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / "media.tar"

    def write_archive(self, entries):
        with tarfile.open(self.archive, "w") as archive:
            for name, content, kind in entries:
                entry = tarfile.TarInfo(name)
                entry.type = kind
                entry.size = len(content) if kind == tarfile.REGTYPE else 0
                if kind == tarfile.SYMTYPE:
                    entry.linkname = "../../outside"
                archive.addfile(entry, io.BytesIO(content))

    def test_restores_exact_file_bytes_and_checksums(self):
        content = b"%PDF-1.7\nprivate-test-file\n"
        self.write_archive([("persons/test/document.pdf", content, tarfile.REGTYPE)])
        expected = {"persons/test/document.pdf": {
            "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
        }}
        restored = self.root / "restored"
        restored.mkdir()
        self.assertEqual(inspect_media(self.archive, expected=expected, destination=restored), expected)
        self.assertEqual((restored / "persons/test/document.pdf").read_bytes(), content)

    def test_rejects_unsafe_paths_links_and_duplicate_entries(self):
        for entries in [
            [("../outside", b"x", tarfile.REGTYPE)],
            [("/outside", b"x", tarfile.REGTYPE)],
            [("persons/../../outside", b"x", tarfile.REGTYPE)],
            [("persons\\outside", b"x", tarfile.REGTYPE)],
            [("linked", b"", tarfile.SYMTYPE)],
            [("file", b"x", tarfile.REGTYPE), ("file", b"y", tarfile.REGTYPE)],
        ]:
            with self.subTest(entries=entries):
                self.write_archive(entries)
                with self.assertRaises(BackupError):
                    inspect_media(self.archive)

    def test_rejects_missing_extra_or_changed_media(self):
        self.write_archive([("document.pdf", b"test", tarfile.REGTYPE)])
        correct = inspect_media(self.archive)
        for expected in [
            {},
            {**correct, "missing.pdf": correct["document.pdf"]},
            {"document.pdf": {"size": 5, "sha256": "0" * 64}},
            {"document.pdf": {"size": 4, "sha256": "0" * 64}},
        ]:
            with self.subTest(expected=expected):
                with self.assertRaises(BackupError):
                    inspect_media(self.archive, expected=expected)

    def test_empty_archive_is_valid_for_database_without_files(self):
        self.write_archive([])
        self.assertEqual(inspect_media(self.archive, expected={}), {})

    def test_dump_corruption_is_detected_before_restore(self):
        self.write_archive([])
        dump = self.root / "database.dump"
        dump.write_bytes(b"test dump")
        manifest = {
            "format_version": 1,
            "postgres_image": "sha256:" + "a" * 64,
            "table_counts": {"heritage_mediaasset": 0},
            "media_files": {},
            "sha256": {"database.dump": digest(dump), "media.tar": digest(self.archive)},
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        self.assertEqual(load_manifest(self.root), manifest)
        dump.write_bytes(b"damaged dump")
        with self.assertRaisesRegex(BackupError, "database.dump"):
            load_manifest(self.root)
