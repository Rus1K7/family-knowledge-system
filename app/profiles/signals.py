from django.core.exceptions import ValidationError
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from audit.models import AuditEvent
from audit.services import log_audit_event
from family.models import Person
from heritage.models import Biography, LifeEvent, MediaAsset
from network.models import HelpOffer

from .models import (
    Education,
    Employment,
    ProfileChangeRequest,
    Skill,
)


RESOURCE_TYPES = {
    MediaAsset: ProfileChangeRequest.ResourceType.MEDIA_ASSET,
    Employment: ProfileChangeRequest.ResourceType.EMPLOYMENT,
    Education: ProfileChangeRequest.ResourceType.EDUCATION,
    Skill: ProfileChangeRequest.ResourceType.SKILL,
    HelpOffer: ProfileChangeRequest.ResourceType.HELP_OFFER,
    Biography: ProfileChangeRequest.ResourceType.BIOGRAPHY,
    LifeEvent: ProfileChangeRequest.ResourceType.LIFE_EVENT,
}

RESOURCE_MODELS = {
    resource_type: model
    for model, resource_type in RESOURCE_TYPES.items()
}


def get_request_person(change_request):
    if change_request.resource_type == ProfileChangeRequest.ResourceType.PERSON:
        return Person.objects.filter(pk=change_request.object_id).first()
    if (
        change_request.action
        == ProfileChangeRequest.Action.CREATE
    ):
        person_id = change_request.proposed_data.get(
            "person_id"
        )

        if not person_id:
            return None

        try:
            return Person.objects.filter(
                id=person_id,
            ).first()
        except (TypeError, ValueError, ValidationError):
            return None

    model = RESOURCE_MODELS.get(
        change_request.resource_type
    )

    if model is None or change_request.object_id is None:
        return None

    target = model.objects.filter(
        id=change_request.object_id,
    ).first()

    return target.person if target is not None else None


@receiver(
    post_save,
    sender=ProfileChangeRequest,
    dispatch_uid="profiles.audit_created_change_request",
)
def audit_created_change_request(
    sender,
    instance,
    created,
    raw=False,
    **kwargs,
):
    if (
        not created
        or raw
        or instance.status
        != ProfileChangeRequest.Status.PENDING
    ):
        return

    target_id = (
        str(instance.object_id)
        if instance.object_id is not None
        else None
    )

    log_audit_event(
        actor=instance.requested_by,
        action=AuditEvent.Action.REQUEST_CHANGE,
        person=get_request_person(instance),
        resource_type=instance.resource_type,
        object_id=instance.object_id,
        details={
            "request_id": str(instance.id),
            "change_action": instance.action,
            "target_id": target_id,
            "proposed_fields": sorted(
                field_name
                for field_name in instance.proposed_data
                if field_name != "person_id"
            ),
        },
    )


@receiver(post_delete, sender=Employment)
@receiver(post_delete, sender=Education)
@receiver(post_delete, sender=Skill)
@receiver(post_delete, sender=HelpOffer)
@receiver(post_delete, sender=Biography)
@receiver(post_delete, sender=LifeEvent)
def cancel_pending_requests_for_deleted_resource(
    sender,
    instance,
    **kwargs,
):
    ProfileChangeRequest.objects.filter(
        resource_type=RESOURCE_TYPES[sender],
        object_id=instance.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).update(
        status=ProfileChangeRequest.Status.CANCELLED,
    )
