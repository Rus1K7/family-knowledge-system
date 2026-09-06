import math

from django.db import DatabaseError
from django.shortcuts import render
from django.utils.cache import add_never_cache_headers

from .login_throttle import reserve_login_attempt, reserve_password_reset_ip
from .recovery import recovery_unavailable


class LoginRateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method != "POST":
            return None
        if request.resolver_match.view_name == "family:password_reset":
            try:
                retry_after = reserve_password_reset_ip(request.META.get("REMOTE_ADDR"))
            except DatabaseError:
                return recovery_unavailable(request)
            if retry_after:
                return recovery_unavailable(request, retry_after, status=429)
            return None
        if request.resolver_match.view_name not in {
            "family:login", "admin:login",
        }:
            return None
        try:
            retry_after = reserve_login_attempt(
                request.META.get("REMOTE_ADDR"),
                request.POST.get("username", ""),
            )
        except DatabaseError:
            # An unavailable counter must not silently disable protection.
            retry_after = 60
            status = 503
        else:
            if not retry_after:
                return None
            status = 429

        response = render(
            request,
            "accounts/login_unavailable.html",
            {"temporarily_unavailable": status == 503,
             "retry_minutes": math.ceil(retry_after / 60),
             "login_path": request.path},
            status=status,
        )
        response["Retry-After"] = str(retry_after)
        add_never_cache_headers(response)
        return response
