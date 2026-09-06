from django.contrib.admin.sites import AdminSite
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from family.models import Person

from .admin import AuditEventAdmin
from .models import AuditEvent
from .services import log_audit_event


class AuditEventListTests(TestCase):
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
            first_name="Мария",
            last_name="Тестова",
        )
        AuditEvent.objects.create(
            actor=self.admin,
            action=AuditEvent.Action.APPROVE_CHANGE,
            person=self.person,
            resource_type="EMPLOYMENT",
        )

    def test_system_admin_can_view_audit_log(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("audit:event_list")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Одобрение изменения")
        self.assertContains(response, str(self.person))

    def test_family_member_cannot_view_audit_log(self):
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("audit:event_list")
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_can_filter_by_action_user_and_person(self):
        AuditEvent.objects.create(
            actor=self.member,
            action=AuditEvent.Action.REQUEST_ACCESS,
            person=self.person,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("audit:event_list"),
            {
                "action": AuditEvent.Action.REQUEST_ACCESS,
                "actor": self.member.email,
                "person": self.person.first_name,
            },
        )

        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        self.assertEqual(page_obj.paginator.count, 1)
        self.assertEqual(
            page_obj.object_list[0].action,
            AuditEvent.Action.REQUEST_ACCESS,
        )

    def test_admin_can_filter_by_date(self):
        self.client.force_login(self.admin)
        today = timezone.localdate().isoformat()

        response = self.client.get(
            reverse("audit:event_list"),
            {"date_from": today, "date_to": today},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_audit_log_is_paginated(self):
        AuditEvent.objects.bulk_create(
            [
                AuditEvent(
                    actor=self.admin,
                    action=AuditEvent.Action.REQUEST_ACCESS,
                )
                for _ in range(55)
            ]
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("audit:event_list"),
            {"page": 2},
        )

        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        self.assertEqual(page_obj.paginator.count, 56)
        self.assertEqual(page_obj.number, 2)
        self.assertEqual(len(page_obj.object_list), 6)


class AuditEventIntegrityTests(TestCase):
    def test_service_uses_empty_context_by_default(self):
        event = log_audit_event(
            actor=None,
            action=AuditEvent.Action.REQUEST_ACCESS,
        )

        self.assertEqual(event.details, {})

    def test_admin_cannot_delete_audit_events(self):
        model_admin = AuditEventAdmin(
            AuditEvent,
            AdminSite(),
        )

        self.assertFalse(
            model_admin.has_delete_permission(
                request=None,
            )
        )
