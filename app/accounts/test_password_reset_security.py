from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordResetConfirmView
from django.db import DatabaseError, close_old_connections, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import User
from .login_throttle import reserve_password_reset_email, reserve_password_reset_ip


def link_for(user):
    return reverse("family:password_reset_confirm", kwargs={
        "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
        "token": default_token_generator.make_token(user),
    })


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class PasswordResetSecurityTests(TestCase):
    old_password = "Original-password-429!"
    new_password = "Replacement-password-563!"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="recovery-security", email="recovery-security@example.com",
            password=cls.old_password,
        )

    def payload(self, password=None):
        return {"new_password1": password or self.new_password,
                "new_password2": password or self.new_password}

    def open_form(self, client=None):
        client = client or self.client
        original = link_for(self.user)
        response = client.get(original)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", response["Cache-Control"])
        return original, response["Location"]

    def assert_invalid(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["validlink"])
        self.assertNotContains(response, 'name="new_password1"')
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_status_changes_disable_both_original_and_opened_links(self):
        for status, is_active in (
            (User.Status.SUSPENDED, True), (User.Status.DISABLED, True),
            (User.Status.INVITED, True), (User.Status.ACTIVE, False),
        ):
            with self.subTest(status=status, is_active=is_active):
                User.objects.filter(pk=self.user.pk).update(status=User.Status.ACTIVE, is_active=True)
                self.user.refresh_from_db()
                client = Client()
                original, form_url = self.open_form(client)
                User.objects.filter(pk=self.user.pk).update(status=status, is_active=is_active)
                self.assert_invalid(client.get(original))
                self.assert_invalid(client.get(form_url))
                self.assert_invalid(client.post(form_url, self.payload()))
                self.user.refresh_from_db()
                self.assertTrue(self.user.check_password(self.old_password))
                self.assertEqual(self.user.status, status)
                self.assertEqual(self.user.is_active, is_active)

    def test_link_expires_after_one_hour_even_when_form_is_already_open(self):
        issued_at = datetime(2026, 9, 6, 12, 0, 0)
        with patch.object(default_token_generator, "_now", return_value=issued_at):
            original, form_url = self.open_form()
        with patch.object(default_token_generator, "_now", return_value=issued_at + timedelta(seconds=3601)):
            self.assert_invalid(self.client.get(original))
            self.assert_invalid(self.client.get(form_url))
            self.assert_invalid(self.client.post(form_url, self.payload()))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_changed_email_invalidates_opened_link(self):
        original, form_url = self.open_form()
        User.objects.filter(pk=self.user.pk).update(email="changed@example.com")
        self.assert_invalid(self.client.get(original))
        self.assert_invalid(self.client.post(form_url, self.payload()))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_weak_or_mismatched_password_is_rejected_without_consuming_link(self):
        _, form_url = self.open_form()
        for payload in (
            self.payload("12345678"),
            {"new_password1": self.new_password, "new_password2": "different"},
        ):
            response = self.client.post(form_url, payload)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["validlink"])
            self.assertTrue(response.context["form"].errors)
            self.user.refresh_from_db()
            self.assertTrue(self.user.check_password(self.old_password))
        self.assertRedirects(self.client.post(form_url, self.payload()), reverse("family:password_reset_complete"))

    def test_reset_invalidates_previous_sessions_and_does_not_auto_login(self):
        previous = Client()
        previous.force_login(self.user)
        self.user.refresh_from_db()  # last_login is part of the token hash.
        original, form_url = self.open_form()
        self.assertRedirects(self.client.post(form_url, self.payload()), reverse("family:password_reset_complete"))
        self.assertNotIn("_auth_user_id", self.client.session)
        response = previous.get(reverse("family:login"))
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertNotIn("_auth_user_id", previous.session)
        self.assert_invalid(self.client.get(original))
        self.assert_invalid(self.client.post(form_url, self.payload("Another-password-946!")))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))

    def test_password_save_failure_rolls_back_and_does_not_consume_link(self):
        _, form_url = self.open_form()
        with patch.object(User, "save", side_effect=DatabaseError("private database details")):
            response = self.client.post(form_url, self.payload())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "60")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotContains(response, "private database details", status_code=503)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))
        self.assertRedirects(self.client.post(form_url, self.payload()), reverse("family:password_reset_complete"))

    def test_confirmation_requires_csrf_even_with_a_valid_link(self):
        client = Client(enforce_csrf_checks=True)
        _, form_url = self.open_form(client)
        self.assertEqual(client.get(form_url).status_code, 200)
        self.assertEqual(client.post(form_url, self.payload()).status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))
        payload = {**self.payload(), "csrfmiddlewaretoken": client.cookies["csrftoken"].value}
        self.assertRedirects(client.post(form_url, payload), reverse("family:password_reset_complete"))


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
@skipUnlessDBFeature("has_select_for_update")
class ConcurrentPasswordResetTests(TransactionTestCase):
    def test_parallel_requests_from_different_ips_share_email_quota(self):
        barrier = Barrier(6)

        def reserve(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                wait = reserve_password_reset_ip(f"192.0.2.{index + 1}")
                email = "Shared@Example.COM" if index % 2 else "shared@example.com"
                return wait, reserve_password_reset_email(email)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(reserve, range(6)))
        self.assertEqual([wait for wait, _ in results], [0] * 6)
        self.assertEqual(sum(admitted for _, admitted in results), 3)

    def test_same_link_in_two_browsers_only_changes_password_once(self):
        user = User.objects.create_user(
            username="concurrent-recovery", email="concurrent-recovery@example.com",
            password="Original-password-486!",
        )
        original = link_for(user)
        clients = [Client(), Client()]
        form_urls = [client.get(original)["Location"] for client in clients]
        passwords = ["First-new-password-734!", "Second-new-password-569!"]
        barrier = Barrier(2)
        get_user = PasswordResetConfirmView.get_user

        def simultaneous_read(view, uid):
            current = get_user(view, uid)
            barrier.wait(timeout=10)
            return current

        def submit(index):
            close_old_connections()
            try:
                response = clients[index].post(form_urls[index], {
                    "new_password1": passwords[index], "new_password2": passwords[index],
                })
                return response.status_code, index
            finally:
                connections.close_all()

        # Both requests read the old state before the subclass locks/refetches it.
        with patch.object(PasswordResetConfirmView, "get_user", simultaneous_read):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(submit, range(2)))
        self.assertEqual(sorted(status for status, _ in results), [200, 302])
        winner = next(index for status, index in results if status == 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password(passwords[winner]))
        self.assertFalse(user.check_password(passwords[1 - winner]))
