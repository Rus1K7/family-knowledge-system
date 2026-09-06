from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.db import transaction
from django.test import TransactionTestCase

from accounts.models import User
from family.models import Person
from privacy.models import AccessGrant, PrivacyPolicy

from .models import Biography, MediaAsset, Source, SourceLink


class MediaFileCleanupTests(TransactionTestCase):
    def setUp(self):
        # Exercise real commits and rollbacks, but never touch the private archive.
        self.storage = InMemoryStorage()
        storage_patch = patch.object(
            MediaAsset._meta.get_field("file"), "storage", self.storage,
        )
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.person = Person.objects.create(first_name="Тестовый профиль")
        self.person_id = self.person.id
        self.document = self.create_document("Документ")
        self.document_id = self.document.id
        self.file_name = self.document.file.name
        self.biography = Biography.objects.create(
            person=self.person, text="Тестовая биография",
        )
        self.source = Source.objects.create(
            title="Семейное свидетельство",
            source_type=Source.SourceType.DOCUMENT,
            document=self.document,
        )
        self.link = SourceLink.objects.create(
            source=self.source,
            resource_type=SourceLink.ResourceType.BIOGRAPHY,
            object_id=self.biography.id,
        )
        self.policy = PrivacyPolicy.objects.get(
            resource_type="MEDIA_ASSET", object_id=self.document_id,
        )
        user = User.objects.create_user(username="cleanup-grantee")
        self.grant = AccessGrant.objects.create(policy=self.policy, grantee=user)

    def create_document(self, title):
        return MediaAsset.objects.create(
            person=self.person,
            title=title,
            media_type=MediaAsset.MediaType.DOCUMENT,
            status=MediaAsset.Status.APPROVED,
            file=ContentFile(b"%PDF-1.7\n%%EOF\n", name="test.pdf"),
        )

    def assert_document_preserved(self):
        self.assertTrue(MediaAsset.objects.filter(id=self.document_id).exists())
        self.assertTrue(self.storage.exists(self.file_name))
        with self.storage.open(self.file_name, "rb") as stored_file:
            self.assertEqual(stored_file.read(), b"%PDF-1.7\n%%EOF\n")
        self.source.refresh_from_db()
        self.assertEqual(self.source.document_id, self.document_id)
        self.assertTrue(SourceLink.objects.filter(id=self.link.id).exists())
        self.assertTrue(PrivacyPolicy.objects.filter(id=self.policy.id).exists())
        self.assertTrue(AccessGrant.objects.filter(id=self.grant.id).exists())

    def test_rollback_preserves_document_file_source_and_access(self):
        with self.assertRaisesMessage(RuntimeError, "cancel deletion"):
            with transaction.atomic():
                self.document.delete()
                raise RuntimeError("cancel deletion")

        self.assert_document_preserved()

    def test_file_is_deleted_only_after_outer_transaction_commits(self):
        with transaction.atomic():
            with transaction.atomic():
                self.document.delete()
            self.assertTrue(self.storage.exists(self.file_name))
            self.assertFalse(MediaAsset.objects.filter(id=self.document_id).exists())
            self.source.refresh_from_db()
            self.assertIsNone(self.source.document_id)

        self.assertFalse(self.storage.exists(self.file_name))
        self.assertEqual(self.source.title, "Семейное свидетельство")
        self.assertTrue(SourceLink.objects.filter(id=self.link.id).exists())
        self.assertFalse(PrivacyPolicy.objects.filter(id=self.policy.id).exists())
        self.assertFalse(AccessGrant.objects.filter(id=self.grant.id).exists())

    def test_savepoint_rollback_cancels_file_deletion(self):
        with transaction.atomic():
            with self.assertRaisesMessage(RuntimeError, "cancel savepoint"):
                with transaction.atomic():
                    self.document.delete()
                    raise RuntimeError("cancel savepoint")
            self.assert_document_preserved()

        self.assert_document_preserved()

    def test_person_deletion_rollback_preserves_archive(self):
        with self.assertRaisesMessage(RuntimeError, "cancel person deletion"):
            with transaction.atomic():
                self.person.delete()
                raise RuntimeError("cancel person deletion")

        self.assertTrue(Person.objects.filter(id=self.person_id).exists())
        self.assert_document_preserved()

    def test_person_deletion_cleans_file_after_commit(self):
        with transaction.atomic():
            self.person.delete()
            self.assertTrue(self.storage.exists(self.file_name))

        self.assertFalse(self.storage.exists(self.file_name))
        self.assertFalse(MediaAsset.objects.filter(id=self.document_id).exists())
        self.source.refresh_from_db()
        self.assertIsNone(self.source.document_id)
        self.assertEqual(self.source.title, "Семейное свидетельство")
        self.assertFalse(SourceLink.objects.filter(id=self.link.id).exists())

    def test_bulk_deletion_cleans_each_file_after_commit(self):
        second = self.create_document("Второй документ")
        file_names = [self.file_name, second.file.name]
        self.assertNotEqual(*file_names)
        with transaction.atomic():
            MediaAsset.objects.filter(id__in=[self.document_id, second.id]).delete()
            for name in file_names:
                self.assertTrue(self.storage.exists(name))

        for name in file_names:
            self.assertFalse(self.storage.exists(name))

    def test_record_without_file_does_not_schedule_cleanup(self):
        empty = MediaAsset.objects.create(
            person=self.person, title="Без файла", media_type="DOCUMENT",
        )
        with patch("heritage.signals.transaction.on_commit") as on_commit:
            with patch.object(self.storage, "delete") as delete_file:
                empty.delete()
        on_commit.assert_not_called()
        delete_file.assert_not_called()
        self.assertTrue(self.storage.exists(self.file_name))

    def test_missing_file_does_not_prevent_record_deletion(self):
        self.storage.delete(self.file_name)
        self.document.delete()
        self.assertFalse(MediaAsset.objects.filter(id=self.document_id).exists())
        self.source.refresh_from_db()
        self.assertIsNone(self.source.document_id)

    def test_storage_error_is_logged_without_interrupting_later_cleanup(self):
        second = self.create_document("Второй документ")
        delete_file = self.storage.delete

        def fail_first_file(name):
            if name == self.file_name:
                raise OSError("storage unavailable")
            return delete_file(name)

        with patch.object(self.storage, "delete", side_effect=fail_first_file):
            with self.assertLogs("heritage.signals", level="ERROR") as logs:
                with transaction.atomic():
                    self.document.delete()
                    second.delete()

        self.assertIn(str(self.document_id), logs.output[0])
        self.assertTrue(self.storage.exists(self.file_name))
        self.assertFalse(self.storage.exists(second.file.name))
        self.assertFalse(MediaAsset.objects.filter(id=self.document_id).exists())
        self.source.refresh_from_db()
        self.assertIsNone(self.source.document_id)
