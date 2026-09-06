from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

from django.core import mail
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .login_throttle import reserve_password_reset_email, reserve_password_reset_ip
from .models import LoginAttemptWindow, User


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class PasswordResetLimitTests(TestCase):
    password = "Current-password-for-limits-927!"
    new_password = "Replacement-password-for-limits-384!"
    address = "192.0.2.20"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="limited-relative",
            email="limit.relative@example.com",
            password=cls.password,
            status=User.Status.ACTIVE,
        )

    def request_reset(self, email=None, address=None, **kwargs):
        return self.client.post(
            reverse("family:password_reset"),
            {"email": self.user.email if email is None else email},
            REMOTE_ADDR=address or self.address,
            **kwargs,
        )

    def assert_temporarily_unavailable(self, response):
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "60")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotContains(response, "private database detail", status_code=503)
        self.assertEqual(mail.outbox, [])

    def test_sixth_ip_request_is_blocked_despite_changing_forwarded_headers(self):
        for number in range(5):
            response = self.request_reset(
                HTTP_X_FORWARDED_FOR=f"198.51.100.{number + 1}",
                HTTP_X_REAL_IP=f"203.0.113.{number + 1}",
            )
            self.assertRedirects(response, reverse("family:password_reset_done"))
        self.assertEqual(len(mail.outbox), 3)
        stored_windows = LoginAttemptWindow.objects.count()

        response = self.request_reset(
            email="another-address@example.com",
            HTTP_X_FORWARDED_FOR="198.51.100.99",
            HTTP_X_REAL_IP="203.0.113.99",
        )
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response["Retry-After"]), 0)
        self.assertLessEqual(int(response["Retry-After"]), 900)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(LoginAttemptWindow.objects.count(), stored_windows)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_email_quota_is_global_and_returns_same_success_page_as_unknown_email(self):
        pages = []
        for email in (self.user.email, "unknown-relative@example.com"):
            for number in range(4):
                response = self.request_reset(
                    email=email,
                    address=f"198.51.100.{number + 1}",
                    follow=True,
                )
                self.assertEqual(
                    response.redirect_chain,
                    [(reverse("family:password_reset_done"), 302)],
                )
                self.assertEqual(response.status_code, 200)
                pages.append(response.content)
        self.assertEqual(len(mail.outbox), 3)
        self.assertTrue(all(page == pages[0] for page in pages))

    def test_normalized_email_aliases_share_an_opaque_counter(self):
        for email in (
            "  LIMIT.RELATIVE@EXAMPLE.COM  ",
            "ｌｉｍｉｔ.relative@example.com",
            self.user.email,
        ):
            self.assertTrue(reserve_password_reset_email(email))
        self.assertEqual(LoginAttemptWindow.objects.count(), 1)
        key = LoginAttemptWindow.objects.get().key
        self.assertRegex(key, r"^[0-9a-f]{64}$")
        self.assertNotIn(self.user.email, key)

        response = self.request_reset(email=" Limit.Relative@Example.Com ")
        self.assertRedirects(response, reverse("family:password_reset_done"))
        self.assertEqual(mail.outbox, [])
        self.assertEqual(
            sorted(LoginAttemptWindow.objects.values_list("attempts", flat=True)),
            [1, 3],
        )

    def test_invalid_forms_consume_ip_budget_but_no_email_budget(self):
        with patch("accounts.forms.reserve_password_reset_email") as reserve_email:
            for _ in range(5):
                response = self.request_reset(email="not an email")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
            self.assertEqual(self.request_reset().status_code, 429)
        reserve_email.assert_not_called()
        self.assertEqual(mail.outbox, [])
        self.assertEqual(LoginAttemptWindow.objects.count(), 1)

    def test_get_head_and_csrf_rejections_do_not_consume_budget(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR=self.address)
        url = reverse("family:password_reset")
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.head(url).status_code, 200)
        self.assertEqual(client.post(url, {"email": self.user.email}).status_code, 403)
        self.assertFalse(LoginAttemptWindow.objects.exists())
        self.assertEqual(mail.outbox, [])

        csrf_token = client.cookies["csrftoken"].value
        for _ in range(5):
            response = client.post(
                url, {"email": self.user.email}, HTTP_X_CSRFTOKEN=csrf_token,
            )
            self.assertRedirects(response, reverse("family:password_reset_done"))
        response = client.post(
            url, {"email": self.user.email}, HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(mail.outbox), 3)

    def test_unknown_and_ineligible_addresses_also_consume_email_quota(self):
        addresses = ["unregistered@example.com"]
        for status in (User.Status.INVITED, User.Status.SUSPENDED, User.Status.DISABLED):
            user = User.objects.create_user(
                username=f"member-{status.lower()}",
                email=f"member-{status.lower()}@example.com",
                password=self.password,
                status=status,
            )
            addresses.append(user.email)
        inactive = User.objects.create_user(
            username="inactive-member", email="inactive@example.com",
            password=self.password, status=User.Status.ACTIVE, is_active=False,
        )
        addresses.append(inactive.email)

        for index, email in enumerate(addresses):
            with self.subTest(email=email):
                for number in range(3):
                    response = self.request_reset(
                        email=email, address=f"203.0.113.{index * 3 + number + 1}",
                    )
                    self.assertRedirects(response, reverse("family:password_reset_done"))
                self.assertFalse(reserve_password_reset_email(email))
        self.assertEqual(mail.outbox, [])

    def test_ip_counter_database_failure_stops_before_mail_and_hides_details(self):
        with patch(
            "accounts.middleware.reserve_password_reset_ip",
            side_effect=DatabaseError("private database detail"),
        ), patch("accounts.forms.reserve_password_reset_email") as reserve_email:
            response = self.request_reset()
        reserve_email.assert_not_called()
        self.assert_temporarily_unavailable(response)

    def test_email_counter_database_failure_stops_mail_and_hides_details(self):
        with patch(
            "accounts.forms.reserve_password_reset_email",
            side_effect=DatabaseError("private database detail"),
        ):
            response = self.request_reset()
        self.assert_temporarily_unavailable(response)

    def test_recovery_limit_preserves_valid_login_and_already_issued_reset_link(self):
        self.request_reset()
        link = next(
            line.strip() for line in mail.outbox[0].body.splitlines()
            if line.strip().startswith(("http://", "https://"))
        )
        token_url = urlsplit(link).path
        for _ in range(4):
            self.request_reset()
        self.assertEqual(self.request_reset().status_code, 429)

        reset_client = Client(REMOTE_ADDR=self.address)
        response = reset_client.get(token_url)
        self.assertEqual(response.status_code, 302)
        response = reset_client.post(
            response["Location"],
            {"new_password1": self.new_password, "new_password2": self.new_password},
        )
        self.assertRedirects(response, reverse("family:password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertNotIn("_auth_user_id", reset_client.session)

        # Redeem before login: login changes last_login and legitimately
        # invalidates a Django reset token independently of any rate limit.
        response = self.client.post(
            reverse("family:login"),
            {"username": self.user.username, "password": self.new_password},
            REMOTE_ADDR=self.address,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))

    def test_login_limit_does_not_consume_recovery_budget(self):
        for _ in range(5):
            self.client.post(
                reverse("family:login"),
                {"username": self.user.username, "password": "incorrect"},
                REMOTE_ADDR=self.address,
            )
        response = self.client.post(
            reverse("family:login"),
            {"username": self.user.username, "password": self.password},
            REMOTE_ADDR=self.address,
        )
        self.assertEqual(response.status_code, 429)
        self.assertRedirects(self.request_reset(), reverse("family:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_fixed_windows_expire_without_being_extended_by_denied_requests(self):
        now = timezone.now()
        with patch("accounts.login_throttle.timezone.now", return_value=now):
            for _ in range(5):
                self.assertEqual(reserve_password_reset_ip(self.address), 0)
            for _ in range(3):
                self.assertTrue(reserve_password_reset_email(self.user.email))
            self.assertEqual(reserve_password_reset_ip(self.address), 900)
            self.assertFalse(reserve_password_reset_email(self.user.email))
        with patch(
            "accounts.login_throttle.timezone.now", return_value=now + timedelta(seconds=121),
        ):
            self.assertEqual(reserve_password_reset_ip(self.address), 779)
            self.assertFalse(reserve_password_reset_email(self.user.email))
        self.assertEqual(
            set(LoginAttemptWindow.objects.values_list("expires_at", flat=True)),
            {now + timedelta(seconds=900)},
        )
        self.assertEqual(
            sorted(LoginAttemptWindow.objects.values_list("attempts", flat=True)), [3, 5],
        )
        with patch(
            "accounts.login_throttle.timezone.now", return_value=now + timedelta(seconds=900),
        ):
            self.assertEqual(reserve_password_reset_ip(self.address), 0)
            self.assertTrue(reserve_password_reset_email(self.user.email))
        self.assertEqual(
            list(LoginAttemptWindow.objects.values_list("attempts", flat=True)), [1, 1],
        )
