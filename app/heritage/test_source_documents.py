from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from family.models import Person, ProfileOwnership
from privacy.models import AccessGrant, PrivacyPolicy

from .models import Biography, LifeEvent, MediaAsset, Source, SourceLink


class SourceDocumentTests(TestCase):
    def setUp(self):
        # Every file in these tests lives in memory, outside the family archive.
        self.storage = InMemoryStorage()
        storage_patch = patch.object(
            MediaAsset._meta.get_field("file"), "storage", self.storage,
        )
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.owner = User.objects.create_user(
            username="document-owner", email="document-owner@example.com",
        )
        self.member = User.objects.create_user(
            username="document-member", email="document-member@example.com",
        )
        self.admin = User.objects.create_user(
            username="document-admin", email="document-admin@example.com",
            system_role=User.SystemRole.SYSTEM_ADMIN,
        )
        self.person = Person.objects.create(first_name="Владелец документа")
        self.other_person = Person.objects.create(first_name="Другой родственник")
        for user, person in [
            (self.owner, self.person), (self.member, self.other_person),
        ]:
            ProfileOwnership.objects.create(
                user=user, person=person,
                status=ProfileOwnership.Status.CONFIRMED,
            )
        self.biography = Biography.objects.create(
            person=self.person, text="Семейная биография",
        )
        self.document = MediaAsset.objects.create(
            person=self.person,
            title="PRIVATE DOCUMENT TITLE",
            description="PRIVATE DOCUMENT DESCRIPTION",
            media_type=MediaAsset.MediaType.DOCUMENT,
            status=MediaAsset.Status.APPROVED,
            uploaded_by=self.owner,
            mime_type="application/pdf",
            original_filename="private-original.pdf",
            file=ContentFile(b"%PDF-1.7\n%%EOF\n", name="private-original.pdf"),
        )
        self.policy = PrivacyPolicy.objects.get(
            resource_type="MEDIA_ASSET", object_id=self.document.id,
        )
        self.policy.visibility = PrivacyPolicy.Visibility.OWNER_ONLY
        self.policy.show_existence = False
        self.policy.save()
        self.create_url = reverse("heritage:create_source_for_resource", args=[
            "BIOGRAPHY", self.biography.id,
        ])
        self.profile_url = reverse("family:person_detail", args=[self.person.id])
        self.file_url = reverse("heritage:serve_media_asset", args=[self.document.id])
        self.payload = {
            "source_type": Source.SourceType.DOCUMENT,
            "title": "Документальное свидетельство",
            "document": str(self.document.id),
            "relation_type": SourceLink.RelationType.SUPPORTS,
            "link_note": "Подтверждает сведения",
        }
        self.client.force_login(self.owner)

    def create_source(self):
        response = self.client.post(self.create_url, self.payload)
        self.assertEqual(response.status_code, 302)
        return Source.objects.get(document=self.document)

    def assert_file_readable(self):
        response = self.client.get(self.file_url)
        self.assertEqual(response.status_code, 200)
        # The test client's streaming wrapper closes the response on exhaustion.
        content = b"".join(response.streaming_content)
        self.assertEqual(content, b"%PDF-1.7\n%%EOF\n")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.closed)

    def test_create_source_reuses_file_and_preserves_private_policy(self):
        stored_name = self.document.file.name
        source = self.create_source()
        self.assertEqual(source.url, "")
        self.assertEqual(source.created_by, self.owner)
        self.assertEqual(SourceLink.objects.get(source=source).object_id, self.biography.id)
        self.assertEqual(MediaAsset.objects.count(), 1)
        self.document.refresh_from_db()
        self.assertEqual(self.document.file.name, stored_name)
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.visibility, PrivacyPolicy.Visibility.OWNER_ONLY)
        self.assertFalse(self.policy.show_existence)
        event = AuditEvent.objects.get(action=AuditEvent.Action.CREATE_SOURCE)
        self.assertEqual(event.details["document_id"], str(self.document.id))
        self.assertNotIn("PRIVATE", str(event.details))
        self.assertNotIn(stored_name, str(event.details))

    def test_form_lists_only_approved_documents_from_this_profile(self):
        for media_type, status, person in [
            ("PHOTO", "APPROVED", self.person),
            ("DOCUMENT", "PENDING", self.person),
            ("DOCUMENT", "REJECTED", self.person),
            ("DOCUMENT", "ARCHIVED", self.person),
            ("DOCUMENT", "APPROVED", self.other_person),
        ]:
            invalid = MediaAsset.objects.create(
                person=person, title="OTHER PRIVATE TITLE",
                media_type=media_type, status=status, file="unavailable.pdf",
            )
            with self.subTest(media_type=media_type, status=status, person=person.id):
                response = self.client.post(
                    self.create_url, {**self.payload, "document": str(invalid.id)},
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("document", response.context["form"].errors)
        self.assertFalse(Source.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action="CREATE_SOURCE").exists())
        response = self.client.get(self.create_url)
        self.assertContains(response, self.document.title)
        self.assertNotContains(response, "OTHER PRIVATE TITLE")

    def test_tampered_document_uuid_and_wrong_source_type_are_rejected(self):
        for payload, field in [
            ({**self.payload, "document": "invalid-uuid"}, "document"),
            ({**self.payload, "source_type": "WEBSITE"}, "source_type"),
        ]:
            with self.subTest(field=field):
                response = self.client.post(self.create_url, payload)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
        self.assertFalse(Source.objects.exists())

    def test_member_cannot_create_source_on_someone_elses_profile(self):
        self.client.force_login(self.member)
        for method in (self.client.get, self.client.post):
            response = method(self.create_url, self.payload)
            self.assertEqual(response.status_code, 403)
        self.assertFalse(Source.objects.exists())

    def test_private_document_metadata_and_link_are_hidden_from_member(self):
        self.create_source()
        self.client.force_login(self.member)
        response = self.client.get(self.profile_url)
        self.assertContains(response, self.payload["title"])
        self.assertNotContains(response, "PRIVATE DOCUMENT")
        self.assertNotContains(response, str(self.document.id))
        self.assertNotContains(response, "private-original.pdf")
        self.assertNotContains(response, "Открыть документ")
        self.assertEqual(self.client.get(self.file_url).status_code, 404)
        self.assertFalse(AuditEvent.objects.filter(action="VIEW_MEDIA").exists())

    def test_document_access_tracks_grant_and_revocation(self):
        self.create_source()
        self.policy.visibility = PrivacyPolicy.Visibility.REQUEST_ONLY
        self.policy.save()
        grant = AccessGrant.objects.create(policy=self.policy, grantee=self.member)
        self.client.force_login(self.member)
        response = self.client.get(self.profile_url)
        self.assertTrue(response.context["biography_item"]["source_links"][0].can_open_document)
        self.assertContains(response, self.file_url)
        self.assert_file_readable()
        event = AuditEvent.objects.get(action=AuditEvent.Action.VIEW_MEDIA)
        self.assertEqual(event.actor, self.member)
        self.assertEqual(event.object_id, self.document.id)

        self.client.force_login(self.owner)
        response = self.client.post(reverse("privacy:revoke_access_grant", args=[grant.id]))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.member)
        response = self.client.get(self.profile_url)
        self.assertNotContains(response, self.file_url)
        self.assertEqual(self.client.get(self.file_url).status_code, 404)

    def test_expired_grant_or_missing_policy_does_not_expose_source_document(self):
        self.create_source()
        self.policy.visibility = PrivacyPolicy.Visibility.REQUEST_ONLY
        self.policy.save()
        AccessGrant.objects.create(
            policy=self.policy, grantee=self.member, valid_until=timezone.now(),
        )
        self.client.force_login(self.member)
        for missing_policy in (False, True):
            with self.subTest(missing_policy=missing_policy):
                if missing_policy:
                    self.policy.delete()
                response = self.client.get(self.profile_url)
                self.assertNotContains(response, self.file_url)
                self.assertEqual(self.client.get(self.file_url).status_code, 404)

    def test_owner_and_admin_can_open_document_from_life_event_source(self):
        event = LifeEvent.objects.create(person=self.person, title="Переезд")
        url = reverse("heritage:create_source_for_resource", args=["LIFE_EVENT", event.id])
        self.assertEqual(self.client.post(url, self.payload).status_code, 302)
        for user in (self.owner, self.admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(self.profile_url)
                link = response.context["life_event_items"][0]["source_links"][0]
                self.assertTrue(link.can_open_document)
                self.assertContains(response, self.file_url)
                self.assert_file_readable()

    def test_archiving_document_disables_link_but_preserves_source(self):
        source = self.create_source()
        response = self.client.post(reverse("heritage:archive_media_asset", args=[self.document.id]))
        self.assertEqual(response.status_code, 302)
        for user in (self.owner, self.admin, self.member):
            self.client.force_login(user)
            response = self.client.get(self.profile_url)
            self.assertContains(response, source.title)
            self.assertNotContains(response, self.file_url)
            self.assertEqual(self.client.get(self.file_url).status_code, 404)
        source.refresh_from_db()
        self.assertEqual(source.document_id, self.document.id)
        self.assertTrue(self.storage.exists(self.document.file.name))

    def test_existing_document_source_can_be_reused_only_in_its_profile(self):
        source = self.create_source()
        event = LifeEvent.objects.create(person=self.person, title="Событие")
        url = reverse("heritage:attach_existing_source", args=["LIFE_EVENT", event.id])
        data = {"source": str(source.id), "relation_type": "CONTEXT"}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(source.links.count(), 2)
        other_bio = Biography.objects.create(person=self.other_person, text="Другая биография")
        other_url = reverse("heritage:attach_existing_source", args=["BIOGRAPHY", other_bio.id])
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(other_url), source.title)
        response = self.client.post(other_url, data)
        self.assertIn("source", response.context["form"].errors)
        self.assertEqual(source.links.count(), 2)

    def test_reusing_archived_document_or_archived_source_is_rejected(self):
        source = self.create_source()
        event = LifeEvent.objects.create(person=self.person, title="Событие")
        url = reverse("heritage:attach_existing_source", args=["LIFE_EVENT", event.id])
        for document_status, source_status in [("ARCHIVED", "ACTIVE"), ("APPROVED", "ARCHIVED")]:
            self.document.status = document_status
            self.document.save()
            source.status = source_status
            source.save()
            response = self.client.post(url, {"source": str(source.id), "relation_type": "SUPPORTS"})
            self.assertIn("source", response.context["form"].errors)
            self.assertEqual(source.links.count(), 1)

    def test_source_metadata_edit_preserves_document_binding(self):
        source = self.create_source()
        data = {
            "source_type": "DOCUMENT", "title": "Уточнённое свидетельство",
            "document": "",  # The attachment isn't an editable metadata field.
        }
        response = self.client.post(reverse("heritage:edit_source", args=[source.id]), data)
        self.assertEqual(response.status_code, 302)
        source.refresh_from_db()
        self.assertEqual(source.document_id, self.document.id)
        self.assertEqual(source.title, data["title"])

    def test_deleting_document_preserves_source_and_citation(self):
        source = self.create_source()
        self.document.delete()
        source.refresh_from_db()
        self.assertIsNone(source.document_id)
        self.assertEqual(source.title, self.payload["title"])
        self.assertEqual(source.links.count(), 1)
        self.assertContains(self.client.get(self.profile_url), source.title)

    def test_document_source_cannot_change_to_another_source_type(self):
        source = self.create_source()
        response = self.client.post(
            reverse("heritage:edit_source", args=[source.id]),
            {"source_type": "WEBSITE", "title": source.title},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("source_type", response.context["form"].errors)
        source.refresh_from_db()
        self.assertEqual(source.source_type, Source.SourceType.DOCUMENT)
        self.assertEqual(source.document_id, self.document.id)
        self.assertFalse(AuditEvent.objects.filter(action="UPDATE_SOURCE").exists())

    def test_audit_failure_rolls_back_source_and_keeps_existing_file(self):
        with patch("heritage.views.log_audit_event", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.create_url, self.payload)
        self.assertFalse(Source.objects.exists())
        self.assertFalse(SourceLink.objects.exists())
        self.assertTrue(MediaAsset.objects.filter(pk=self.document.id).exists())
        self.assertTrue(self.storage.exists(self.document.file.name))
