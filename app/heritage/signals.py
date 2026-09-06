import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import (
    Biography,
    LifeEvent,
    MediaAsset,
    SourceLink,
    Verification,
)


logger = logging.getLogger(__name__)


RESOURCE_TYPES = {
    Biography: SourceLink.ResourceType.BIOGRAPHY,
    LifeEvent: SourceLink.ResourceType.LIFE_EVENT,
}


@receiver(post_delete, sender=Biography)
@receiver(post_delete, sender=LifeEvent)
def delete_historical_resource_metadata(sender, instance, **kwargs):
    resource_type = RESOURCE_TYPES[sender]

    SourceLink.objects.filter(
        resource_type=resource_type,
        object_id=instance.id,
    ).delete()

    Verification.objects.filter(
        resource_type=resource_type,
        object_id=instance.id,
    ).delete()


@receiver(post_delete, sender=MediaAsset)
def delete_media_file(sender, instance, using, **kwargs):
    file_name = getattr(instance.file, "name", "")
    if not file_name:
        return

    # Database deletion can still roll back, including a cascaded Person delete.
    # Capture values now: Django clears the instance's primary key after delete().
    storage = instance.file.storage
    media_id = instance.pk

    def delete_after_commit():
        try:
            storage.delete(file_name)
        except Exception:
            logger.exception(
                "Не удалось удалить файл медиа-объекта: media_id=%s",
                media_id,
            )

    transaction.on_commit(delete_after_commit, using=using)
