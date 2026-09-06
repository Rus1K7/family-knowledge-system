from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from family.models import Person, ProfileOwnership

from .forms import ExistingSourceLinkForm, MediaAssetUploadForm
from .models import (
    Biography,
    LifeEvent,
    MediaAsset,
    Source,
    SourceLink,
    Verification,
)
from .storage import private_media_storage


class MediaAssetUploadFormTests(SimpleTestCase):
    def build_form(
        self,
        *,
        filename,
        content,
        content_type,
        media_type=MediaAsset.MediaType.PHOTO,
    ):
        uploaded_file = SimpleUploadedFile(
            filename,
            content,
            content_type=content_type,
        )

        return MediaAssetUploadForm(
            data={
                "media_type": media_type,
                "title": "Тестовый файл",
                "description": "",
            },
            files={
                "file": uploaded_file,
            },
        )

    def test_valid_jpeg_is_accepted_and_mime_is_verified(self):
        form = self.build_form(
            filename="family.jpg",
            content=b"\xff\xd8\xff\xe0test-image",
            content_type="image/jpeg",
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["file"].verified_content_type,
            "image/jpeg",
        )

    def test_valid_pdf_document_is_accepted(self):
        form = self.build_form(
            filename="document.pdf",
            content=b"%PDF-1.7\n1 0 obj\n",
            content_type="application/pdf",
            media_type=MediaAsset.MediaType.DOCUMENT,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_spoofed_image_is_rejected(self):
        form = self.build_form(
            filename="malware.jpg",
            content=b"not-an-image",
            content_type="image/jpeg",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_wrong_extension_is_rejected(self):
        form = self.build_form(
            filename="image.pdf",
            content=b"\xff\xd8\xff\xe0test-image",
            content_type="image/jpeg",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_pdf_cannot_be_uploaded_as_photo(self):
        form = self.build_form(
            filename="document.pdf",
            content=b"%PDF-1.7\n1 0 obj\n",
            content_type="application/pdf",
            media_type=MediaAsset.MediaType.PHOTO,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)


class HistoricalResourceCleanupTests(TestCase):
    def setUp(self):
        self.person = Person.objects.create(
            first_name="Исторический",
            last_name="Профиль",
        )
        self.source = Source.objects.create(
            title="Семейный архив",
            source_type=Source.SourceType.ARCHIVE,
        )

    def add_metadata(self, resource, resource_type):
        SourceLink.objects.create(
            source=self.source,
            resource_type=resource_type,
            object_id=resource.id,
        )
        Verification.objects.create(
            resource_type=resource_type,
            object_id=resource.id,
        )

    def test_deleting_biography_removes_links_and_verification(self):
        biography = Biography.objects.create(
            person=self.person,
            text="Биография",
        )
        self.add_metadata(
            biography,
            SourceLink.ResourceType.BIOGRAPHY,
        )

        biography.delete()

        self.assertFalse(SourceLink.objects.exists())
        self.assertFalse(Verification.objects.exists())
        self.assertTrue(
            Source.objects.filter(id=self.source.id).exists()
        )

    def test_deleting_life_event_removes_links_and_verification(self):
        event = LifeEvent.objects.create(
            person=self.person,
            title="Событие",
        )
        self.add_metadata(
            event,
            SourceLink.ResourceType.LIFE_EVENT,
        )

        event.delete()

        self.assertFalse(SourceLink.objects.exists())
        self.assertFalse(Verification.objects.exists())
        self.assertTrue(
            Source.objects.filter(id=self.source.id).exists()
        )

    def test_deleting_media_asset_removes_private_file(self):
        media_asset = MediaAsset.objects.create(
            person=self.person,
            media_type=MediaAsset.MediaType.DOCUMENT,
            title="Документ для очистки",
        )
        media_asset.file.save(
            "cleanup.pdf",
            ContentFile(b"%PDF-1.7\n"),
            save=True,
        )
        stored_name = media_asset.file.name
        self.addCleanup(private_media_storage.delete, stored_name)
        self.assertTrue(private_media_storage.exists(stored_name))

        with self.captureOnCommitCallbacks(execute=True):
            media_asset.delete()
            self.assertTrue(private_media_storage.exists(stored_name))

        self.assertFalse(private_media_storage.exists(stored_name))


class HeritageMutationAuditTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="heritage-owner",
            email="heritage-owner@example.com",
            password="Heritage-test-password-418!",
        )
        self.person = Person.objects.create(
            first_name="Анна",
            last_name="Архивная",
        )
        ProfileOwnership.objects.create(
            user=self.owner,
            person=self.person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        self.biography = Biography.objects.create(
            person=self.person,
            text="Биография для источников",
        )
        self.client.force_login(self.owner)

    def source_url(self, view_name):
        return reverse(
            f"heritage:{view_name}",
            args=[
                SourceLink.ResourceType.BIOGRAPHY,
                self.biography.id,
            ],
        )

    def assert_resource_event(self, action):
        events = AuditEvent.objects.filter(action=action)
        self.assertEqual(events.count(), 1)

        event = events.get()
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.person, self.person)
        self.assertEqual(
            event.resource_type,
            SourceLink.ResourceType.BIOGRAPHY,
        )
        self.assertEqual(event.object_id, self.biography.id)

        return event

    def assert_source_ids(self, event, source, source_link):
        self.assertEqual(
            event.details["source_id"],
            str(source.id),
        )
        self.assertEqual(
            event.details["source_link_id"],
            str(source_link.id),
        )
        self.assertIsInstance(event.details["source_id"], str)
        self.assertIsInstance(
            event.details["source_link_id"],
            str,
        )

    def test_media_upload_logs_safe_metadata(self):
        file_content = b"\xff\xd8\xff\xe0test-image"
        secret_filename = "private-family-secret.jpg"

        response = self.client.post(
            reverse(
                "heritage:upload_media_asset",
                args=[self.person.id],
            ),
            {
                "media_type": MediaAsset.MediaType.PHOTO,
                "title": "Секретная подпись фотографии",
                "description": (
                    "Секретное описание фотографии"
                ),
                "file": SimpleUploadedFile(
                    secret_filename,
                    file_content,
                    content_type="image/jpeg",
                ),
            },
        )

        self.assertEqual(response.status_code, 302)
        media_asset = MediaAsset.objects.get(person=self.person)
        self.addCleanup(media_asset.file.delete, save=False)
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.UPLOAD_MEDIA,
        )
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.person, self.person)
        self.assertEqual(event.resource_type, "MEDIA_ASSET")
        self.assertEqual(event.object_id, media_asset.id)
        self.assertEqual(
            event.details,
            {
                "media_type": MediaAsset.MediaType.PHOTO,
                "mime_type": "image/jpeg",
                "file_size": len(file_content),
                "status": MediaAsset.Status.PENDING,
            },
        )
        self.assertNotIn(secret_filename, str(event.details))

    def test_owner_can_archive_media_and_archived_file_is_hidden(self):
        media_asset = MediaAsset.objects.create(
            person=self.person,
            media_type=MediaAsset.MediaType.PHOTO,
            title="Фото для архива",
            uploaded_by=self.owner,
            status=MediaAsset.Status.APPROVED,
        )
        media_asset.file.save(
            "archive.jpg",
            ContentFile(b"\xff\xd8\xff\xe0archive-image"),
            save=True,
        )
        stored_name = media_asset.file.name
        self.addCleanup(private_media_storage.delete, stored_name)

        response = self.client.post(
            reverse(
                "heritage:archive_media_asset",
                args=[media_asset.id],
            )
        )

        self.assertEqual(response.status_code, 302)
        media_asset.refresh_from_db()
        self.assertEqual(
            media_asset.status,
            MediaAsset.Status.ARCHIVED,
        )
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.ARCHIVE_MEDIA,
        )
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.object_id, media_asset.id)
        self.assertEqual(
            event.details,
            {
                "previous_status": MediaAsset.Status.APPROVED,
                "status": MediaAsset.Status.ARCHIVED,
            },
        )

        response = self.client.get(
            reverse(
                "heritage:serve_media_asset",
                args=[media_asset.id],
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_owner_can_edit_media_metadata_and_audit_field_names(self):
        media_asset = MediaAsset.objects.create(
            person=self.person,
            media_type=MediaAsset.MediaType.PHOTO,
            title="Старое название",
            description="PRIVATE OLD DESCRIPTION",
            status=MediaAsset.Status.APPROVED,
            uploaded_by=self.owner,
        )

        payload = {
            "title": "Новое название",
            "description": "PRIVATE NEW DESCRIPTION",
        }
        response = self.client.post(
            reverse(
                "heritage:edit_media_asset",
                args=[media_asset.id],
            ),
            payload,
        )

        self.assertEqual(response.status_code, 302)
        media_asset.refresh_from_db()
        self.assertEqual(media_asset.title, "Новое название")
        self.assertEqual(
            media_asset.description,
            "PRIVATE NEW DESCRIPTION",
        )
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.UPDATE_MEDIA,
        )
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.person, self.person)
        self.assertEqual(event.object_id, media_asset.id)
        self.assertEqual(
            event.details,
            {
                "media_id": str(media_asset.id),
                "changed_fields": ["description", "title"],
            },
        )
        self.assertNotIn("PRIVATE", str(event.details))

        repeat_response = self.client.post(
            reverse(
                "heritage:edit_media_asset",
                args=[media_asset.id],
            ),
            payload,
        )
        self.assertEqual(repeat_response.status_code, 302)
        self.assertEqual(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.UPDATE_MEDIA,
            ).count(),
            1,
        )

    def test_non_owner_cannot_edit_media_metadata(self):
        outsider = User.objects.create_user(
            username="media-editor-outsider",
            email="media-editor-outsider@example.com",
            password="Media-editor-password-933!",
        )
        media_asset = MediaAsset.objects.create(
            person=self.person,
            media_type=MediaAsset.MediaType.PHOTO,
            title="Только владелец",
            status=MediaAsset.Status.APPROVED,
            uploaded_by=self.owner,
        )
        self.client.force_login(outsider)

        response = self.client.post(
            reverse(
                "heritage:edit_media_asset",
                args=[media_asset.id],
            ),
            {"title": "Чужая правка", "description": ""},
        )

        self.assertEqual(response.status_code, 403)
        media_asset.refresh_from_db()
        self.assertEqual(media_asset.title, "Только владелец")

    def test_invalid_media_upload_does_not_log_event(self):
        response = self.client.post(
            reverse(
                "heritage:upload_media_asset",
                args=[self.person.id],
            ),
            {
                "media_type": MediaAsset.MediaType.PHOTO,
                "title": "Некорректный файл",
                "description": "Не должен сохраниться",
                "file": SimpleUploadedFile(
                    "spoofed-private.jpg",
                    b"not-an-image",
                    content_type="image/jpeg",
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MediaAsset.objects.exists())
        self.assertFalse(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.UPLOAD_MEDIA,
            ).exists()
        )

    @patch(
        "heritage.views.log_audit_event",
        side_effect=RuntimeError("audit unavailable"),
    )
    def test_media_audit_failure_removes_file_and_rolls_back(
        self,
        mocked_log,
    ):
        with patch.object(
            private_media_storage,
            "delete",
            wraps=private_media_storage.delete,
        ) as mocked_delete:
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse(
                        "heritage:upload_media_asset",
                        args=[self.person.id],
                    ),
                    {
                        "media_type": MediaAsset.MediaType.PHOTO,
                        "title": "Файл для отката",
                        "description": "",
                        "file": SimpleUploadedFile(
                            "rollback.jpg",
                            b"\xff\xd8\xff\xe0rollback-image",
                            content_type="image/jpeg",
                        ),
                    },
                )

        self.assertFalse(MediaAsset.objects.exists())
        mocked_log.assert_called_once()
        mocked_delete.assert_called_once()
        deleted_name = mocked_delete.call_args.args[0]
        self.assertFalse(
            private_media_storage.exists(deleted_name)
        )

    def test_create_source_logs_source_and_initial_link_once(self):
        secret_url = "https://example.com/private-family-archive"
        secret_source_note = "PRIVATE SOURCE NOTE"
        secret_link_note = "PRIVATE LINK NOTE"

        response = self.client.post(
            self.source_url("create_source_for_resource"),
            {
                "source_type": Source.SourceType.WEBSITE,
                "title": "Закрытый семейный источник",
                "author": "Частный рассказчик",
                "source_date": "2020-01-02",
                "url": secret_url,
                "citation": "Закрытая цитата",
                "notes": secret_source_note,
                "relation_type": SourceLink.RelationType.SUPPORTS,
                "link_note": secret_link_note,
            },
        )

        self.assertEqual(response.status_code, 302)
        source = Source.objects.get(
            title="Закрытый семейный источник"
        )
        source_link = SourceLink.objects.get(source=source)
        event = self.assert_resource_event(
            AuditEvent.Action.CREATE_SOURCE
        )
        self.assert_source_ids(event, source, source_link)
        self.assertEqual(
            event.details,
            {
                "source_id": str(source.id),
                "source_link_id": str(source_link.id),
                "source_type": Source.SourceType.WEBSITE,
                "relation_type": SourceLink.RelationType.SUPPORTS,
            },
        )
        self.assertNotIn(secret_url, str(event.details))
        self.assertNotIn(secret_source_note, str(event.details))
        self.assertNotIn(secret_link_note, str(event.details))

    def test_invalid_source_form_does_not_create_or_log(self):
        response = self.client.post(
            self.source_url("create_source_for_resource"),
            {
                "source_type": Source.SourceType.ARCHIVE,
                "title": "",
                "relation_type": SourceLink.RelationType.SUPPORTS,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Source.objects.exists())
        self.assertFalse(SourceLink.objects.exists())
        self.assertFalse(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.CREATE_SOURCE,
            ).exists()
        )

    def test_source_creator_can_edit_metadata_and_audit_field_names(self):
        source = Source.objects.create(
            title="Старое название",
            source_type=Source.SourceType.ARCHIVE,
            author="Старый автор",
            notes="PRIVATE OLD NOTES",
            created_by=self.owner,
        )
        SourceLink.objects.create(
            source=source,
            resource_type=SourceLink.ResourceType.BIOGRAPHY,
            object_id=self.biography.id,
        )

        response = self.client.post(
            reverse("heritage:edit_source", args=[source.id]),
            {
                "source_type": Source.SourceType.BOOK,
                "title": "Новое название",
                "author": "Новый автор",
                "source_date": "2024-05-06",
                "url": "https://example.com/private-source",
                "citation": "PRIVATE CITATION",
                "notes": "PRIVATE NEW NOTES",
            },
        )

        self.assertEqual(response.status_code, 302)
        source.refresh_from_db()
        self.assertEqual(source.title, "Новое название")
        self.assertEqual(source.source_type, Source.SourceType.BOOK)
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.UPDATE_SOURCE,
        )
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.person, self.person)
        self.assertEqual(event.object_id, source.id)
        self.assertEqual(
            event.details,
            {
                "source_id": str(source.id),
                "changed_fields": [
                    "author",
                    "citation",
                    "notes",
                    "source_date",
                    "source_type",
                    "title",
                    "url",
                ],
            },
        )
        self.assertNotIn("PRIVATE", str(event.details))

    def test_non_creator_cannot_edit_source(self):
        member = User.objects.create_user(
            username="source-editor-outsider",
            email="source-editor-outsider@example.com",
            password="Source-editor-password-648!",
        )
        source = Source.objects.create(
            title="Закрытый источник",
            source_type=Source.SourceType.ARCHIVE,
            created_by=self.owner,
        )
        self.client.force_login(member)

        response = self.client.post(
            reverse("heritage:edit_source", args=[source.id]),
            {
                "source_type": Source.SourceType.BOOK,
                "title": "Чужая правка",
            },
        )

        self.assertEqual(response.status_code, 403)
        source.refresh_from_db()
        self.assertEqual(source.title, "Закрытый источник")

    def test_source_creator_can_archive_source_and_hide_links(self):
        source = Source.objects.create(
            title="Архивный источник",
            source_type=Source.SourceType.ARCHIVE,
            created_by=self.owner,
        )
        SourceLink.objects.create(
            source=source,
            resource_type=SourceLink.ResourceType.BIOGRAPHY,
            object_id=self.biography.id,
        )

        response = self.client.post(
            reverse("heritage:archive_source", args=[source.id]),
        )

        self.assertEqual(response.status_code, 302)
        source.refresh_from_db()
        self.assertEqual(source.status, Source.Status.ARCHIVED)
        self.assertTrue(
            SourceLink.objects.filter(source=source).exists()
        )
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.ARCHIVE_SOURCE,
        )
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.person, self.person)
        self.assertEqual(event.object_id, source.id)
        self.assertEqual(
            event.details,
            {
                "source_id": str(source.id),
                "previous_status": Source.Status.ACTIVE,
                "status": Source.Status.ARCHIVED,
            },
        )

        response = self.client.get(
            reverse(
                "family:person_detail",
                args=[self.person.id],
            )
        )
        self.assertNotContains(response, "Архивный источник")

        form = ExistingSourceLinkForm(
            data={
                "source": str(source.id),
                "relation_type": SourceLink.RelationType.SUPPORTS,
                "note": "",
            }
        )
        self.assertFalse(form.is_valid())

    def test_non_creator_cannot_archive_source(self):
        member = User.objects.create_user(
            username="source-archive-outsider",
            email="source-archive-outsider@example.com",
            password="Source-archive-password-741!",
        )
        source = Source.objects.create(
            title="Чужой источник",
            source_type=Source.SourceType.ARCHIVE,
            created_by=self.owner,
        )
        self.client.force_login(member)

        response = self.client.post(
            reverse("heritage:archive_source", args=[source.id]),
        )

        self.assertEqual(response.status_code, 403)
        source.refresh_from_db()
        self.assertEqual(source.status, Source.Status.ACTIVE)

    def test_attach_existing_source_logs_new_link(self):
        source = Source.objects.create(
            title="Готовый источник",
            source_type=Source.SourceType.ARCHIVE,
            url="https://example.com/hidden-source",
            notes="HIDDEN SOURCE NOTES",
        )

        response = self.client.post(
            self.source_url("attach_existing_source"),
            {
                "source": str(source.id),
                "relation_type": SourceLink.RelationType.CONTEXT,
                "note": "HIDDEN ATTACH NOTE",
            },
        )

        self.assertEqual(response.status_code, 302)
        source_link = SourceLink.objects.get(source=source)
        event = self.assert_resource_event(
            AuditEvent.Action.ATTACH_SOURCE
        )
        self.assert_source_ids(event, source, source_link)
        self.assertEqual(
            event.details,
            {
                "source_id": str(source.id),
                "source_link_id": str(source_link.id),
                "relation_type": SourceLink.RelationType.CONTEXT,
            },
        )

    def test_changed_source_link_logs_fields_without_note_content(self):
        source = Source.objects.create(
            title="Изменяемый источник",
            source_type=Source.SourceType.ARCHIVE,
        )
        source_link = SourceLink.objects.create(
            source=source,
            resource_type=SourceLink.ResourceType.BIOGRAPHY,
            object_id=self.biography.id,
            relation_type=SourceLink.RelationType.SUPPORTS,
            note="OLD PRIVATE NOTE",
            created_by=None,
        )
        post_data = {
            "source": str(source.id),
            "relation_type": SourceLink.RelationType.CONTRADICTS,
            "note": "NEW PRIVATE NOTE",
        }

        response = self.client.post(
            self.source_url("attach_existing_source"),
            post_data,
        )

        self.assertEqual(response.status_code, 302)
        source_link.refresh_from_db()
        self.assertIsNone(source_link.created_by)
        event = self.assert_resource_event(
            AuditEvent.Action.UPDATE_SOURCE_LINK
        )
        self.assert_source_ids(event, source, source_link)
        self.assertEqual(
            event.details,
            {
                "source_id": str(source.id),
                "source_link_id": str(source_link.id),
                "changed_fields": ["note", "relation_type"],
            },
        )
        self.assertNotIn("OLD PRIVATE NOTE", str(event.details))
        self.assertNotIn("NEW PRIVATE NOTE", str(event.details))

        repeat_response = self.client.post(
            self.source_url("attach_existing_source"),
            post_data,
        )

        self.assertEqual(repeat_response.status_code, 302)
        self.assertEqual(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.UPDATE_SOURCE_LINK,
            ).count(),
            1,
        )

    def test_detach_source_logs_once_and_repeat_request_does_not(self):
        source = Source.objects.create(
            title="Отвязываемый источник",
            source_type=Source.SourceType.ORAL,
        )
        source_link = SourceLink.objects.create(
            source=source,
            resource_type=SourceLink.ResourceType.BIOGRAPHY,
            object_id=self.biography.id,
            relation_type=SourceLink.RelationType.CONTRADICTS,
            note="DETACH PRIVATE NOTE",
            created_by=self.owner,
        )
        source_link_id = source_link.id
        url = reverse(
            "heritage:detach_source",
            args=[source_link_id],
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            SourceLink.objects.filter(id=source_link_id).exists()
        )
        event = self.assert_resource_event(
            AuditEvent.Action.DETACH_SOURCE
        )
        self.assertEqual(
            event.details,
            {
                "source_id": str(source.id),
                "source_link_id": str(source_link_id),
                "relation_type": SourceLink.RelationType.CONTRADICTS,
            },
        )
        self.assertNotIn("DETACH PRIVATE NOTE", str(event.details))

        repeat_response = self.client.post(url)

        self.assertEqual(repeat_response.status_code, 404)
        self.assertEqual(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.DETACH_SOURCE,
            ).count(),
            1,
        )


class VerificationMutationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="verification-admin",
            email="verification-admin@example.com",
            password="Verification-test-password-517!",
        )
        self.person = Person.objects.create(
            first_name="Проверяемый",
            last_name="Профиль",
        )
        self.biography = Biography.objects.create(
            person=self.person,
            text="Проверяемая биография",
        )
        self.url = reverse(
            "heritage:verify_resource",
            args=[
                Verification.ResourceType.BIOGRAPHY,
                self.biography.id,
            ],
        )
        self.client.force_login(self.admin)

    def test_opening_verification_form_does_not_write_to_database(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Verification.objects.exists())
        self.assertFalse(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.VERIFY_HERITAGE,
            ).exists()
        )

    def test_post_creates_verification_and_audits_status(self):
        response = self.client.post(
            self.url,
            {
                "status": Verification.Status.VERIFIED,
                "comment": "Комментарий не должен попасть в аудит",
            },
        )

        self.assertEqual(response.status_code, 302)
        verification = Verification.objects.get(
            resource_type=Verification.ResourceType.BIOGRAPHY,
            object_id=self.biography.id,
        )
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.VERIFY_HERITAGE,
        )
        self.assertEqual(event.person, self.person)
        self.assertEqual(event.object_id, self.biography.id)
        self.assertEqual(
            event.details,
            {
                "verification_id": str(verification.id),
                "previous_status": None,
                "current_status": Verification.Status.VERIFIED,
            },
        )
        self.assertNotIn("Комментарий", str(event.details))
