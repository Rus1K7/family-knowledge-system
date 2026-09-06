from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from heritage.models import Biography, LifeEvent, MediaAsset
from network.models import HelpOffer
from profiles.models import Education, Employment, Skill

from .models import PrivacyPolicy


RESOURCE_TYPES = {
    Employment: PrivacyPolicy.ResourceType.EMPLOYMENT,
    Education: PrivacyPolicy.ResourceType.EDUCATION,
    Skill: PrivacyPolicy.ResourceType.SKILL,
    HelpOffer: PrivacyPolicy.ResourceType.HELP_OFFER,
    Biography: PrivacyPolicy.ResourceType.BIOGRAPHY,
    LifeEvent: PrivacyPolicy.ResourceType.LIFE_EVENT,
    MediaAsset: PrivacyPolicy.ResourceType.MEDIA_ASSET,
}


@receiver(post_save, sender=Employment)
@receiver(post_save, sender=Education)
@receiver(post_save, sender=Skill)
@receiver(post_save, sender=HelpOffer)
@receiver(post_save, sender=Biography)
@receiver(post_save, sender=LifeEvent)
@receiver(post_save, sender=MediaAsset)
def create_default_privacy_policy(sender, instance, created, **kwargs):
    if not created:
        return

    PrivacyPolicy.objects.get_or_create(
        person=instance.person,
        resource_type=RESOURCE_TYPES[sender],
        object_id=instance.id,
        defaults={
            "visibility": PrivacyPolicy.Visibility.FAMILY,
            "show_existence": True,
        },
    )


@receiver(post_delete, sender=Employment)
@receiver(post_delete, sender=Education)
@receiver(post_delete, sender=Skill)
@receiver(post_delete, sender=HelpOffer)
@receiver(post_delete, sender=Biography)
@receiver(post_delete, sender=LifeEvent)
@receiver(post_delete, sender=MediaAsset)
def delete_resource_privacy_policy(sender, instance, **kwargs):
    PrivacyPolicy.objects.filter(
        resource_type=RESOURCE_TYPES[sender],
        object_id=instance.id,
    ).delete()
