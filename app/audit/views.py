from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.utils.dateparse import parse_date

from family.permissions import is_system_admin

from .models import AuditEvent


@login_required
def audit_event_list(request):
    if not is_system_admin(request.user):
        raise PermissionDenied(
            "Только системный администратор может просматривать журнал действий."
        )

    events = (
        AuditEvent.objects
        .select_related(
            "actor",
            "person",
        )
        .order_by("-created_at", "-id")
    )

    action = request.GET.get("action", "").strip()
    actor = request.GET.get("actor", "").strip()
    person = request.GET.get("person", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    valid_actions = {value for value, _label in AuditEvent.Action.choices}
    if action in valid_actions:
        events = events.filter(action=action)
    else:
        action = ""

    if actor:
        events = events.filter(
            Q(actor__email__icontains=actor)
            | Q(actor__username__icontains=actor)
        )

    if person:
        events = events.filter(
            Q(person__first_name__icontains=person)
            | Q(person__middle_name__icontains=person)
            | Q(person__last_name__icontains=person)
        )

    parsed_date_from = parse_date(date_from)
    if parsed_date_from is None:
        date_from = ""
    else:
        events = events.filter(created_at__date__gte=parsed_date_from)

    parsed_date_to = parse_date(date_to)
    if parsed_date_to is None:
        date_to = ""
    else:
        events = events.filter(created_at__date__lte=parsed_date_to)

    paginator = Paginator(events, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    filter_query = request.GET.copy()
    filter_query.pop("page", None)

    return render(
        request,
        "audit/event_list.html",
        {
            "events": page_obj.object_list,
            "page_obj": page_obj,
            "actions": AuditEvent.Action.choices,
            "filter_query": filter_query.urlencode(),
            "filters": {
                "action": action,
                "actor": actor,
                "person": person,
                "date_from": date_from,
                "date_to": date_to,
            },
        },
    )
