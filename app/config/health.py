from django.db import DatabaseError, connections
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@require_safe
@never_cache
def health(request):
    """Readiness through the HTTP worker, without account or family data."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            ready = cursor.fetchone() == (1,)
    except (DatabaseError, OSError):
        ready = False
    return JsonResponse(
        {"status": "ok" if ready else "unavailable"},
        status=200 if ready else 503,
    )
