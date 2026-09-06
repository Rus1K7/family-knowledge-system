from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from family.models import Person
from heritage.models import Biography
from network.models import HelpOffer

from .models import Employment, ProfileChangeRequest
from .services import submit_change_request


class ProfileChangeModerationAuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="test-password",
            system_role=User.SystemRole.SYSTEM_ADMIN,
        )
        self.member = User.objects.create_user(
            username="member",
            email="member@example.com",
            password="test-password",
        )
        self.person = Person.objects.create(
            first_name="Анна",
            last_name="Тестова",
        )
        self.client.force_login(self.admin)

    def create_employment_request(self):
        return ProfileChangeRequest.objects.create(
            resource_type=(
                ProfileChangeRequest.ResourceType.EMPLOYMENT
            ),
            action=ProfileChangeRequest.Action.CREATE,
            proposed_data={
                "person_id": str(self.person.id),
                "organization": "Новая организация",
                "position": "Инженер",
                "start_date": "",
                "end_date": "",
                "is_current": True,
                "description": "",
            },
            requested_by=self.member,
        )

    def test_approve_create_logs_created_resource(self):
        change_request = self.create_employment_request()

        response = self.client.post(
            reverse(
                "profiles:approve_change_request",
                args=[change_request.id],
            )
        )

        self.assertRedirects(
            response,
            reverse("profiles:change_request_list"),
        )
        employment = Employment.objects.get(
            person=self.person
        )
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.APPROVE_CHANGE
        )
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.person, self.person)
        self.assertEqual(
            event.resource_type,
            ProfileChangeRequest.ResourceType.EMPLOYMENT,
        )
        self.assertEqual(event.object_id, employment.id)
        self.assertEqual(
            event.details["request_id"],
            str(change_request.id),
        )
        self.assertEqual(
            event.details["requester_id"],
            str(self.member.id),
        )

    def test_reject_logs_event_without_changing_target(self):
        employment = Employment.objects.create(
            person=self.person,
            organization="Старая организация",
        )
        change_request = ProfileChangeRequest.objects.create(
            resource_type=(
                ProfileChangeRequest.ResourceType.EMPLOYMENT
            ),
            object_id=employment.id,
            action=ProfileChangeRequest.Action.EDIT,
            proposed_data={
                "organization": "Новая организация",
            },
            requested_by=self.member,
        )

        response = self.client.post(
            reverse(
                "profiles:reject_change_request",
                args=[change_request.id],
            )
        )

        self.assertRedirects(
            response,
            reverse("profiles:change_request_list"),
        )
        employment.refresh_from_db()
        self.assertEqual(
            employment.organization,
            "Старая организация",
        )
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.REJECT_CHANGE
        )
        self.assertEqual(event.person, self.person)
        self.assertEqual(event.object_id, employment.id)
        self.assertEqual(
            event.details["request_id"],
            str(change_request.id),
        )
        self.assertEqual(
            event.details["requester_id"],
            str(self.member.id),
        )

    def test_repeat_processing_does_not_duplicate_audit_event(self):
        change_request = self.create_employment_request()
        url = reverse(
            "profiles:approve_change_request",
            args=[change_request.id],
        )

        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.APPROVE_CHANGE
            ).count(),
            1,
        )

    def test_delete_logs_target_before_removing_it(self):
        employment = Employment.objects.create(
            person=self.person,
            organization="Удаляемая организация",
        )
        employment_id = employment.id
        change_request = ProfileChangeRequest.objects.create(
            resource_type=(
                ProfileChangeRequest.ResourceType.EMPLOYMENT
            ),
            object_id=employment_id,
            action=ProfileChangeRequest.Action.DELETE,
            requested_by=self.member,
        )

        response = self.client.post(
            reverse(
                "profiles:approve_change_request",
                args=[change_request.id],
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Employment.objects.filter(id=employment_id).exists()
        )
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.APPROVE_CHANGE
        )
        self.assertEqual(event.person, self.person)
        self.assertEqual(event.object_id, employment_id)

    def test_non_admin_cannot_process_request(self):
        change_request = self.create_employment_request()
        self.client.force_login(self.member)

        response = self.client.post(
            reverse(
                "profiles:approve_change_request",
                args=[change_request.id],
            )
        )

        self.assertEqual(response.status_code, 403)
        change_request.refresh_from_db()
        self.assertEqual(
            change_request.status,
            ProfileChangeRequest.Status.PENDING,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.REQUEST_CHANGE,
            ).count(),
            1,
        )
        self.assertFalse(
            AuditEvent.objects.filter(
                action__in=[
                    AuditEvent.Action.APPROVE_CHANGE,
                    AuditEvent.Action.REJECT_CHANGE,
                ],
            ).exists()
        )

    def test_edit_request_is_rendered_in_moderation_list(self):
        employment = Employment.objects.create(
            person=self.person,
            organization="Организация",
        )
        ProfileChangeRequest.objects.create(
            resource_type=(
                ProfileChangeRequest.ResourceType.EMPLOYMENT
            ),
            object_id=employment.id,
            action=ProfileChangeRequest.Action.EDIT,
            proposed_data={
                "organization": "Другая организация",
            },
            requested_by=self.member,
        )

        response = self.client.get(
            reverse("profiles:change_request_list")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Другая организация")

    def test_only_one_pending_request_is_allowed_per_target(self):
        employment = Employment.objects.create(
            person=self.person,
            organization="Удаляемая организация",
        )
        edit_request = ProfileChangeRequest.objects.create(
            resource_type=(
                ProfileChangeRequest.ResourceType.EMPLOYMENT
            ),
            object_id=employment.id,
            action=ProfileChangeRequest.Action.EDIT,
            proposed_data={
                "organization": "Обновлённая организация",
            },
            requested_by=self.member,
        )

        repeated_request, created = submit_change_request(
            resource_type=(
                ProfileChangeRequest.ResourceType.EMPLOYMENT
            ),
            object_id=employment.id,
            action=ProfileChangeRequest.Action.DELETE,
            requested_by=self.member,
        )

        self.assertFalse(created)
        self.assertEqual(
            repeated_request.id,
            edit_request.id,
        )
        self.assertEqual(
            ProfileChangeRequest.objects.filter(
                resource_type=ProfileChangeRequest.ResourceType.EMPLOYMENT,
                object_id=employment.id,
                status=ProfileChangeRequest.Status.PENDING,
            ).count(),
            1,
        )

    def test_create_requests_are_unique_per_person_and_resource(self):
        first, first_created = submit_change_request(
            resource_type=ProfileChangeRequest.ResourceType.EMPLOYMENT,
            action=ProfileChangeRequest.Action.CREATE,
            proposed_data={
                "person_id": str(self.person.id),
                "organization": "Первая заявка",
            },
            requested_by=self.member,
        )
        second, second_created = submit_change_request(
            resource_type=ProfileChangeRequest.ResourceType.EMPLOYMENT,
            action=ProfileChangeRequest.Action.CREATE,
            proposed_data={
                "person_id": str(self.person.id),
                "organization": "Повторная заявка",
            },
            requested_by=self.member,
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.id, second.id)
        self.assertEqual(
            ProfileChangeRequest.objects.filter(
                resource_type=ProfileChangeRequest.ResourceType.EMPLOYMENT,
                status=ProfileChangeRequest.Status.PENDING,
                object_id__isnull=True,
                proposed_data__person_id=str(self.person.id),
            ).count(),
            1,
        )

    def test_database_rejects_second_pending_request_for_target(self):
        employment = Employment.objects.create(
            person=self.person,
            organization="Одна запись",
        )
        ProfileChangeRequest.objects.create(
            resource_type=ProfileChangeRequest.ResourceType.EMPLOYMENT,
            object_id=employment.id,
            action=ProfileChangeRequest.Action.EDIT,
            requested_by=self.member,
        )

        with self.assertRaises(IntegrityError):
            ProfileChangeRequest.objects.create(
                resource_type=ProfileChangeRequest.ResourceType.EMPLOYMENT,
                object_id=employment.id,
                action=ProfileChangeRequest.Action.DELETE,
                requested_by=self.member,
            )


class ProfileChangeRequestCreationAuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="request-audit-admin",
            email="request-audit-admin@example.com",
            password="test-password",
            system_role=User.SystemRole.SYSTEM_ADMIN,
        )
        self.member = User.objects.create_user(
            username="request-audit-member",
            email="request-audit-member@example.com",
            password="test-password",
        )
        self.person = Person.objects.create(
            first_name="Мария",
            last_name="Аудитова",
        )

    def assert_request_event(
        self,
        change_request,
        *,
        target_id,
    ):
        events = AuditEvent.objects.filter(
            action=AuditEvent.Action.REQUEST_CHANGE,
        )
        self.assertEqual(events.count(), 1)

        event = events.get()
        self.assertEqual(event.actor, self.member)
        self.assertEqual(event.person, self.person)
        self.assertEqual(
            event.resource_type,
            change_request.resource_type,
        )
        self.assertEqual(event.object_id, target_id)
        self.assertEqual(
            event.details,
            {
                "request_id": str(change_request.id),
                "change_action": change_request.action,
                "target_id": (
                    str(target_id)
                    if target_id is not None
                    else None
                ),
                "proposed_fields": sorted(
                    field_name
                    for field_name in change_request.proposed_data
                    if field_name != "person_id"
                ),
            },
        )

    def test_create_profile_resource_request_is_audited_once(self):
        change_request = ProfileChangeRequest.objects.create(
            resource_type=(
                ProfileChangeRequest.ResourceType.EMPLOYMENT
            ),
            action=ProfileChangeRequest.Action.CREATE,
            proposed_data={
                "person_id": str(self.person.id),
                "organization": "Новая организация",
            },
            requested_by=self.member,
        )

        self.assertIsNone(change_request.object_id)
        self.assert_request_event(
            change_request,
            target_id=None,
        )

    def test_edit_heritage_resource_request_is_audited(self):
        biography = Biography.objects.create(
            person=self.person,
            text="Исходная биография",
            created_by=self.member,
        )

        change_request = ProfileChangeRequest.objects.create(
            resource_type=(
                ProfileChangeRequest.ResourceType.BIOGRAPHY
            ),
            object_id=biography.id,
            action=ProfileChangeRequest.Action.EDIT,
            proposed_data={
                "text": "Обновлённая биография",
            },
            requested_by=self.member,
        )

        self.assert_request_event(
            change_request,
            target_id=biography.id,
        )

    def test_delete_network_resource_request_is_audited(self):
        help_offer = HelpOffer.objects.create(
            person=self.person,
            title="Помогу с переездом",
        )

        change_request = ProfileChangeRequest.objects.create(
            resource_type=(
                ProfileChangeRequest.ResourceType.HELP_OFFER
            ),
            object_id=help_offer.id,
            action=ProfileChangeRequest.Action.DELETE,
            requested_by=self.member,
        )

        self.assert_request_event(
            change_request,
            target_id=help_offer.id,
        )

    def test_moderation_does_not_duplicate_request_event(self):
        change_request = ProfileChangeRequest.objects.create(
            resource_type=(
                ProfileChangeRequest.ResourceType.EMPLOYMENT
            ),
            action=ProfileChangeRequest.Action.CREATE,
            proposed_data={
                "person_id": str(self.person.id),
                "organization": "Организация после проверки",
            },
            requested_by=self.member,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse(
                "profiles:approve_change_request",
                args=[change_request.id],
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.REQUEST_CHANGE,
            ).count(),
            1,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.APPROVE_CHANGE,
            ).count(),
            1,
        )

    @patch(
        "profiles.signals.log_audit_event",
        side_effect=RuntimeError("audit unavailable"),
    )
    def test_audit_failure_rolls_back_change_request(
        self,
        mocked_log,
    ):
        with self.assertRaises(RuntimeError):
            ProfileChangeRequest.objects.create(
                resource_type=(
                    ProfileChangeRequest.ResourceType.EMPLOYMENT
                ),
                action=ProfileChangeRequest.Action.CREATE,
                proposed_data={
                    "person_id": str(self.person.id),
                    "organization": "Не должна сохраниться",
                },
                requested_by=self.member,
            )

        self.assertFalse(
            ProfileChangeRequest.objects.exists()
        )
        self.assertFalse(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.REQUEST_CHANGE,
            ).exists()
        )
        mocked_log.assert_called_once()
