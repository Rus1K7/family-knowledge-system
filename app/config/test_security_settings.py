import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User
from family.models import Person, ProfileOwnership


class SecuritySettingsTests(SimpleTestCase):
    def test_browser_security_defaults_are_explicit(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Lax")
        self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")

    def test_production_security_headers_are_configured(self):
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(settings.SECURE_REFERRER_POLICY, "same-origin")
        self.assertEqual(settings.SECURE_CROSS_ORIGIN_OPENER_POLICY, "same-origin")

    def test_csp_restricts_scripts_and_framing(self):
        self.assertEqual(settings.SECURE_CSP["default-src"], ["'self'"])
        self.assertIn("'self'", settings.SECURE_CSP["script-src"])
        self.assertEqual(settings.SECURE_CSP["script-src-attr"], ["'none'"])
        self.assertEqual(settings.SECURE_CSP["style-src"], ["'self'"])
        self.assertEqual(settings.SECURE_CSP["style-src-attr"], ["'none'"])
        self.assertEqual(settings.SECURE_CSP["object-src"], ["'none'"])
        self.assertEqual(settings.SECURE_CSP["frame-ancestors"], ["'none'"])

    def test_project_templates_do_not_use_inline_styles(self):
        for template in settings.BASE_DIR.rglob("*.html"):
            content = template.read_text(encoding="utf-8")
            with self.subTest(template=template.relative_to(settings.BASE_DIR)):
                self.assertNotRegex(content, r"<style\b")
                self.assertNotRegex(content, r"\sstyle\s*=")

    def test_vis_network_is_stored_locally(self):
        self.assertIsNotNone(
            find("family/vendor/vis-network-10.1.2/vis-network.min.js")
        )

    def test_vis_network_styles_are_external_and_runtime_injection_is_removed(self):
        stylesheet = find("family/vendor/vis-network-10.1.2/vis-network.css")
        self.assertIsNotNone(stylesheet)
        self.assertIn(".vis-network", Path(stylesheet).read_text(encoding="utf-8"))
        script = Path(find("family/vendor/vis-network-10.1.2/vis-network.min.js")).read_text(encoding="utf-8")
        self.assertNotIn('document.createElement("style")', script)

    def test_whitenoise_precedes_application_middleware_when_enabled(self):
        security_index = settings.MIDDLEWARE.index(
            "django.middleware.security.SecurityMiddleware"
        )
        csp_index = settings.MIDDLEWARE.index(
            "django.middleware.csp.ContentSecurityPolicyMiddleware"
        )
        whitenoise = "whitenoise.middleware.WhiteNoiseMiddleware"
        if whitenoise in settings.MIDDLEWARE:
            whitenoise_index = settings.MIDDLEWARE.index(whitenoise)
            self.assertEqual(whitenoise_index, security_index + 1)
            self.assertEqual(csp_index, whitenoise_index + 1)
        else:
            self.assertEqual(csp_index, security_index + 1)
        self.assertFalse(settings.WHITENOISE_ALLOW_ALL_ORIGINS)


class ContentSecurityPolicyResponseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="csp-member",
            email="csp-member@example.com",
            password="Csp-test-password-975!",
        )
        self.person = Person.objects.create(first_name="Безопасность")
        ProfileOwnership.objects.create(
            user=self.user,
            person=self.person,
            status=ProfileOwnership.Status.CONFIRMED,
        )
        self.client.force_login(self.user)

    def test_family_tree_uses_matching_nonce_and_local_script(self):
        response = self.client.get(reverse("family:tree"))

        self.assertEqual(response.status_code, 200)
        policy = response.headers["Content-Security-Policy"]
        match = re.search(r"script-src 'self' 'nonce-([^']+)'", policy)
        self.assertIsNotNone(match)
        self.assertContains(response, f'nonce="{match.group(1)}"')
        self.assertContains(
            response,
            "/static/family/vendor/vis-network-10.1.2/vis-network.min.js",
        )
        self.assertNotContains(response, "unpkg.com")
        self.assertContains(response, "/static/family/vendor/vis-network-10.1.2/vis-network.css")
