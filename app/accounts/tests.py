import json
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from family.models import Person, ProfileOwnership

from .forms import InvitationCreateForm
from .models import Invitation, User


class InvitationAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="Admin-test-password-731!",
        )
        self.person = Person.objects.create(
            first_name="Алексей",
            last_name="Тестов",
        )
        self.invitation = Invitation.objects.create(
            person=self.person,
            email="relative@example.com",
            created_by=self.admin,
            expires_at=(
                timezone.now()
                + timedelta(days=7)
            ),
        )
        self.url = reverse(
            "accounts:accept_invitation",
            args=[self.invitation.token],
        )

    def test_weak_password_is_rejected_by_django_validators(self):
        response = self.client.post(
            self.url,
            {
                "username": "relative",
                "password1": "password",
                "password2": "password",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "password1",
            response.context["form"].errors,
        )
        self.assertFalse(
            User.objects.filter(
                email=self.invitation.email
            ).exists()
        )
        self.invitation.refresh_from_db()
        self.assertEqual(
            self.invitation.status,
            Invitation.Status.PENDING,
        )
        self.assertFalse(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.ACCEPT_INVITATION,
            ).exists()
        )

    def test_strong_password_accepts_invitation(self):
        response = self.client.post(
            self.url,
            {
                "username": "relative",
                "password1": "Long-Family-Passphrase-582!",
                "password2": "Long-Family-Passphrase-582!",
            },
        )

        self.assertRedirects(
            response,
            reverse("family:my_profile"),
            fetch_redirect_response=False,
        )
        user = User.objects.get(
            email=self.invitation.email
        )
        self.assertTrue(
            user.check_password(
                "Long-Family-Passphrase-582!"
            )
        )
        self.assertTrue(
            ProfileOwnership.objects.filter(
                user=user,
                person=self.person,
                status=ProfileOwnership.Status.CONFIRMED,
            ).exists()
        )
        self.invitation.refresh_from_db()
        self.assertEqual(
            self.invitation.status,
            Invitation.Status.ACCEPTED,
        )
        self.person.refresh_from_db()
        self.assertEqual(
            self.person.profile_status,
            Person.ProfileStatus.CLAIMED,
        )

    def test_existing_email_cannot_accept_or_create_audit_event(self):
        User.objects.create_user(
            username="existing-relative",
            email=self.invitation.email,
            password="Existing-user-password-936!",
        )

        response = self.client.post(
            self.url,
            {
                "username": "new-relative",
                "password1": "Long-Family-Passphrase-582!",
                "password2": "Long-Family-Passphrase-582!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.invitation.refresh_from_db()
        self.assertEqual(
            self.invitation.status,
            Invitation.Status.PENDING,
        )
        self.assertFalse(
            ProfileOwnership.objects.filter(
                person=self.person,
                status=ProfileOwnership.Status.CONFIRMED,
            ).exists()
        )
        self.assertFalse(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.ACCEPT_INVITATION,
            ).exists()
        )


class InvitationAuditTests(TestCase):
    password = "Invitation-audit-password-846!"

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="invitation-audit-admin",
            email="invitation-audit-admin@example.com",
            password=self.password,
        )
        self.person = Person.objects.create(
            first_name="Мария",
            last_name="Аудитова",
        )
        self.email = "invitee@example.com"

    def create_invitation(self):
        return Invitation.objects.create(
            person=self.person,
            email=self.email,
            created_by=self.admin,
            expires_at=(
                timezone.now()
                + timedelta(days=7)
            ),
        )

    def assert_invitation_details(
        self,
        event,
        invitation,
        *,
        user=None,
    ):
        self.assertEqual(
            event.details["invitation_id"],
            str(invitation.id),
        )
        self.assertEqual(
            event.details["email"],
            invitation.email,
        )

        if user is not None:
            self.assertEqual(
                event.details["user_id"],
                str(user.id),
            )

        serialized_details = json.dumps(
            event.details,
            sort_keys=True,
        )
        self.assertNotIn(
            str(invitation.token),
            serialized_details,
        )
        self.assertNotIn(
            invitation.token.hex,
            serialized_details,
        )
        self.assertNotIn(
            '"token"',
            serialized_details.lower(),
        )

    def test_create_invitation_is_audited_once(self):
        self.client.force_login(self.admin)
        url = reverse("accounts:create_invitation")
        payload = {
            "person": str(self.person.id),
            "email": self.email,
        }

        response = self.client.post(url, payload)

        self.assertEqual(response.status_code, 200)
        invitation = Invitation.objects.get(
            person=self.person,
        )
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.CREATE_INVITATION,
        )
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.person, self.person)
        self.assertEqual(event.object_id, invitation.id)
        self.assert_invitation_details(
            event,
            invitation,
        )

        repeat_response = self.client.post(
            url,
            payload,
        )

        self.assertEqual(repeat_response.status_code, 200)
        self.assertEqual(
            Invitation.objects.filter(
                person=self.person,
            ).count(),
            1,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                action=(
                    AuditEvent.Action.CREATE_INVITATION
                ),
            ).count(),
            1,
        )

    @patch("accounts.views.send_mail")
    def test_create_invitation_queues_email_after_commit(self, mocked_send_mail):
        self.client.force_login(self.admin)
        url = reverse("accounts:create_invitation")
        payload = {
            "person": str(self.person.id),
            "email": self.email,
        }

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(url, payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(callbacks), 1)
        mocked_send_mail.assert_called_once()
        call = mocked_send_mail.call_args.kwargs
        self.assertEqual(call["recipient_list"], [self.email])
        self.assertIn("Откройте ссылку для регистрации", call["message"])
        self.assertIn("/family/invite/", call["message"])
        self.assertFalse(call["fail_silently"])

    def test_accept_invitation_is_audited_once(self):
        invitation = self.create_invitation()
        url = reverse(
            "accounts:accept_invitation",
            args=[invitation.token],
        )
        payload = {
            "username": "invitation-audit-relative",
            "password1": self.password,
            "password2": self.password,
        }

        response = self.client.post(url, payload)

        self.assertRedirects(
            response,
            reverse("family:my_profile"),
            fetch_redirect_response=False,
        )
        user = User.objects.get(email=self.email)
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.ACCEPT_INVITATION,
        )
        self.assertEqual(event.actor, user)
        self.assertEqual(event.person, self.person)
        self.assertEqual(event.object_id, invitation.id)
        self.assert_invitation_details(
            event,
            invitation,
            user=user,
        )

        repeat_response = self.client.post(
            url,
            payload,
        )

        self.assertEqual(repeat_response.status_code, 200)
        self.assertEqual(
            AuditEvent.objects.filter(
                action=(
                    AuditEvent.Action.ACCEPT_INVITATION
                ),
            ).count(),
            1,
        )

    def test_cancel_invitation_is_audited_once(self):
        invitation = self.create_invitation()
        self.client.force_login(self.admin)
        url = reverse(
            "accounts:cancel_invitation",
            args=[invitation.id],
        )

        response = self.client.post(url)

        self.assertRedirects(
            response,
            reverse("accounts:invitation_list"),
            fetch_redirect_response=False,
        )
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.CANCEL_INVITATION,
        )
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.person, self.person)
        self.assertEqual(event.object_id, invitation.id)
        self.assert_invitation_details(
            event,
            invitation,
        )

        repeat_response = self.client.post(url)

        self.assertRedirects(
            repeat_response,
            reverse("accounts:invitation_list"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                action=(
                    AuditEvent.Action.CANCEL_INVITATION
                ),
            ).count(),
            1,
        )

    @patch(
        "accounts.views.log_audit_event",
        side_effect=RuntimeError("audit unavailable"),
    )
    def test_audit_failure_rolls_back_invitation_acceptance(
        self,
        mocked_log,
    ):
        invitation = self.create_invitation()
        url = reverse(
            "accounts:accept_invitation",
            args=[invitation.token],
        )

        with self.assertRaises(RuntimeError):
            self.client.post(
                url,
                {
                    "username": "rollback-relative",
                    "password1": self.password,
                    "password2": self.password,
                },
            )

        invitation.refresh_from_db()
        self.person.refresh_from_db()
        self.assertEqual(
            invitation.status,
            Invitation.Status.PENDING,
        )
        self.assertEqual(
            self.person.profile_status,
            Person.ProfileStatus.UNCLAIMED,
        )
        self.assertFalse(
            User.objects.filter(email=self.email).exists()
        )
        self.assertFalse(
            ProfileOwnership.objects.filter(
                person=self.person,
            ).exists()
        )
        mocked_log.assert_called_once()


class UserStatusAuthenticationTests(TestCase):
    password = "Authentication-test-password-927!"

    def create_user(self, status):
        return User.objects.create_user(
            username=status.lower(),
            email=f"{status.lower()}@example.com",
            password=self.password,
            status=status,
        )

    def test_active_user_can_log_in(self):
        user = self.create_user(User.Status.ACTIVE)

        authenticated = self.client.login(
            username=user.username,
            password=self.password,
        )

        self.assertTrue(authenticated)

    def test_invited_user_cannot_log_in(self):
        user = self.create_user(User.Status.INVITED)

        authenticated = self.client.login(
            username=user.username,
            password=self.password,
        )

        self.assertFalse(authenticated)

    def test_suspended_user_cannot_log_in(self):
        user = self.create_user(User.Status.SUSPENDED)

        authenticated = self.client.login(
            username=user.username,
            password=self.password,
        )

        self.assertFalse(authenticated)

    def test_disabled_user_cannot_log_in(self):
        user = self.create_user(User.Status.DISABLED)

        authenticated = self.client.login(
            username=user.username,
            password=self.password,
        )

        self.assertFalse(authenticated)

    def test_suspending_user_invalidates_existing_session(self):
        user = self.create_user(User.Status.ACTIVE)
        self.client.force_login(user)
        user.status = User.Status.SUSPENDED
        user.save(update_fields=["status"])

        response = self.client.get(
            reverse("family:home")
        )

        self.assertRedirects(
            response,
            f"{reverse('family:login')}?next={reverse('family:home')}",
            fetch_redirect_response=False,
        )


class UserEmailUniquenessTests(TestCase):
    def test_user_manager_normalizes_entire_email(self):
        user = User.objects.create_user(
            username="mixed-case",
            email="Relative@Example.COM",
            password="Email-test-password-614!",
        )

        self.assertEqual(
            user.email,
            "relative@example.com",
        )

    def test_database_rejects_case_insensitive_duplicate(self):
        User.objects.create_user(
            username="first",
            email="relative@example.com",
            password="Email-test-password-614!",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.bulk_create(
                    [
                        User(
                            username="second",
                            email="RELATIVE@EXAMPLE.COM",
                        )
                    ]
                )

    def test_invitation_form_rejects_existing_email_case_insensitively(self):
        User.objects.create_user(
            username="existing",
            email="relative@example.com",
            password="Email-test-password-614!",
        )
        person = Person.objects.create(
            first_name="Елена",
            last_name="Тестова",
        )
        form = InvitationCreateForm(
            data={
                "person": person.id,
                "email": "RELATIVE@EXAMPLE.COM",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
