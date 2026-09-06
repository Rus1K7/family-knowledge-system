"""Authentication request limits shared by all workers through PostgreSQL."""

import ipaddress
import json
import math
import unicodedata
from datetime import timedelta

from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import LoginAttemptWindow


WINDOW_SECONDS = 15 * 60
IP_LIMIT = 30
USERNAME_LIMIT = 5
PASSWORD_RESET_IP_LIMIT = 5
PASSWORD_RESET_EMAIL_LIMIT = 3


def _bound_lock_wait():
    # Backup snapshots temporarily block writes. Do not leave a login worker
    # waiting for the entire archive operation; the middleware returns 503.
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '2s'")


def _normalize_address(remote_addr):
    try:
        address = ipaddress.ip_address(remote_addr or "")
        if isinstance(address, ipaddress.IPv6Address):
            address = address.ipv4_mapped or address
        address = str(address)
    except ValueError:
        # Missing or malformed server metadata must not disable the limiter.
        address = "unknown"
    return address


def _digest(parts):
    return salted_hmac(
        "accounts.login_throttle.v1",
        json.dumps(parts, ensure_ascii=True),
        algorithm="sha256",
    ).hexdigest()


def _keys(remote_addr, username):
    address = _normalize_address(remote_addr)
    username = username.strip()
    # AuthenticationForm rejects names longer than 150 before authentication.
    # Avoid expensive normalization of arbitrarily long invalid input.
    if len(username) > 150:
        username = "<invalid-length>"
    else:
        username = unicodedata.normalize("NFKC", username).casefold()

    return _digest(["ip", address]), _digest(["username", address, username])


def _consume(key, limit):
    window, _ = LoginAttemptWindow.objects.select_for_update().get_or_create(
        key=key,
        defaults={"expires_at": timezone.now() + timedelta(seconds=WINDOW_SECONDS)},
    )
    # Read the clock after acquiring the row lock, including after concurrent creation.
    now = timezone.now()
    if window.expires_at <= now:
        window.attempts = 0
        window.expires_at = now + timedelta(seconds=WINDOW_SECONDS)
    retry_after = max(1, math.ceil((window.expires_at - now).total_seconds()))
    if window.attempts >= limit:
        return retry_after, window
    window.attempts += 1
    window.save(update_fields=["attempts", "expires_at"])
    return 0, window


def _prune_old_windows():
    # Bounded housekeeping after admission, outside its transaction. Locked rows
    # are skipped so cleanup cannot deadlock with concurrent login reservations.
    cutoff = timezone.now() - timedelta(days=1)
    with transaction.atomic():
        _bound_lock_wait()
        keys = list(
            LoginAttemptWindow.objects.select_for_update(skip_locked=True)
            .filter(expires_at__lte=cutoff)
            .order_by("key")
            .values_list("key", flat=True)[:100]
        )
        if keys:
            LoginAttemptWindow.objects.filter(key__in=keys).delete()


def reserve_login_attempt(remote_addr, username):
    """Return 0 if admitted, otherwise seconds to wait; never check a password.

    Every attempt consumes the address budget, even if the username budget is
    exhausted. Successful logins do not reset either budget. Never lock an
    account globally: another address retains its own budget.
    """
    ip_key, username_key = _keys(remote_addr, username)
    with transaction.atomic():
        _bound_lock_wait()
        # Always IP first, then its own (IP, username) key. Different IPs never
        # share the second row. Reject before creating a username row when the
        # IP is exhausted, preventing unlimited row creation by rotating names.
        retry_after, ip_window = _consume(ip_key, IP_LIMIT)
        if retry_after:
            return retry_after
        retry_after, _ = _consume(username_key, USERNAME_LIMIT)
        if retry_after:
            if ip_window.attempts >= IP_LIMIT:
                retry_after = max(
                    retry_after,
                    math.ceil((ip_window.expires_at - timezone.now()).total_seconds()),
                )
            return retry_after
    try:
        _prune_old_windows()
    except DatabaseError:
        # Housekeeping is not part of admission. Its own transaction has been
        # rolled back; a later admitted request will retry bounded cleanup.
        pass
    return 0


def _reserve_recovery_window(key, limit):
    with transaction.atomic():
        _bound_lock_wait()
        retry_after, _ = _consume(key, limit)
    if not retry_after:
        try:
            _prune_old_windows()
        except DatabaseError:
            pass  # Admission is committed; housekeeping can retry later.
    return retry_after


def reserve_password_reset_ip(remote_addr):
    """Cap form submissions without consuming the normal login budget."""
    key = _digest(["password-reset-ip", _normalize_address(remote_addr)])
    return _reserve_recovery_window(key, PASSWORD_RESET_IP_LIMIT)


def reserve_password_reset_email(email):
    """Cap delivery across IPs; call only after email form validation.

    Charge every valid address, including unknown/inactive accounts. A False
    result must produce the same confirmation as an ordinary accepted request.
    """
    normalized_email = unicodedata.normalize("NFKC", email.strip()).casefold()
    key = _digest(["password-reset-email", normalized_email])
    return not _reserve_recovery_window(key, PASSWORD_RESET_EMAIL_LIMIT)
