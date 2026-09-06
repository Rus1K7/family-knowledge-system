from datetime import timedelta
from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import LoginAttemptWindow, User


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    SECURE_SSL_REDIRECT=False,
)
class LoginThrottleHTTPTests(TestCase):
    password = "Login-throttle-test-password-936!"
    remote_addr = "192.0.2.10"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="throttle-relative",
            email="throttle-relative@example.com",
            password=cls.password,
            status=User.Status.ACTIVE,
            is_staff=True,
        )

    def setUp(self):
        self.login_urls = (reverse("family:login"), reverse("admin:login"))

    def post_login(
        self,
        url,
        *,
        client=None,
        username="unknown-relative",
        password="incorrect-password",
        remote_addr=None,
        fields=None,
        headers=None,
    ):
        payload = {"username": username, "password": password}
        payload.update(fields or {})
        return (client or self.client).post(
            url,
            payload,
            REMOTE_ADDR=remote_addr or self.remote_addr,
            **(headers or {}),
        )

    def assert_throttled(self, response):
        self.assertEqual(response.status_code, 429)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        retry_after = response.headers.get("Retry-After", "")
        self.assertTrue(retry_after.isdecimal(), retry_after)
        self.assertGreater(int(retry_after), 0)
        self.assertLessEqual(int(retry_after), 900)

    def test_get_and_head_do_not_consume_attempts_on_either_login(self):
        for url in self.login_urls:
            with self.subTest(url=url):
                for _ in range(6):
                    self.assertEqual(self.client.get(url).status_code, 200)
                    self.assertEqual(self.client.head(url).status_code, 200)

        self.assertFalse(LoginAttemptWindow.objects.exists())

    def test_each_login_allows_five_wrong_passwords_then_limits(self):
        for index, url in enumerate(self.login_urls):
            with self.subTest(url=url):
                remote_addr = f"192.0.2.{20 + index}"
                for _ in range(5):
                    response = self.post_login(url, remote_addr=remote_addr)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.context["form"].errors)

                self.assert_throttled(
                    self.post_login(url, remote_addr=remote_addr)
                )

    def test_limits_are_shared_across_endpoints_clients_and_form_changes(self):
        for index in range(5):
            response = self.post_login(
                self.login_urls[index % 2],
                client=Client(),
                fields={"next": f"/family/?attempt={index}", "nonce": index},
            )
            self.assertEqual(response.status_code, 200)

        for url in self.login_urls:
            with self.subTest(url=url):
                self.assert_throttled(
                    self.post_login(
                        url + "?next=/family/",
                        client=Client(),
                        password="another-incorrect-password",
                        fields={"next": "/admin/"},
                    )
                )

    def test_username_nfkc_whitespace_and_case_share_one_limit(self):
        variants = (
            "unknown-relative",
            "UNKNOWN-RELATIVE",
            "  Unknown-Relative  ",
            "ｕｎｋｎｏｗｎ－ｒｅｌａｔｉｖｅ",
            "\tunknown-relative\n",
        )
        for index, username in enumerate(variants):
            response = self.post_login(
                self.login_urls[index % 2], username=username
            )
            self.assertEqual(response.status_code, 200)

        self.assert_throttled(
            self.post_login(self.login_urls[0], username="Unknown-Relative")
        )

    def test_another_ip_or_username_has_its_own_pair_limit(self):
        url = self.login_urls[0]
        for _ in range(5):
            self.assertEqual(self.post_login(url).status_code, 200)
        self.assert_throttled(self.post_login(url))

        self.assertEqual(
            self.post_login(url, username="another-relative").status_code, 200
        )
        self.assertEqual(
            self.post_login(url, remote_addr="192.0.2.11").status_code, 200
        )

    def test_ip_limit_covers_different_usernames_and_ignores_proxy_headers(self):
        for index in range(30):
            response = self.post_login(
                self.login_urls[index % 2],
                username=f"unknown-relative-{index}",
                headers={
                    "HTTP_X_FORWARDED_FOR": f"198.51.100.{index + 1}",
                    "HTTP_FORWARDED": f"for=203.0.113.{index + 1}",
                    "HTTP_X_REAL_IP": f"198.51.100.{index + 100}",
                },
            )
            self.assertEqual(response.status_code, 200)

        for url in self.login_urls:
            with self.subTest(url=url):
                self.assert_throttled(
                    self.post_login(
                        url,
                        username="one-more-relative",
                        headers={
                            "HTTP_X_FORWARDED_FOR": "203.0.113.200",
                            "HTTP_FORWARDED": "for=203.0.113.201",
                            "HTTP_X_REAL_IP": "203.0.113.202",
                        },
                    )
                )

        self.assertEqual(
            self.post_login(
                self.login_urls[0],
                username="one-more-relative",
                remote_addr="192.0.2.11",
                headers={"HTTP_X_FORWARDED_FOR": self.remote_addr},
            ).status_code,
            200,
        )

    def test_expired_windows_allow_a_new_full_set_of_attempts(self):
        url = self.login_urls[0]
        for _ in range(5):
            self.assertEqual(self.post_login(url).status_code, 200)
        self.assert_throttled(self.post_login(url))

        LoginAttemptWindow.objects.update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        for _ in range(5):
            self.assertEqual(self.post_login(url).status_code, 200)
        self.assert_throttled(self.post_login(url))

    def test_successful_logins_are_counted_and_do_not_clear_previous_attempts(self):
        for index in range(5):
            client = Client()
            response = self.post_login(
                self.login_urls[index % 2],
                client=client,
                username=self.user.username,
                password=self.password,
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(client.session.get("_auth_user_id"), str(self.user.pk))

        for url in self.login_urls:
            with self.subTest(url=url):
                client = Client()
                response = self.post_login(
                    url,
                    client=client,
                    username=self.user.username,
                    password=self.password,
                )
                self.assert_throttled(response)
                self.assertNotIn("_auth_user_id", client.session)

    def test_disabled_and_non_active_accounts_cannot_login_or_bypass_limits(self):
        states = (
            (User.Status.INVITED, True),
            (User.Status.SUSPENDED, True),
            (User.Status.DISABLED, True),
            (User.Status.ACTIVE, False),
        )
        for index, (status, is_active) in enumerate(states):
            with self.subTest(status=status, is_active=is_active):
                User.objects.filter(pk=self.user.pk).update(
                    status=status, is_active=is_active
                )
                remote_addr = f"192.0.2.{40 + index}"
                client = Client()
                for attempt in range(5):
                    response = self.post_login(
                        self.login_urls[attempt % 2],
                        client=client,
                        username=self.user.username,
                        password=self.password,
                        remote_addr=remote_addr,
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn("_auth_user_id", client.session)

                self.assert_throttled(
                    self.post_login(
                        self.login_urls[1],
                        client=client,
                        username=self.user.username,
                        password=self.password,
                        remote_addr=remote_addr,
                    )
                )

    def test_authenticated_staff_posts_are_still_limited_on_both_logins(self):
        for index, url in enumerate(self.login_urls):
            with self.subTest(url=url):
                client = Client()
                client.force_login(self.user)
                remote_addr = f"192.0.2.{70 + index}"
                for _ in range(5):
                    response = self.post_login(
                        url,
                        client=client,
                        username=self.user.username,
                        password=self.password,
                        remote_addr=remote_addr,
                    )
                    self.assertEqual(response.status_code, 302)

                response = self.post_login(
                    url,
                    client=client,
                    username=self.user.username,
                    password=self.password,
                    remote_addr=remote_addr,
                )
                self.assert_throttled(response)
                self.assertEqual(
                    client.session.get("_auth_user_id"), str(self.user.pk)
                )

    def test_limited_response_does_not_disclose_account_or_submitted_values(self):
        for url_index, url in enumerate(self.login_urls):
            bodies = []
            for index, username in enumerate(
                (self.user.username, "private-nonexistent-relative")
            ):
                remote_addr = f"192.0.2.{50 + url_index * 2 + index}"
                for _ in range(5):
                    self.post_login(
                        url,
                        username=username,
                        remote_addr=remote_addr,
                    )
                response = self.post_login(
                    url,
                    username=username,
                    password="sensitive-submitted-password",
                    remote_addr=remote_addr,
                )
                self.assert_throttled(response)
                body = response.content.decode()
                self.assertNotIn(username, body)
                self.assertNotIn(self.user.email, body)
                self.assertNotIn(remote_addr, body)
                self.assertNotIn("sensitive-submitted-password", body)
                self.assertRegex(body, "[А-Яа-яЁё]")
                bodies.append(body)

            with self.subTest(url=url):
                self.assertEqual(bodies[0], bodies[1])

    def test_database_failure_fails_closed_without_internal_details(self):
        with patch(
            "accounts.middleware.reserve_login_attempt",
            side_effect=DatabaseError("private-db-host password=secret-value"),
        ):
            for url in self.login_urls:
                with self.subTest(url=url):
                    client = Client()
                    response = self.post_login(
                        url,
                        client=client,
                        username=self.user.username,
                        password=self.password,
                    )
                    self.assertEqual(response.status_code, 503)
                    self.assertIn(
                        "no-store", response.headers.get("Cache-Control", "")
                    )
                    body = response.content.decode()
                    self.assertNotIn("private-db-host", body)
                    self.assertNotIn("secret-value", body)
                    self.assertNotIn(self.password, body)
                    self.assertNotIn(self.user.username, body)
                    self.assertRegex(body, "[А-Яа-яЁё]")
                    self.assertNotIn("_auth_user_id", client.session)

    def test_csrf_rejections_do_not_consume_attempts_but_valid_tokens_do(self):
        for index, url in enumerate(self.login_urls):
            with self.subTest(url=url):
                client = Client(enforce_csrf_checks=True)
                remote_addr = f"192.0.2.{60 + index}"
                self.assertEqual(client.get(url).status_code, 200)
                token = client.cookies["csrftoken"].value
                before = list(
                    LoginAttemptWindow.objects.order_by("key").values_list(
                        "key", "attempts", "expires_at"
                    )
                )

                for invalid_token in (None, "invalid", "a" * 32):
                    fields = (
                        {}
                        if invalid_token is None
                        else {"csrfmiddlewaretoken": invalid_token}
                    )
                    response = self.post_login(
                        url,
                        client=client,
                        remote_addr=remote_addr,
                        fields=fields,
                    )
                    self.assertEqual(response.status_code, 403)

                self.assertEqual(
                    list(
                        LoginAttemptWindow.objects.order_by("key").values_list(
                            "key", "attempts", "expires_at"
                        )
                    ),
                    before,
                )
                for _ in range(5):
                    response = self.post_login(
                        url,
                        client=client,
                        remote_addr=remote_addr,
                        fields={"csrfmiddlewaretoken": token},
                    )
                    self.assertEqual(response.status_code, 200)

                self.assert_throttled(
                    self.post_login(
                        url,
                        client=client,
                        remote_addr=remote_addr,
                        fields={"csrfmiddlewaretoken": token},
                    )
                )
