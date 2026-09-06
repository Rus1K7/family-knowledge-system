from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from family.models import Person, ProfileOwnership
from heritage.models import Biography, LifeEvent, MediaAsset
from network.models import HelpOffer
from profiles.models import Education, Employment, Skill

from .models import AccessGrant, AccessRequest, PrivacyPolicy
from .permissions import (
    can_see_resource_existence,
    can_view_resource,
)


class PrivacyPermissionMatrixTests(TestCase):
    def setUp(self):
        self.owner = self.create_user("owner")
        self.member = self.create_user("member")
        self.historian = self.create_user(
            "historian",
            User.SystemRole.FAMILY_HISTORIAN,
        )
        self.admin = self.create_user(
            "admin",
            User.SystemRole.SYSTEM_ADMIN,
        )
        self.outsider = self.create_user("outsider")
        self.person = Person.objects.create(
            first_name="Владелец",
            last_name="Профиля",
        )
        ProfileOwnership.objects.create(
            user=self.owner,
            person=self.person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        self.add_family_membership(self.member, "Участник")
        self.add_family_membership(self.historian, "Историк")
        self.employment = Employment.objects.create(
            person=self.person,
            organization="Семейная организация",
        )

    def create_user(
        self,
        username,
        role=User.SystemRole.FAMILY_MEMBER,
    ):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="Privacy-test-password-418!",
            system_role=role,
        )

    def add_family_membership(self, user, first_name):
        related_person = Person.objects.create(
            first_name=first_name,
            last_name="Семьи",
        )
        ProfileOwnership.objects.create(
            user=user,
            person=related_person,
            status=ProfileOwnership.Status.CONFIRMED,
        )

    def create_policy(self, visibility, show_existence=True):
        policy, _ = PrivacyPolicy.objects.update_or_create(
            person=self.person,
            resource_type=PrivacyPolicy.ResourceType.EMPLOYMENT,
            object_id=self.employment.id,
            defaults={
                "visibility": visibility,
                "show_existence": show_existence,
            },
        )
        return policy

    def can_view(self, user):
        return can_view_resource(
            user,
            self.person,
            PrivacyPolicy.ResourceType.EMPLOYMENT,
            self.employment.id,
        )

    def can_see_existence(self, user):
        return can_see_resource_existence(
            user,
            self.person,
            PrivacyPolicy.ResourceType.EMPLOYMENT,
            self.employment.id,
        )

    def test_owner_and_admin_can_view_private_resource(self):
        self.create_policy(PrivacyPolicy.Visibility.PRIVATE)

        self.assertTrue(self.can_view(self.owner))
        self.assertTrue(self.can_view(self.admin))
        self.assertFalse(self.can_view(self.member))
        self.assertFalse(self.can_view(self.historian))

    def test_family_visibility_allows_authenticated_users_only(self):
        self.create_policy(PrivacyPolicy.Visibility.FAMILY)

        self.assertTrue(self.can_view(self.member))
        self.assertTrue(self.can_view(self.historian))
        self.assertFalse(self.can_view(self.outsider))
        self.assertFalse(self.can_view(AnonymousUser()))

    def test_missing_policy_denies_other_users(self):
        PrivacyPolicy.objects.filter(
            resource_type=PrivacyPolicy.ResourceType.EMPLOYMENT,
            object_id=self.employment.id,
        ).delete()

        self.assertFalse(self.can_view(self.member))
        self.assertFalse(self.can_view(AnonymousUser()))
        self.assertTrue(self.can_view(self.owner))
        self.assertTrue(self.can_view(self.admin))

    def test_selected_users_requires_active_grant(self):
        policy = self.create_policy(
            PrivacyPolicy.Visibility.SELECTED_USERS
        )
        self.assertFalse(self.can_view(self.member))

        grant = AccessGrant.objects.create(
            policy=policy,
            grantee=self.member,
            valid_until=timezone.now() + timedelta(days=1),
        )
        self.assertTrue(self.can_view(self.member))

        grant.valid_until = timezone.now() - timedelta(seconds=1)
        grant.save(update_fields=["valid_until"])
        self.assertFalse(self.can_view(self.member))

        grant.valid_until = None
        grant.revoked_at = timezone.now()
        grant.save(update_fields=["valid_until", "revoked_at"])
        self.assertFalse(self.can_view(self.member))

        AccessGrant.objects.create(
            policy=policy,
            grantee=self.outsider,
        )
        self.assertFalse(self.can_view(self.outsider))

    def test_request_only_requires_active_grant(self):
        policy = self.create_policy(
            PrivacyPolicy.Visibility.REQUEST_ONLY
        )
        self.assertFalse(self.can_view(self.member))

        AccessGrant.objects.create(
            policy=policy,
            grantee=self.member,
        )

        self.assertTrue(self.can_view(self.member))

    def test_owner_only_denies_other_authenticated_users(self):
        self.create_policy(PrivacyPolicy.Visibility.OWNER_ONLY)

        self.assertTrue(self.can_view(self.owner))
        self.assertFalse(self.can_view(self.member))
        self.assertFalse(self.can_view(self.historian))

    def test_show_existence_controls_locked_placeholder(self):
        policy = self.create_policy(
            PrivacyPolicy.Visibility.PRIVATE,
            show_existence=True,
        )
        self.assertTrue(self.can_see_existence(self.member))

        policy.show_existence = False
        policy.save(update_fields=["show_existence"])
        self.assertFalse(self.can_see_existence(self.member))


class PrivacyObjectAuthorizationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="Privacy-test-password-418!",
        )
        self.other_member = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="Privacy-test-password-418!",
        )
        self.person = Person.objects.create(
            first_name="Анна",
            last_name="Владелец",
        )
        ProfileOwnership.objects.create(
            user=self.owner,
            person=self.person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        other_person = Person.objects.create(
            first_name="Другой",
            last_name="Участник",
        )
        ProfileOwnership.objects.create(
            user=self.other_member,
            person=other_person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        self.employment = Employment.objects.create(
            person=self.person,
            organization="Организация",
        )

    def test_owner_can_edit_resource_privacy(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                "privacy:edit_privacy",
                args=[
                    PrivacyPolicy.ResourceType.EMPLOYMENT,
                    self.employment.id,
                ],
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_other_member_cannot_edit_resource_privacy_by_uuid(self):
        self.client.force_login(self.other_member)

        response = self.client.get(
            reverse(
                "privacy:edit_privacy",
                args=[
                    PrivacyPolicy.ResourceType.EMPLOYMENT,
                    self.employment.id,
                ],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_other_member_cannot_approve_access_request(self):
        policy = PrivacyPolicy.objects.get(
            resource_type=PrivacyPolicy.ResourceType.EMPLOYMENT,
            object_id=self.employment.id,
        )
        policy.visibility = PrivacyPolicy.Visibility.REQUEST_ONLY
        policy.save(update_fields=["visibility"])
        access_request = AccessRequest.objects.create(
            policy=policy,
            requester=self.other_member,
        )
        intruder = User.objects.create_user(
            username="intruder",
            email="intruder@example.com",
            password="Privacy-test-password-418!",
        )
        self.client.force_login(intruder)

        response = self.client.post(
            reverse(
                "privacy:approve_access_request",
                args=[access_request.id, "24h"],
            )
        )

        self.assertEqual(response.status_code, 403)
        access_request.refresh_from_db()
        self.assertEqual(
            access_request.status,
            AccessRequest.Status.PENDING,
        )
        self.assertFalse(AccessGrant.objects.exists())

    def test_unaffiliated_account_cannot_request_access(self):
        policy = PrivacyPolicy.objects.get(
            resource_type=PrivacyPolicy.ResourceType.EMPLOYMENT,
            object_id=self.employment.id,
        )
        policy.visibility = PrivacyPolicy.Visibility.REQUEST_ONLY
        policy.save(update_fields=["visibility"])
        outsider = User.objects.create_user(
            username="outsider",
            email="outsider@example.com",
            password="Privacy-test-password-418!",
        )
        self.client.force_login(outsider)

        response = self.client.get(
            reverse(
                "privacy:request_access",
                args=[policy.id],
            )
        )

        self.assertEqual(response.status_code, 403)


class DefaultPrivacyPolicySignalTests(TestCase):
    def setUp(self):
        self.person = Person.objects.create(
            first_name="Пётр",
            last_name="Тестов",
        )

    def assert_family_policy(self, resource, resource_type):
        policy = PrivacyPolicy.objects.get(
            resource_type=resource_type,
            object_id=resource.id,
        )
        self.assertEqual(policy.person, self.person)
        self.assertEqual(
            policy.visibility,
            PrivacyPolicy.Visibility.FAMILY,
        )
        self.assertTrue(policy.show_existence)

    def test_supported_resources_receive_default_policy(self):
        resources = [
            (
                Employment.objects.create(
                    person=self.person,
                    organization="Организация",
                ),
                PrivacyPolicy.ResourceType.EMPLOYMENT,
            ),
            (
                Education.objects.create(
                    person=self.person,
                    institution="Университет",
                ),
                PrivacyPolicy.ResourceType.EDUCATION,
            ),
            (
                Skill.objects.create(
                    person=self.person,
                    name="Навык",
                ),
                PrivacyPolicy.ResourceType.SKILL,
            ),
            (
                HelpOffer.objects.create(
                    person=self.person,
                    title="Помощь",
                ),
                PrivacyPolicy.ResourceType.HELP_OFFER,
            ),
            (
                Biography.objects.create(
                    person=self.person,
                    text="Биография",
                ),
                PrivacyPolicy.ResourceType.BIOGRAPHY,
            ),
            (
                LifeEvent.objects.create(
                    person=self.person,
                    title="Событие",
                ),
                PrivacyPolicy.ResourceType.LIFE_EVENT,
            ),
            (
                MediaAsset.objects.create(
                    person=self.person,
                    media_type=MediaAsset.MediaType.PHOTO,
                    title="Фото",
                    file="persons/test/photo.jpg",
                ),
                PrivacyPolicy.ResourceType.MEDIA_ASSET,
            ),
        ]

        for resource, resource_type in resources:
            with self.subTest(resource_type=resource_type):
                self.assert_family_policy(
                    resource,
                    resource_type,
                )

    def test_deleting_resource_removes_policy_grants_and_requests(self):
        employment = Employment.objects.create(
            person=self.person,
            organization="Удаляемая организация",
        )
        policy = PrivacyPolicy.objects.get(
            resource_type=PrivacyPolicy.ResourceType.EMPLOYMENT,
            object_id=employment.id,
        )
        requester = User.objects.create_user(
            username="requester",
            email="requester@example.com",
            password="Privacy-test-password-418!",
        )
        AccessGrant.objects.create(
            policy=policy,
            grantee=requester,
        )
        AccessRequest.objects.create(
            policy=policy,
            requester=requester,
        )

        employment.delete()

        self.assertFalse(
            PrivacyPolicy.objects.filter(id=policy.id).exists()
        )
        self.assertFalse(AccessGrant.objects.exists())
        self.assertFalse(AccessRequest.objects.exists())


class PrivacyAuditEventTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="audit-owner",
            email="audit-owner@example.com",
            password="Privacy-test-password-418!",
        )
        self.member = User.objects.create_user(
            username="audit-member",
            email="audit-member@example.com",
            password="Privacy-test-password-418!",
        )
        self.person = Person.objects.create(
            first_name="Владелец",
            last_name="Аудита",
        )
        ProfileOwnership.objects.create(
            user=self.owner,
            person=self.person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        member_person = Person.objects.create(
            first_name="Участник",
            last_name="Аудита",
        )
        ProfileOwnership.objects.create(
            user=self.member,
            person=member_person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        self.employment = Employment.objects.create(
            person=self.person,
            organization="Аудируемая организация",
        )
        self.policy = PrivacyPolicy.objects.get(
            resource_type=PrivacyPolicy.ResourceType.EMPLOYMENT,
            object_id=self.employment.id,
        )

    def get_event(self, action):
        return AuditEvent.objects.get(action=action)

    def assert_resource_context(self, event, actor):
        self.assertEqual(event.actor, actor)
        self.assertEqual(event.person, self.person)
        self.assertEqual(
            event.resource_type,
            PrivacyPolicy.ResourceType.EMPLOYMENT,
        )
        self.assertEqual(event.object_id, self.employment.id)

    def test_policy_update_logs_old_and_new_values_only_once(self):
        self.client.force_login(self.owner)
        url = reverse(
            "privacy:edit_privacy",
            args=[
                PrivacyPolicy.ResourceType.EMPLOYMENT,
                self.employment.id,
            ],
        )
        data = {
            "visibility": PrivacyPolicy.Visibility.OWNER_ONLY,
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)
        event = self.get_event(
            AuditEvent.Action.UPDATE_PRIVACY_POLICY
        )
        self.assert_resource_context(event, self.owner)
        self.assertEqual(
            event.details,
            {
                "old": {
                    "visibility": PrivacyPolicy.Visibility.FAMILY,
                    "show_existence": True,
                },
                "new": {
                    "visibility": PrivacyPolicy.Visibility.OWNER_ONLY,
                    "show_existence": False,
                },
            },
        )

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.UPDATE_PRIVACY_POLICY,
            ).count(),
            1,
        )

    def test_access_request_creation_is_audited(self):
        self.policy.visibility = PrivacyPolicy.Visibility.REQUEST_ONLY
        self.policy.save(update_fields=["visibility"])
        self.client.force_login(self.member)

        response = self.client.post(
            reverse(
                "privacy:request_access",
                args=[self.policy.id],
            ),
            {"reason": "Нужен доступ для семейного исследования"},
        )

        self.assertEqual(response.status_code, 302)
        access_request = AccessRequest.objects.get(
            policy=self.policy,
            requester=self.member,
        )
        event = self.get_event(AuditEvent.Action.REQUEST_ACCESS)
        self.assert_resource_context(event, self.member)
        self.assertEqual(
            event.details["request_id"],
            str(access_request.id),
        )
        self.assertEqual(
            event.details["requester_id"],
            str(self.member.id),
        )

    def test_repeated_access_request_does_not_create_duplicate(self):
        self.policy.visibility = PrivacyPolicy.Visibility.REQUEST_ONLY
        self.policy.save(update_fields=["visibility"])
        self.client.force_login(self.member)
        url = reverse(
            "privacy:request_access",
            args=[self.policy.id],
        )

        first = self.client.post(url, {"reason": "Первый запрос"})
        second = self.client.post(url, {"reason": "Повторный запрос"})

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(
            AccessRequest.objects.filter(
                policy=self.policy,
                requester=self.member,
                status=AccessRequest.Status.PENDING,
            ).count(),
            1,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.REQUEST_ACCESS,
            ).count(),
            1,
        )

    def test_access_request_rejection_is_audited(self):
        access_request = AccessRequest.objects.create(
            policy=self.policy,
            requester=self.member,
            reason="Проверяем отклонение",
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "privacy:reject_access_request",
                args=[access_request.id],
            )
        )

        self.assertEqual(response.status_code, 302)
        event = self.get_event(AuditEvent.Action.REJECT_ACCESS)
        self.assert_resource_context(event, self.owner)
        self.assertEqual(
            event.details["request_id"],
            str(access_request.id),
        )
        self.assertEqual(
            event.details["requester_id"],
            str(self.member.id),
        )

    def test_access_request_approval_audits_grantee_and_grant(self):
        access_request = AccessRequest.objects.create(
            policy=self.policy,
            requester=self.member,
            reason="Проверяем одобрение",
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "privacy:approve_access_request",
                args=[access_request.id, "24h"],
            )
        )

        self.assertEqual(response.status_code, 302)
        grant = AccessGrant.objects.get(
            policy=self.policy,
            grantee=self.member,
        )
        event = self.get_event(AuditEvent.Action.GRANT_ACCESS)
        self.assert_resource_context(event, self.owner)
        self.assertEqual(
            event.details["grantee_id"],
            str(self.member.id),
        )
        self.assertEqual(
            event.details["grant_id"],
            str(grant.id),
        )

    def test_manual_grant_is_audited_only_when_access_changes(self):
        self.policy.visibility = PrivacyPolicy.Visibility.SELECTED_USERS
        self.policy.save(update_fields=["visibility"])
        self.client.force_login(self.owner)
        url = reverse(
            "privacy:grant_selected_user",
            args=[self.policy.id],
        )

        response = self.client.post(url, {"user": self.member.id})

        self.assertEqual(response.status_code, 302)
        grant = AccessGrant.objects.get(
            policy=self.policy,
            grantee=self.member,
        )
        event = self.get_event(AuditEvent.Action.GRANT_ACCESS)
        self.assert_resource_context(event, self.owner)
        self.assertEqual(
            event.details["grantee_id"],
            str(self.member.id),
        )
        self.assertEqual(
            event.details["grant_id"],
            str(grant.id),
        )

        response = self.client.post(url, {"user": self.member.id})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.GRANT_ACCESS,
            ).count(),
            1,
        )

    def test_revoke_access_audits_grantee_and_grant(self):
        grant = AccessGrant.objects.create(
            policy=self.policy,
            grantee=self.member,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "privacy:revoke_access_grant",
                args=[grant.id],
            )
        )

        self.assertEqual(response.status_code, 302)
        event = self.get_event(AuditEvent.Action.REVOKE_ACCESS)
        self.assert_resource_context(event, self.owner)
        self.assertEqual(
            event.details["grantee_id"],
            str(self.member.id),
        )
        self.assertEqual(
            event.details["grant_id"],
            str(grant.id),
        )
