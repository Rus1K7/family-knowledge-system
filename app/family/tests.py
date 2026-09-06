from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, RequestFactory
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from heritage.models import LifeEvent, MediaAsset
from privacy.models import AccessGrant, PrivacyPolicy
from profiles.models import Employment

from .models import Person, ProfileOwnership, Relationship
from .forms import AddRelativeForm
from .views import add_relative


class RelationshipAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="relationship-admin", email="relationship-admin@example.com", password="test-password",
        )
        self.client.force_login(self.admin)
        self.a = Person.objects.create(first_name="A")
        self.b = Person.objects.create(first_name="B")
        self.link = Relationship.objects.create(
            person_a=self.a, person_b=self.b,
            relationship_type=Relationship.Type.PARENT_CHILD,
        )

    def test_admin_rejects_cycle_without_writing_audit(self):
        response = self.client.post(reverse("admin:family_relationship_add"), {
            "person_a": self.b.id, "person_b": self.a.id,
            "relationship_type": Relationship.Type.PARENT_CHILD,
            "status": Relationship.Status.VERIFIED, "_save": "Save",
        })
        self.assertContains(response, "цикл")
        self.assertEqual(Relationship.objects.count(), 1)
        self.assertFalse(AuditEvent.objects.exists())

    def test_admin_update_and_delete_are_audited(self):
        url = reverse("admin:family_relationship_change", args=[self.link.id])
        data = {
            "person_a": self.a.id, "person_b": self.b.id,
            "relationship_type": Relationship.Type.PARENT_CHILD,
            "status": Relationship.Status.VERIFIED, "_save": "Save",
        }
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        event = AuditEvent.objects.get(action=AuditEvent.Action.UPDATE_RELATIONSHIP)
        self.assertEqual(event.details["old"]["status"], Relationship.Status.PENDING)
        self.assertEqual(event.details["new"]["status"], Relationship.Status.VERIFIED)
        response = self.client.post(
            reverse("admin:family_relationship_delete", args=[self.link.id]), {"post": "yes"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Relationship.objects.exists())
        self.assertEqual(AuditEvent.objects.get(
            action=AuditEvent.Action.DELETE_RELATIONSHIP).object_id, self.link.id)

    def test_admin_rejects_reverse_spouse_duplicate(self):
        self.link.relationship_type = Relationship.Type.SPOUSE
        self.link.save()
        response = self.client.post(reverse("admin:family_relationship_add"), {
            "person_a": self.b.id, "person_b": self.a.id,
            "relationship_type": Relationship.Type.SPOUSE,
            "status": Relationship.Status.VERIFIED,
        })
        self.assertContains(response, "уже существует")
        self.assertEqual(Relationship.objects.count(), 1)


class AncestryValidationTests(TestCase):
    def test_indirect_cycle_including_adoptive_parent_is_rejected(self):
        a, b, c = [Person.objects.create(first_name=name) for name in "ABC"]
        Relationship.objects.create(person_a=a, person_b=b,
            relationship_type=Relationship.Type.PARENT_CHILD)
        Relationship.objects.create(person_a=b, person_b=c,
            relationship_type=Relationship.Type.ADOPTIVE_PARENT)
        form = AddRelativeForm(
            {"relation_type": "CHILD", "existing_person": a.id}, current_person=c,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("цикл", str(form.errors))
        valid_form = AddRelativeForm(
            {"relation_type": "CHILD", "existing_person": c.id}, current_person=a,
        )
        self.assertTrue(valid_form.is_valid(), valid_form.errors)


class ConcurrentTreeChangesTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Graph locking uses PostgreSQL")
        self.admin = User.objects.create_user(
            username="concurrent-admin", email="concurrent@example.com",
            system_role=User.SystemRole.SYSTEM_ADMIN,
        )
        self.a = Person.objects.create(first_name="A")
        self.b = Person.objects.create(first_name="B")

    def simultaneous_posts(self, operations):
        barrier = Barrier(2)

        def submit(operation):
            close_old_connections()
            try:
                person_id, relative_id, relation_type = operation
                request = RequestFactory().post("/", {
                    "existing_person": relative_id, "relation_type": relation_type,
                })
                request.user = User.objects.get(pk=self.admin.pk)
                barrier.wait(timeout=10)
                return add_relative(request, person_id).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(submit, operations))

    def test_opposite_parent_requests_cannot_form_cycle(self):
        statuses = self.simultaneous_posts([
            (self.a.id, self.b.id, "CHILD"),
            (self.b.id, self.a.id, "CHILD"),
        ])
        self.assertEqual(sorted(statuses), [200, 302])
        self.assertEqual(Relationship.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(
            action=AuditEvent.Action.CREATE_RELATIONSHIP).count(), 1)

    def test_reversed_spouse_requests_create_one_link(self):
        self.assertEqual(self.simultaneous_posts([
            (self.a.id, self.b.id, "SPOUSE"),
            (self.b.id, self.a.id, "SPOUSE"),
        ]), [302, 302])
        self.assertEqual(Relationship.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(
            action=AuditEvent.Action.CREATE_RELATIONSHIP).count(), 1)

    def test_duplicate_child_requests_create_one_link(self):
        self.assertEqual(self.simultaneous_posts([
            (self.a.id, self.b.id, "CHILD"),
            (self.a.id, self.b.id, "CHILD"),
        ]), [302, 302])
        self.assertEqual(Relationship.objects.count(), 1)


class FamilyTreeAuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="tree-admin", email="tree-admin@example.com",
            system_role=User.SystemRole.SYSTEM_ADMIN,
        )
        self.person = Person.objects.create(first_name="Исходный")
        self.url = reverse("family:add_relative", args=[self.person.id])
        self.client.force_login(self.admin)

    def test_new_parent_and_relationship_are_audited(self):
        response = self.client.post(self.url, {
            "relation_type": "PARENT", "first_name": "Родитель",
        })
        self.assertEqual(response.status_code, 302)
        relationship = Relationship.objects.get()
        self.assertEqual(relationship.person_b, self.person)
        person_event = AuditEvent.objects.get(action=AuditEvent.Action.CREATE_PERSON)
        self.assertEqual(person_event.person_id, relationship.person_a_id)
        event = AuditEvent.objects.get(action=AuditEvent.Action.CREATE_RELATIONSHIP)
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.object_id, relationship.id)
        self.assertEqual(event.details["person_a_id"], str(relationship.person_a_id))
        self.assertEqual(event.details["person_b_id"], str(self.person.id))
        self.assertNotIn("Родитель", str(event.details))

    def test_existing_relative_repeat_does_not_duplicate_events(self):
        relative = Person.objects.create(first_name="Существующий")
        for relation_type in ("CHILD", "SPOUSE"):
            with self.subTest(relation_type=relation_type):
                data = {"relation_type": relation_type, "existing_person": relative.id}
                self.assertEqual(self.client.post(self.url, data).status_code, 302)
                self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(Relationship.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(
            action=AuditEvent.Action.CREATE_RELATIONSHIP).count(), 2)
        self.assertFalse(AuditEvent.objects.filter(action=AuditEvent.Action.CREATE_PERSON).exists())

    def test_staff_without_system_role_cannot_modify_tree(self):
        staff = User.objects.create_user(
            username="tree-staff", email="tree-staff@example.com", is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.post(self.url, {
            "relation_type": "CHILD", "first_name": "Недопустимый",
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Person.objects.count(), 1)
        self.assertFalse(Relationship.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_audit_failure_rolls_back_person_relationship_and_first_event(self):
        from audit.services import log_audit_event

        def fail_relationship_event(**kwargs):
            if kwargs["action"] == AuditEvent.Action.CREATE_RELATIONSHIP:
                raise RuntimeError("audit unavailable")
            return log_audit_event(**kwargs)

        with patch("family.views.log_audit_event", side_effect=fail_relationship_event):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, {
                    "relation_type": "CHILD", "first_name": "Откат",
                })
        self.assertEqual(Person.objects.count(), 1)
        self.assertFalse(Relationship.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())


class PersonDetailTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="test-password",
        )
        self.person = Person.objects.create(
            first_name="Иван",
            last_name="Тестов",
        )
        self.client.force_login(self.admin)

    def test_life_events_are_not_duplicated_and_media_is_included(self):
        event = LifeEvent.objects.create(
            person=self.person,
            title="Важное событие",
            created_by=self.admin,
        )
        media = MediaAsset.objects.create(
            person=self.person,
            media_type=MediaAsset.MediaType.PHOTO,
            title="Семейное фото",
            file="persons/test/photo.jpg",
            status=MediaAsset.Status.APPROVED,
            uploaded_by=self.admin,
        )

        response = self.client.get(
            reverse(
                "family:person_detail",
                args=[self.person.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["object"] for item in response.context["life_event_items"]],
            [event],
        )
        self.assertEqual(
            [item["object"] for item in response.context["media_items"]],
            [media],
        )


class FamilySpaceAuthorizationTests(TestCase):
    def setUp(self):
        self.person = Person.objects.create(
            first_name="Семейный",
            last_name="Профиль",
        )

    def create_user(self, username, **extra_fields):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="Family-test-password-629!",
            **extra_fields,
        )

    def test_confirmed_family_member_can_open_family_space(self):
        member = self.create_user("member")
        ProfileOwnership.objects.create(
            user=member,
            person=self.person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        self.client.force_login(member)

        home_response = self.client.get(
            reverse("family:home")
        )
        profile_response = self.client.get(
            reverse(
                "family:person_detail",
                args=[self.person.id],
            )
        )

        self.assertEqual(home_response.status_code, 200)
        self.assertEqual(profile_response.status_code, 200)

    def test_unaffiliated_account_cannot_open_family_space(self):
        outsider = self.create_user("outsider")
        self.client.force_login(outsider)

        home_response = self.client.get(
            reverse("family:home")
        )
        profile_response = self.client.get(
            reverse(
                "family:person_detail",
                args=[self.person.id],
            )
        )

        self.assertEqual(home_response.status_code, 403)
        self.assertEqual(profile_response.status_code, 403)

    def test_system_admin_without_profile_can_open_family_space(self):
        admin = self.create_user(
            "admin",
            system_role=User.SystemRole.SYSTEM_ADMIN,
        )
        self.client.force_login(admin)

        response = self.client.get(
            reverse("family:home")
        )

        self.assertEqual(response.status_code, 200)

    def test_suspended_owner_cannot_open_family_space(self):
        owner = self.create_user(
            "suspended-owner",
            status=User.Status.SUSPENDED,
        )
        ProfileOwnership.objects.create(
            user=owner,
            person=self.person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        self.client.force_login(owner)

        response = self.client.get(
            reverse("family:home")
        )

        self.assertRedirects(
            response,
            f"{reverse('family:login')}?next={reverse('family:home')}",
            fetch_redirect_response=False,
        )


class PrivateResourceViewAuditTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner-for-audit",
            email="owner-for-audit@example.com",
            password="Audit-test-password-825!",
        )
        self.member = User.objects.create_user(
            username="member-for-audit",
            email="member-for-audit@example.com",
            password="Audit-test-password-825!",
        )
        self.person = Person.objects.create(
            first_name="Закрытый",
            last_name="Профиль",
        )
        member_person = Person.objects.create(
            first_name="Участник",
            last_name="Семьи",
        )
        ProfileOwnership.objects.create(
            user=self.owner,
            person=self.person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        ProfileOwnership.objects.create(
            user=self.member,
            person=member_person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        self.employment = Employment.objects.create(
            person=self.person,
            organization="Закрытая организация",
        )
        self.policy = PrivacyPolicy.objects.get(
            resource_type=PrivacyPolicy.ResourceType.EMPLOYMENT,
            object_id=self.employment.id,
        )
        self.url = reverse(
            "family:person_detail",
            args=[self.person.id],
        )

    def test_view_through_grant_is_audited(self):
        self.policy.visibility = (
            PrivacyPolicy.Visibility.SELECTED_USERS
        )
        self.policy.save(update_fields=["visibility"])
        AccessGrant.objects.create(
            policy=self.policy,
            grantee=self.member,
        )
        self.client.force_login(self.member)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.VIEW_PRIVATE_RESOURCE
        )
        self.assertEqual(event.actor, self.member)
        self.assertEqual(event.person, self.person)
        self.assertEqual(
            event.resource_type,
            PrivacyPolicy.ResourceType.EMPLOYMENT,
        )
        self.assertEqual(event.object_id, self.employment.id)

    def test_owner_view_is_not_logged_as_granted_access(self):
        self.policy.visibility = PrivacyPolicy.Visibility.PRIVATE
        self.policy.save(update_fields=["visibility"])
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.VIEW_PRIVATE_RESOURCE
            ).exists()
        )

    def test_family_visible_resource_view_is_not_logged(self):
        self.client.force_login(self.member)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.VIEW_PRIVATE_RESOURCE
            ).exists()
        )
