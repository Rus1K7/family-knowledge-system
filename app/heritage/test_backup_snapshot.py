import io
import json
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection
from django.test import TransactionTestCase

from family.models import Person

from .models import MediaAsset


class BackupSnapshotTests(TransactionTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        storage = FileSystemStorage(location=self.root)
        storage_patch = patch.object(MediaAsset._meta.get_field("file"), "storage", storage)
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.person = Person.objects.create(first_name="Тест копирования")
        self.media = MediaAsset.objects.create(
            person=self.person, title="Тестовый документ", media_type="DOCUMENT",
            status="ARCHIVED", file=ContentFile(b"%PDF-test-backup\n", name="test.pdf"),
        )
        self.output = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", write_through=True)
        self.addCleanup(self.output.close)

    def execute_snapshot(self, reply="export-media\n", before_export=None):
        incoming = io.StringIO(reply)

        def ready(*args):
            if before_export:
                before_export()
            return [incoming], [], []

        with patch("heritage.management.commands.backup_snapshot.sys.stdin", incoming):
            with patch("heritage.management.commands.backup_snapshot.select.select", side_effect=ready):
                call_command("backup_snapshot", stdout=self.output)
        return self.output.buffer.getvalue()

    def test_snapshot_includes_archived_media_and_counts(self):
        raw = self.execute_snapshot()
        header, archive = raw.split(b"\n", 1)
        metadata = json.loads(header)
        self.assertEqual(metadata["table_counts"]["heritage_mediaasset"], 1)
        self.assertEqual(metadata["media_names"], [self.media.file.name])
        with tarfile.open(fileobj=io.BytesIO(archive)) as restored:
            self.assertEqual(restored.getnames(), [self.media.file.name])
            self.assertEqual(restored.extractfile(self.media.file.name).read(), b"%PDF-test-backup\n")
        self.assertFalse(connection.in_atomic_block)

    def test_missing_registered_file_aborts_before_export(self):
        self.media.file.storage.delete(self.media.file.name)
        with self.assertRaisesMessage(CommandError, "отсутствует"):
            self.execute_snapshot()
        self.assertEqual(self.output.buffer.getvalue(), b"")
        self.assertTrue(MediaAsset.objects.filter(id=self.media.id).exists())
        self.assertFalse(connection.in_atomic_block)

    def test_symbolic_link_is_not_copied(self):
        target = self.root / "another-file"
        target.write_bytes(b"not a registered file")
        path = self.root / self.media.file.name
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesMessage(CommandError, "символической ссылкой"):
            self.execute_snapshot()
        self.assertEqual(self.output.buffer.getvalue(), b"")

    def test_disconnected_orchestrator_releases_transaction(self):
        with self.assertRaisesMessage(CommandError, "отменено"):
            self.execute_snapshot(reply="")
        self.assertFalse(connection.in_atomic_block)
        self.assertTrue(self.media.file.storage.exists(self.media.file.name))
        self.assertTrue(MediaAsset.objects.filter(id=self.media.id).exists())

    def test_writes_are_blocked_until_export_finishes(self):
        def concurrent_write():
            writer = connection.copy(alias="backup_test_writer")
            try:
                with writer.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '100ms'")
                    with self.assertRaises(DatabaseError):
                        cursor.execute(
                            "UPDATE heritage_mediaasset SET title = 'changed' WHERE id = %s",
                            [self.media.id],
                        )
            finally:
                writer.close()

        self.execute_snapshot(before_export=concurrent_write)
        self.media.refresh_from_db()
        self.assertEqual(self.media.title, "Тестовый документ")
        self.media.title = "Изменение после копирования"
        self.media.save(update_fields=["title"])
        self.media.refresh_from_db()
        self.assertEqual(self.media.title, "Изменение после копирования")
