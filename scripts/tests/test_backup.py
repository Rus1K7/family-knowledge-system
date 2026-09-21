import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import backup
from scripts.backup import BackupError, digest, inspect_media, load_manifest


class BackupSourceTests(unittest.TestCase):
    def test_local_and_production_snapshot_use_the_same_selected_stack_for_all_steps(self):
        for production, compose in [
            (False, ["docker", "compose"]),
            (True, ["docker", "compose", "-p", "family-production", "-f", "compose.production.yaml"]),
        ]:
            with self.subTest(production=production), tempfile.TemporaryDirectory() as temporary:
                metadata = {
                    "database": "synthetic", "snapshot": "0001-0002-1",
                    "media_names": [], "postgres_major": 18, "table_counts": {"test_table": 0},
                }
                media = io.BytesIO()
                with tarfile.open(fileobj=media, mode="w"):
                    pass
                holder = Mock(
                    stdin=io.BytesIO(),
                    stdout=io.BytesIO(json.dumps(metadata).encode() + b"\n" + media.getvalue()),
                )
                holder.wait.return_value = 0

                def execute(command, **options):
                    if command == ["docker", "info", "--format", "{{.ID}}"]:
                        self.assertEqual(options["timeout"], 10)
                        return b"synthetic-daemon"
                    if command == compose + ["ps", "-q", "db"]:
                        return b"synthetic-db-container\n"
                    if command == ["docker", "inspect", "--format", "{{.Image}}", "synthetic-db-container"]:
                        return ("sha256:" + "a" * 64).encode()
                    self.assertEqual(command[:len(compose)], compose)
                    self.assertEqual(command[len(compose):len(compose) + 3], ["exec", "-T", "db"])
                    if "psql" in command:
                        return b"synthetic\n"
                    self.assertIn("pg_dump", command)
                    self.assertIn("--snapshot=0001-0002-1", command)
                    options["stdout"].write(b"synthetic database dump")
                    return b""

                with patch.object(backup, "run", side_effect=execute) as run_command, \
                        patch.object(backup.subprocess, "Popen", return_value=holder) as process, \
                        redirect_stdout(io.StringIO()):
                    created = backup.create_backup(Path(temporary), production=production)
                    self.assertEqual(run_command.call_count, 6)
                    expected_source = backup.backup_source(production=production)
                self.assertEqual(process.call_args.args[0], compose + [
                    "exec", "-T", "web", "python", "manage.py", "backup_snapshot",
                ])
                manifest = backup.load_manifest(created)
                self.assertEqual(manifest["source"], expected_source)
                self.assertFalse(list(Path(temporary).glob(".incomplete-*")))

    def test_source_context_records_only_routing_environment_without_reading_env_files(self):
        environment = {
            "COMPOSE_PROJECT_NAME": "test-project", "COMPOSE_FILE": "compose.test.yaml",
            "COMPOSE_PROFILES": "test", "FKS_PRODUCTION_ENV_FILE": "/missing/test-production.env",
            "POSTGRES_PASSWORD": "must-not-appear", "DJANGO_SECRET_KEY": "must-not-appear",
        }
        with patch.dict(backup.os.environ, environment, clear=True), \
                patch.object(backup, "run", return_value=b"synthetic-daemon"), \
                patch.object(Path, "read_text", side_effect=AssertionError("No env files should be read")):
            local = backup.backup_source()
            production = backup.backup_source(production=True)
        self.assertEqual(local["compose_environment"], {
            key: value for key, value in environment.items() if key.startswith("COMPOSE_")
        })
        self.assertEqual(production["environment_file"], "/missing/test-production.env")
        self.assertNotIn("must-not-appear", json.dumps([local, production]))
        self.assertNotIn("synthetic-daemon", json.dumps([local, production]))
        self.assertEqual(local["docker_daemon_sha256"], hashlib.sha256(b"synthetic-daemon").hexdigest())

    def test_source_changes_with_selected_daemon_without_exposing_its_identity(self):
        with patch.dict(backup.os.environ, {}, clear=True), \
                patch.object(backup, "run", side_effect=[b"synthetic-daemon-a", b"synthetic-daemon-b"]) as run:
            first = backup.backup_source(production=True)
            second = backup.backup_source(production=True)
        self.assertNotEqual(first, second)
        self.assertNotIn("synthetic-daemon", json.dumps([first, second]))
        for call in run.call_args_list:
            self.assertEqual(call.args, (["docker", "info", "--format", "{{.ID}}"],))
            self.assertEqual(call.kwargs, {"timeout": 10})

    def test_unknown_daemon_fails_closed_without_disclosing_diagnostics(self):
        failures = [
            b"", b"\n", b"<no value>", b"invalid identifier",
            BackupError("private diagnostic", diagnostic=b"private diagnostic"),
            OSError("private diagnostic"), subprocess.TimeoutExpired("private diagnostic", 10),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(backup, "run", **(
                        {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
                    )):
                with self.assertRaises(BackupError) as raised:
                    backup.backup_source()
                self.assertNotIn("private diagnostic", str(raised.exception))
                self.assertEqual(raised.exception.diagnostic, b"")

    def test_source_switch_during_raw_snapshot_discards_new_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            metadata = {
                "database": "synthetic", "snapshot": "0001-0002-1",
                "media_names": [], "postgres_major": 18, "table_counts": {"test_table": 0},
            }
            media = io.BytesIO()
            with tarfile.open(fileobj=media, mode="w"):
                pass
            holder = Mock(
                stdin=io.BytesIO(),
                stdout=io.BytesIO(json.dumps(metadata).encode() + b"\n" + media.getvalue()),
            )
            holder.wait.return_value = 0
            daemons = iter([b"synthetic-daemon-a", b"synthetic-daemon-b"])

            def execute(command, **options):
                if "info" in command:
                    return next(daemons)
                if "ps" in command:
                    return b"synthetic-db-container"
                if "inspect" in command:
                    return ("sha256:" + "a" * 64).encode()
                if "psql" in command:
                    return b"synthetic"
                self.assertIn("pg_dump", command)
                options["stdout"].write(b"synthetic database dump")
                return b""

            with patch.object(backup, "run", side_effect=execute), \
                    patch.object(backup.subprocess, "Popen", return_value=holder):
                with self.assertRaisesRegex(BackupError, "изменился"):
                    backup.create_backup(Path(temporary), production=True)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_create_cli_uses_separate_defaults_and_respects_explicit_output(self):
        for arguments, expected, options in [
            (["create"], backup.OUTPUT, {}),
            (["create", "--production"], backup.PRODUCTION_OUTPUT, {"production": True}),
            (["create", "--production", "--output", "custom-backups"], Path("custom-backups"), {"production": True}),
        ]:
            with self.subTest(arguments=arguments), \
                    patch("sys.argv", ["backup.py", *arguments]), \
                    patch.object(backup.os, "umask"), patch.object(backup, "create_backup") as create:
                backup.main()
            create.assert_called_once_with(expected.resolve(), **options)


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
