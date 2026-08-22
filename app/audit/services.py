from .models import AuditEvent


def log_audit_event(
    *,
    actor,
    action,
    person=None,
    resource_type="",
    object_id=None,
):
    if actor is not None and not actor.is_authenticated:
        actor = None

    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        person=person,
        resource_type=resource_type,
        object_id=object_id,
    )