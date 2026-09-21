import io
import json
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import backup, secure_backup as secure
from scripts.backup import BackupError, digest, run


class SecureBackupSourceTests(unittest.TestCase):
    """Routing tests use synthetic files and never run Docker or read real keys."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.local_output = self.root / "local"
        self.production_output = self.root / "production"
        patches = [
            patch.dict(secure.os.environ, {}, clear=True),
            patch.object(secure, "OUTPUT", self.local_output),
            patch.object(secure, "PRODUCTION_OUTPUT", self.production_output),
            patch.object(secure, "require_age"),
            patch.object(secure, "read_recipient", return_value="synthetic-public-recipient"),
            patch.object(secure, "encrypt_backup", side_effect=self.fake_encrypt),
            patch.object(backup, "run", return_value=b"synthetic-daemon"),
            patch.object(secure.subprocess, "Popen", side_effect=AssertionError("No real commands")),
        ]
        for mock_patch in patches:
            mock_patch.start()
            self.addCleanup(mock_patch.stop)
        create_patch = patch.object(secure, "create_backup", side_effect=self.fake_backup)
        self.create = create_patch.start()
        self.addCleanup(create_patch.stop)
        self.stdout = redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def fake_backup(self, directory, *, production=False):
        directory.mkdir(parents=True)
        (directory / "source").write_text("production" if production else "local")
        (directory / "manifest.json").write_text(json.dumps({
            "source": secure.backup_source(production=production),
        }))
        return directory

    def fake_encrypt(self, source, recipient, target):
        target.write_bytes(b"synthetic encrypted backup: " + (source / "source").read_bytes())

    def test_production_defaults_to_separate_output_and_forwards_selected_source(self):
        local = secure.create_encrypted(daily=True)
        production = secure.create_encrypted(daily=True, production=True)
        self.assertEqual(local.parent, self.local_output)
        self.assertEqual(production.parent, self.production_output)
        self.assertEqual(self.create.call_args_list[0].kwargs, {})
        self.assertEqual(self.create.call_args_list[1].kwargs, {"production": True})
        self.assertEqual(secure.create_encrypted(daily=True), local)
        self.assertEqual(secure.create_encrypted(daily=True, production=True), production)
        self.assertEqual(self.create.call_count, 2)

    def test_daily_shared_output_never_reuses_a_backup_from_the_other_source(self):
        output = self.root / "shared"
        local = secure.create_encrypted(output, daily=True)
        production = secure.create_encrypted(output, daily=True, production=True)
        self.assertNotEqual(local, production)
        self.assertEqual(secure.create_encrypted(output, daily=True, production=True), production)
        next_local = secure.create_encrypted(output, daily=True)
        self.assertNotIn(next_local, [local, production])
        self.assertEqual(self.create.call_count, 3)
        state = json.loads((output / ".daily.json").read_text())
        self.assertEqual(state["source"], secure.backup_source())
        self.assertTrue(local.exists())
        self.assertTrue(production.exists())

    def test_daily_environment_target_changes_require_a_fresh_backup(self):
        for production, variable in [
            (False, "COMPOSE_PROJECT_NAME"), (False, "COMPOSE_FILE"),
            (False, "COMPOSE_PROFILES"), (False, "COMPOSE_ENV_FILES"),
            (True, "FKS_PRODUCTION_ENV_FILE"), (True, "COMPOSE_ENV_FILES"),
        ]:
            with self.subTest(production=production, variable=variable):
                output = self.root / f"{production}-{variable}"
                first = secure.create_encrypted(output, daily=True, production=production)
                with patch.dict(secure.os.environ, {variable: "another-target"}):
                    second = secure.create_encrypted(output, daily=True, production=production)
                    self.assertEqual(
                        secure.create_encrypted(output, daily=True, production=production), second,
                    )
                self.assertNotEqual(first, second)

    def test_legacy_daily_markers_without_source_or_daemon_require_a_new_copy(self):
        output = self.root / "legacy"
        original = secure.create_encrypted(output, daily=True)
        state = json.loads((output / ".daily.json").read_text())
        without_source = {key: value for key, value in state.items() if key != "source"}
        without_daemon = {**state, "source": {
            key: value for key, value in state["source"].items() if key != "docker_daemon_sha256"
        }}
        for legacy in [without_source, without_daemon]:
            for production in [False, True]:
                with self.subTest(production=production, has_source="source" in legacy):
                    (output / ".daily.json").write_text(json.dumps(legacy))
                    created = secure.create_encrypted(output, daily=True, production=production)
                    self.assertNotEqual(created, original)

    def test_daily_daemon_switch_requires_new_backup_even_without_environment_changes(self):
        for production in [False, True]:
            with self.subTest(production=production):
                output = self.root / f"daemon-{production}"
                first = secure.create_encrypted(output, daily=True, production=production)
                with patch.object(backup, "run", return_value=b"another-synthetic-daemon"):
                    second = secure.create_encrypted(output, daily=True, production=production)
                    self.assertEqual(secure.create_encrypted(output, daily=True, production=production), second)
                self.assertNotEqual(first, second)

    def test_daily_unknown_source_does_not_report_success_or_replace_previous_copy(self):
        output = self.root / "unknown"
        previous = secure.create_encrypted(output, daily=True)
        marker = (output / ".daily.json").read_bytes()
        with patch.object(backup, "run", return_value=b""):
            with self.assertRaises(BackupError):
                secure.create_encrypted(output, daily=True)
        self.assertEqual(self.create.call_count, 1)
        self.assertEqual((output / ".daily.json").read_bytes(), marker)
        self.assertEqual(list(output.glob("*.age")), [previous])

    def test_daily_source_switch_during_integrity_check_is_not_accepted(self):
        output = self.root / "daily-race"
        previous = secure.create_encrypted(output, daily=True)
        marker = (output / ".daily.json").read_bytes()
        with patch.object(backup, "run", side_effect=[b"synthetic-daemon", b"another-synthetic-daemon"]):
            with self.assertRaisesRegex(BackupError, "изменился"):
                secure.create_encrypted(output, daily=True)
        self.assertEqual(self.create.call_count, 1)
        self.assertEqual((output / ".daily.json").read_bytes(), marker)
        self.assertEqual(list(output.glob("*.age")), [previous])

    def test_source_switch_after_snapshot_keeps_previous_marker_and_discards_new_copy(self):
        output = self.root / "encryption-race"
        previous = secure.create_encrypted(output)
        marker = (output / ".daily.json").read_bytes()
        with patch.object(backup, "run", side_effect=[b"synthetic-daemon", b"another-synthetic-daemon"]):
            with self.assertRaisesRegex(BackupError, "изменился"):
                secure.create_encrypted(output)
        self.assertEqual((output / ".daily.json").read_bytes(), marker)
        self.assertEqual(list(output.glob("*.age")), [previous])
        self.assertFalse(list(output.glob(".secure-*")))

    def test_create_cli_keeps_existing_calls_and_accepts_production_output(self):
        for arguments, options in [
            (["create"], {"daily": False}),
            (["create", "--daily"], {"daily": True}),
            (["create", "--production", "--daily"], {"daily": True, "production": True}),
            (["create", "--production", "--output", "custom-encrypted"], {
                "daily": False, "production": True, "output": Path("custom-encrypted").resolve(),
            }),
        ]:
            with self.subTest(arguments=arguments), \
                    patch("sys.argv", ["secure_backup.py", *arguments]), \
                    patch.object(secure.os, "umask"), patch.object(secure, "create_encrypted") as create:
                secure.main()
            create.assert_called_once_with(**options)


@unittest.skipUnless(secure.AGE.is_file(), "Install the pinned age tool before running encryption tests")
class SecureBackupTests(unittest.TestCase):
    def setUp(self):
        source_patch = patch.object(secure, "backup_source", return_value={
            "docker_daemon_sha256": "a" * 64, "test_source": "synthetic",
        })
        source_patch.start()
        self.addCleanup(source_patch.stop)
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
        (directory / "manifest.json").write_text(json.dumps({"source": secure.backup_source()}))
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
