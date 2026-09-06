from django.db import connections, router, transaction

from .models import ProfileChangeRequest


def _lock_change_request_table(using):
    """Serialize pending-request creation across all resource types.

    A request can point to different models (or to a person in ``proposed_data``
    for CREATE), so there is no single row that can be locked for every scope.
    The short table lock keeps the duplicate check and INSERT atomic even when
    two submissions arrive at the same time.
    """
    connection = connections[using]
    if connection.vendor != "postgresql":
        return

    with connection.cursor() as cursor:
        cursor.execute(
            'LOCK TABLE "profiles_profilechangerequest" '
            "IN SHARE ROW EXCLUSIVE MODE"
        )


def submit_change_request(
    *,
    resource_type,
    object_id=None,
    action,
    requested_by,
    proposed_data=None,
    status=ProfileChangeRequest.Status.PENDING,
    comment="",
):
    """Create a change request unless an equivalent pending request exists.

    The returned tuple is ``(request, created)``.  CREATE requests are scoped
    by ``person_id`` in ``proposed_data``; EDIT/DELETE requests are scoped by
    ``resource_type`` and ``object_id``.  Callers can therefore safely redirect
    to the same page for a repeated submission without creating a second row.
    """
    proposed_data = proposed_data or {}
    using = router.db_for_write(ProfileChangeRequest)

    with transaction.atomic(using=using):
        if status == ProfileChangeRequest.Status.PENDING:
            _lock_change_request_table(using)
            pending = ProfileChangeRequest.objects.using(using).filter(
                resource_type=resource_type,
                status=ProfileChangeRequest.Status.PENDING,
            )

            if object_id is None:
                person_id = proposed_data.get("person_id")
                if person_id:
                    pending = pending.filter(
                        object_id__isnull=True,
                        proposed_data__person_id=str(person_id),
                    )
                else:
                    pending = pending.none()
            else:
                pending = pending.filter(object_id=object_id)

            existing = pending.order_by("requested_at").first()
            if existing is not None:
                return existing, False

        request = ProfileChangeRequest(
            resource_type=resource_type,
            object_id=object_id,
            action=action,
            proposed_data=proposed_data,
            requested_by=requested_by,
            status=status,
            comment=comment,
        )
        request.save(using=using)
        return request, True
