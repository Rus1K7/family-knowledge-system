from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


class HealthcheckCommandTests(SimpleTestCase):
    @override_settings(ALLOWED_HOSTS=["family.example.com"], SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
    def test_command_is_registered_and_checks_local_http_server(self):
        output = StringIO()
        with patch("config.management.commands.healthcheck.http.client.HTTPConnection") as factory:
            client = factory.return_value
            client.getresponse.return_value.status = 200
            client.getresponse.return_value.read.return_value = b'{"status": "ok"}'
            call_command("healthcheck", stdout=output)
            factory.assert_called_once_with("127.0.0.1", 8000, timeout=3)
            client.request.assert_called_once_with("GET", "/health/", headers={
                "Host": "family.example.com", "X-Forwarded-Proto": "https",
            })
            client.close.assert_called_once()
        self.assertEqual(output.getvalue().strip(), "ok")

    def test_stopped_or_unresponsive_server_fails_without_exposing_details(self):
        for error in (ConnectionRefusedError("private host"), TimeoutError("private host")):
            with self.subTest(error=type(error).__name__):
                with patch("config.management.commands.healthcheck.http.client.HTTPConnection") as factory:
                    factory.return_value.request.side_effect = error
                    with self.assertRaisesMessage(CommandError, "Приложение или база данных недоступны"):
                        call_command("healthcheck")
                    factory.return_value.close.assert_called_once()

    def test_redirect_database_failure_and_unexpected_body_fail_the_probe(self):
        for status, body in ((301, b""), (503, b'{"status":"unavailable"}'), (200, b"not json"), (200, b'{"status":"unavailable"}')):
            with self.subTest(status=status, body=body):
                with patch("config.management.commands.healthcheck.http.client.HTTPConnection") as factory:
                    factory.return_value.getresponse.return_value.status = status
                    factory.return_value.getresponse.return_value.read.return_value = body
                    with self.assertRaises(CommandError):
                        call_command("healthcheck")


class HealthEndpointTests(TestCase):
    def test_anonymous_request_checks_real_database_without_exposing_data(self):
        with self.assertNumQueries(1):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("sessionid", response.cookies)

    def test_database_failure_returns_only_generic_status(self):
        with patch("config.health.connections") as connections:
            connections["default"].cursor.side_effect = DatabaseError("private connection details")
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertNotContains(response, "private connection details", status_code=503)
        self.assertIn("no-store", response["Cache-Control"])

    def test_post_is_rejected_without_database_queries(self):
        with self.assertNumQueries(0):
            response = self.client.post(reverse("health"))
        self.assertEqual(response.status_code, 405)

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
    def test_probe_works_behind_https_proxy_and_plain_http_still_redirects(self):
        self.assertEqual(self.client.get(reverse("health")).status_code, 301)
        response = self.client.get(reverse("health"), HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code, 200)
