import io
import json
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import secure_backup as secure
from scripts.backup import BackupError, digest, run


@unittest.skipUnless(secure.AGE.is_file(), "Install the pinned age tool before running encryption tests")
class SecureBackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.keys = self.root / "keys"
        with redirect_stdout(io.StringIO()):
            secure.initialize_keys(self.keys)
        self.identity = self.keys / "backup.agekey"
        self.recipient_path = self.keys / "backup-recipient.txt"
        self.recipient = secure.read_recipient(self.recipient_path)
        self.raw = self.fake_backup(self.root / "raw")

    def fake_backup(self, directory):
        directory.mkdir(mode=0o700, parents=True)
        for name in secure.CONTENTS:
            (directory / name).write_bytes(b"private synthetic backup: " + name.encode())
        return directory

    def encrypted(self):
        encrypted = self.root / "backup.age"
        secure.encrypt_backup(self.raw, self.recipient, encrypted)
        return encrypted

    def test_age_roundtrip_preserves_all_bytes(self):
        encrypted = self.encrypted()
        self.assertNotIn(b"private synthetic backup", encrypted.read_bytes())
        restored = self.root / "restored"
        secure.decrypt_backup(encrypted, self.identity, restored)
        self.assertEqual({p.name for p in restored.iterdir()}, secure.CONTENTS)
        for name in secure.CONTENTS:
            self.assertEqual((self.raw / name).read_bytes(), (restored / name).read_bytes())

    def test_wrong_key_and_damaged_ciphertext_are_rejected_before_extraction(self):
        encrypted = self.encrypted()
        with redirect_stdout(io.StringIO()):
            secure.initialize_keys(self.root / "other-keys")
        restored = self.root / "restored"
        with self.assertRaises(BackupError):
            secure.decrypt_backup(encrypted, self.root / "other-keys/backup.agekey", restored)
        self.assertFalse(restored.exists())
        original = encrypted.read_bytes()
        damaged = original[:-1] + bytes([original[-1] ^ 1])
        for content in [original[:-10], damaged]:
            encrypted.write_bytes(content)
            with self.assertRaises(BackupError):
                secure.decrypt_backup(encrypted, self.identity, restored)
            self.assertFalse(restored.exists())
        self.assertFalse(list(self.root.glob(".decrypt-*")))

    def test_existing_recovery_key_is_preserved_and_missing_key_is_not_replaced(self):
        previous = digest(self.identity)
        with redirect_stdout(io.StringIO()):
            secure.initialize_keys(self.keys)
        self.assertEqual(digest(self.identity), previous)
        self.identity.rename(self.root / "saved-identity")
        with self.assertRaises(BackupError):
            secure.initialize_keys(self.keys)
        self.assertFalse(self.identity.exists())
        self.assertEqual(digest(self.root / "saved-identity"), previous)

    def test_decrypted_bundle_cannot_extract_unexpected_paths(self):
        payload = self.root / "unsafe.tar"
        with tarfile.open(payload, "w") as archive:
            entry = tarfile.TarInfo("../escaped")
            entry.size = 4
            archive.addfile(entry, io.BytesIO(b"test"))
        encrypted = self.root / "unsafe.age"
        with encrypted.open("xb") as output:
            run([str(secure.AGE), "-r", self.recipient, str(payload)], stdout=output)
        with self.assertRaises(BackupError):
            secure.decrypt_backup(encrypted, self.identity, self.root / "restored")
        self.assertFalse((self.root / "escaped").exists())

    def test_daily_run_skips_only_a_complete_unchanged_copy(self):
        output = self.root / "output"
        with patch.object(secure, "create_backup", side_effect=self.fake_backup) as create:
            with redirect_stdout(io.StringIO()):
                first = secure.create_encrypted(output, self.recipient_path, daily=True)
                second = secure.create_encrypted(output, self.recipient_path, daily=True)
                self.assertEqual(first, second)
                self.assertEqual(create.call_count, 1)
                first.write_bytes(b"damaged")
                third = secure.create_encrypted(output, self.recipient_path, daily=True)
        self.assertNotEqual(first, third)
        self.assertTrue(first.exists())
        self.assertTrue(third.exists())
        state = json.loads((output / ".daily.json").read_text())
        self.assertEqual(state["sha256"], digest(third))
        self.assertFalse(list(output.glob(".secure-*")))

    def test_encryption_failure_preserves_last_copy_and_removes_temporary_plaintext(self):
        output = self.root / "output"
        with patch.object(secure, "create_backup", side_effect=self.fake_backup):
            with redirect_stdout(io.StringIO()):
                previous = secure.create_encrypted(output, self.recipient_path)
            checksum = digest(previous)
            state = (output / ".daily.json").read_bytes()
            with patch.object(secure, "encrypt_backup", side_effect=BackupError("test failure")):
                with self.assertRaises(BackupError):
                    secure.create_encrypted(output, self.recipient_path)
        self.assertEqual(digest(previous), checksum)
        self.assertEqual((output / ".daily.json").read_bytes(), state)
        self.assertEqual(list(output.glob("*.age")), [previous])
        self.assertFalse(list(output.glob(".secure-*")))

    def test_overlapping_run_does_not_start_second_database_snapshot(self):
        output = self.root / "output"
        with secure.backup_lock(output):
            with patch.object(secure, "create_backup") as create:
                with self.assertRaises(BackupError):
                    secure.create_encrypted(output, self.recipient_path)
                create.assert_not_called()
