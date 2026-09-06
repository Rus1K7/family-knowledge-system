from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import User


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class PasswordResetTests(TestCase):
    old_password = "Old-password-for-reset-927!"
    new_password = "New-password-for-reset-384!"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="reset-relative",
            email="Reset.Relative@Example.COM",
            password=cls.old_password,
            status=User.Status.ACTIVE,
        )

    def test_form_and_success_page_do_not_disclose_account_existence(self):
        url = reverse("family:password_reset")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Восстановление пароля")

        for address in ("reset.relative@example.com", "not-registered@example.com"):
            with self.subTest(address=address):
                self.assertRedirects(
                    self.client.post(url, {"email": address}),
                    reverse("family:password_reset_done"),
                )
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(self.user.email, mail.outbox[0].body)

    def test_reset_email_contains_one_time_link_without_password_or_private_data(self):
        self.client.post(
            reverse("family:password_reset"),
            {"email": self.user.email.lower()},
        )
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.user.email])
        self.assertIn("/family/password-reset/", message.body)
        self.assertNotIn(self.old_password, message.body)
        self.assertNotIn(self.new_password, message.body)
        self.assertNotIn("Reset.Relative", message.body)

    def test_valid_link_changes_password_and_is_invalidated_after_use(self):
        self.client.post(
            reverse("family:password_reset"),
            {"email": self.user.email},
        )
        link = mail.outbox[0].body.splitlines()[-3]
        confirm_url = link.split("testserver", 1)[1]
        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 302)
        confirm_url = response["Location"]
        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Создайте новый пароль")
        response = self.client.post(
            confirm_url,
            {"new_password1": self.new_password, "new_password2": self.new_password},
        )
        self.assertRedirects(response, reverse("family:password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertFalse(self.user.check_password(self.old_password))
        response = self.client.get(confirm_url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "недействительна")

    def test_non_active_user_does_not_receive_reset_email(self):
        self.user.status = User.Status.SUSPENDED
        self.user.save(update_fields=["status"])
        self.client.post(
            reverse("family:password_reset"),
            {"email": self.user.email},
        )
        self.assertEqual(mail.outbox, [])

    def test_csrf_is_required_for_reset_request(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse("family:password_reset")
        self.assertEqual(client.get(url).status_code, 200)
        response = client.post(url, {"email": self.user.email})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(mail.outbox, [])
