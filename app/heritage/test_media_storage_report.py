import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from family.models import Person

from .models import MediaAsset


class MediaStorageReportTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = FileSystemStorage(location=self.root)
        storage_patch = patch.object(MediaAsset._meta.get_field("file"), "storage", self.storage)
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.person = Person.objects.create(first_name="Отчёт хранилища")

    def test_report_finds_missing_orphan_and_symlink_without_deleting(self):
        present = MediaAsset.objects.create(
            person=self.person, title="Есть", media_type="DOCUMENT",
            file=ContentFile(b"present", name="persons/present.pdf"),
        )
        missing = MediaAsset.objects.create(
            person=self.person, title="Нет", media_type="DOCUMENT",
            file="persons/missing.pdf",
        )
        orphan = self.root / "persons" / "orphan.pdf"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b"orphan")
        link = self.root / "persons" / "link.pdf"
        link.symlink_to(orphan)
        output = tempfile.SpooledTemporaryFile(mode="w+")
        try:
            call_command("media_storage_report", "--json", stdout=output)
            output.seek(0)
            report = json.load(output)
        finally:
            output.close()
        self.assertEqual(report["referenced"], 2)
        self.assertEqual(report["files"], 2)
        self.assertEqual(report["missing"], [missing.file.name])
        self.assertEqual(report["orphans"], [orphan.relative_to(self.root).as_posix()])
        self.assertEqual(report["symlinks"], [link.relative_to(self.root).as_posix()])
        self.assertTrue(MediaAsset.objects.filter(id=present.id).exists())
        self.assertTrue(MediaAsset.objects.filter(id=missing.id).exists())

    def test_missing_storage_is_a_command_error(self):
        self.root.rmdir()
        with self.assertRaisesMessage(CommandError, "не существует"):
            call_command("media_storage_report")
