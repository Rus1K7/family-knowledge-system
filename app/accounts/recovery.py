import math

from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.db import DatabaseError, transaction
from django.shortcuts import render
from django.utils.cache import add_never_cache_headers
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from .login_throttle import _bound_lock_wait
from .models import User


def recovery_unavailable(request, retry_after=60, status=503):
    response = render(
        request,
        "accounts/password_reset_unavailable.html",
        {"temporarily_unavailable": status == 503,
         "retry_minutes": math.ceil(retry_after / 60)},
        status=status,
    )
    response["Retry-After"] = str(retry_after)
    add_never_cache_headers(response)
    response["Referrer-Policy"] = "no-referrer"
    return response


@method_decorator(never_cache, name="dispatch")
class PasswordResetRequestView(PasswordResetView):
    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except DatabaseError:
            return recovery_unavailable(self.request)


@method_decorator(
    [login_not_required, csrf_protect, sensitive_post_parameters(), never_cache],
    name="dispatch",
)
class ActivePasswordResetConfirmView(PasswordResetConfirmView):
    def dispatch(self, request, *args, **kwargs):
        try:
            if request.method == "POST":
                # The locked current user is loaded by get_user below. Keep
                # token/status checks, form validation and save in this one
                # transaction so a second submission sees the changed password.
                with transaction.atomic():
                    _bound_lock_wait()
                    response = super().dispatch(request, *args, **kwargs)
            else:
                response = super().dispatch(request, *args, **kwargs)
        except DatabaseError:
            response = recovery_unavailable(request)
        # The original email URL contains a secret and must never be referred.
        # The valid form URL contains only the public "set-password" marker.
        # HTTPS clients without Origin need a same-origin Referer for CSRF.
        response["Referrer-Policy"] = (
            "same-origin"
            if kwargs.get("token") == self.reset_url_token
            and getattr(self, "validlink", False)
            and response.status_code == 200
            else "no-referrer"
        )
        return response

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        if user is not None and self.request.method == "POST":
            # Refresh after acquiring the lock, not just lock a stale instance.
            user = User.objects.select_for_update().filter(pk=user.pk).first()
        if user is None or not (
            user.is_active
            and user.status == User.Status.ACTIVE
            and user.has_usable_password()
        ):
            return None
        return user
