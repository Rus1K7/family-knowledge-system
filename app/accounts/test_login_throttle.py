from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.db import DatabaseError, OperationalError, close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from .login_throttle import _keys, _prune_old_windows, reserve_login_attempt
from .models import LoginAttemptWindow


class LoginThrottleTests(TestCase):
    address = "192.0.2.12"

    def test_five_attempts_then_fixed_pause_without_extension(self):
        now = timezone.now()
        with patch("accounts.login_throttle.timezone.now", return_value=now):
            for _ in range(5):
                self.assertEqual(reserve_login_attempt(self.address, "member"), 0)
            self.assertEqual(reserve_login_attempt(self.address, "member"), 900)
        with patch("accounts.login_throttle.timezone.now", return_value=now + timedelta(seconds=121)):
            self.assertEqual(reserve_login_attempt(self.address, "member"), 779)
        self.assertEqual(
            set(LoginAttemptWindow.objects.values_list("expires_at", flat=True)),
            {now + timedelta(seconds=900)},
        )
        with patch("accounts.login_throttle.timezone.now", return_value=now + timedelta(seconds=900)):
            self.assertEqual(reserve_login_attempt(self.address, "member"), 0)
        self.assertEqual(list(LoginAttemptWindow.objects.values_list("attempts", flat=True)), [1, 1])

    def test_ip_budget_caps_username_rotation_and_row_growth(self):
        for number in range(30):
            self.assertEqual(reserve_login_attempt(self.address, f"member-{number}"), 0)
        self.assertEqual(LoginAttemptWindow.objects.count(), 31)
        for number in range(30, 60):
            self.assertGreater(reserve_login_attempt(self.address, f"member-{number}"), 0)
        self.assertEqual(LoginAttemptWindow.objects.count(), 31)
        ip_key, _ = _keys(self.address, "")
        self.assertEqual(LoginAttemptWindow.objects.get(pk=ip_key).attempts, 30)

    def test_blocked_username_also_consumes_ip_budget(self):
        for _ in range(30):
            reserve_login_attempt(self.address, "member")
        self.assertGreater(reserve_login_attempt(self.address, "different"), 0)
        self.assertEqual(LoginAttemptWindow.objects.count(), 2)

    def test_no_global_account_lockout(self):
        for _ in range(5):
            reserve_login_attempt(self.address, "member")
        self.assertEqual(reserve_login_attempt("192.0.2.13", "member"), 0)
        self.assertEqual(reserve_login_attempt(self.address, "different"), 0)

    def test_keys_are_normalized_separated_and_secret_keyed(self):
        self.assertEqual(_keys("::ffff:192.0.2.12", " Ｍｅｍｂｅｒ "), _keys(self.address, "member"))
        self.assertEqual(_keys("2001:db8::1", "member"), _keys("2001:0db8:0:0:0:0:0:1", "member"))
        self.assertEqual(_keys(None, "member"), _keys("invalid", "member"))
        self.assertEqual(_keys(self.address, "x" * 151), _keys(self.address, "y" * 10000))
        keys = _keys(self.address, "member")
        self.assertNotEqual(*keys)
        for key in keys:
            self.assertRegex(key, r"^[0-9a-f]{64}$")
        with self.settings(SECRET_KEY="different-test-secret"):
            self.assertNotEqual(keys, _keys(self.address, "member"))

    def test_cleanup_is_bounded_and_preserves_recent_windows(self):
        now = timezone.now()
        old_expiry = now - timedelta(days=2)
        LoginAttemptWindow.objects.bulk_create([
            LoginAttemptWindow(key=f"{number:064x}", expires_at=old_expiry)
            for number in range(105)
        ])
        active = LoginAttemptWindow.objects.create(key="a" * 64, expires_at=now + timedelta(minutes=15))
        recent = LoginAttemptWindow.objects.create(key="b" * 64, expires_at=now - timedelta(minutes=15))
        _prune_old_windows()
        self.assertEqual(LoginAttemptWindow.objects.filter(expires_at=old_expiry).count(), 5)
        self.assertTrue(LoginAttemptWindow.objects.filter(pk=active.pk).exists())
        self.assertTrue(LoginAttemptWindow.objects.filter(pk=recent.pk).exists())
        reserve_login_attempt(self.address, "member")
        self.assertFalse(LoginAttemptWindow.objects.filter(expires_at=old_expiry).exists())

    @patch("accounts.login_throttle._prune_old_windows", side_effect=DatabaseError("cleanup unavailable"))
    def test_cleanup_failure_does_not_cancel_admitted_login(self, cleanup):
        self.assertEqual(reserve_login_attempt(self.address, "member"), 0)
        self.assertEqual(LoginAttemptWindow.objects.count(), 2)
        cleanup.assert_called_once()


@skipUnlessDBFeature("has_select_for_update")
class ConcurrentLoginThrottleTests(TransactionTestCase):
    def reserve_concurrently(self, usernames):
        barrier = Barrier(len(usernames))

        def attempt(username):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return reserve_login_attempt("192.0.2.90", username)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(usernames)) as executor:
            return list(executor.map(attempt, usernames))

    def test_parallel_first_attempts_cannot_exceed_username_limit(self):
        results = self.reserve_concurrently(["member"] * 8)
        self.assertEqual(results.count(0), 5)
        self.assertEqual(LoginAttemptWindow.objects.count(), 2)

    def test_parallel_different_users_cannot_exceed_ip_limit(self):
        with patch("accounts.login_throttle.IP_LIMIT", 4):
            results = self.reserve_concurrently([f"member-{number}" for number in range(8)])
        self.assertEqual(results.count(0), 4)
        self.assertEqual(LoginAttemptWindow.objects.count(), 5)

    def test_parallel_expired_window_is_reset_once(self):
        for _ in range(5):
            reserve_login_attempt("192.0.2.90", "member")
        LoginAttemptWindow.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        results = self.reserve_concurrently(["member"] * 8)
        self.assertEqual(results.count(0), 5)

    def test_backup_write_lock_times_out_instead_of_hanging_login(self):
        def attempt():
            close_old_connections()
            try:
                return reserve_login_attempt("192.0.2.91", "member")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("LOCK TABLE accounts_loginattemptwindow IN SHARE MODE")
                future = executor.submit(attempt)
                with self.assertRaises(OperationalError):
                    future.result(timeout=5)
        self.assertFalse(LoginAttemptWindow.objects.exists())

    @skipUnlessDBFeature("has_select_for_update_skip_locked")
    def test_cleanup_skips_locked_rows_and_keeps_refreshed_window(self):
        window = LoginAttemptWindow.objects.create(
            key="c" * 64, expires_at=timezone.now() - timedelta(days=2),
        )

        def cleanup():
            close_old_connections()
            try:
                _prune_old_windows()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                locked = LoginAttemptWindow.objects.select_for_update().get(pk=window.pk)
                executor.submit(cleanup).result(timeout=5)
                locked.expires_at = timezone.now() + timedelta(minutes=15)
                locked.save(update_fields=["expires_at"])
        _prune_old_windows()
        self.assertTrue(LoginAttemptWindow.objects.filter(pk=window.pk).exists())
