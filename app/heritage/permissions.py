from family.permissions import can_manage_person, has_active_account, can_manage_relationships
from privacy.permissions import can_view_resource

from .models import MediaAsset


def available_source_documents(user, person):
    if user is None or person is None or not can_manage_person(user, person):
        return MediaAsset.objects.none()

    return MediaAsset.objects.filter(
        person=person,
        media_type=MediaAsset.MediaType.DOCUMENT,
        status=MediaAsset.Status.APPROVED,
    ).exclude(file="")


def can_view_media(user, media_asset):
    from privacy.person_visibility import can_view_person
    if not can_view_person(user, media_asset.person):
        return False
    if media_asset.status == MediaAsset.Status.ARCHIVED:
        return False

    if has_active_account(user) and media_asset.status == MediaAsset.Status.PENDING and (
        media_asset.uploaded_by_id == user.pk or can_manage_relationships(user)
    ):
        return True

    if can_manage_person(user, media_asset.person):
        return True

    return (
        media_asset.status == MediaAsset.Status.APPROVED
        and can_view_resource(
            user, media_asset.person, "MEDIA_ASSET", media_asset.id,
        )
    )


def prepare_source_documents(user, links):
    for link in links:
        document = link.source.document
        link.can_open_document = bool(
            document is not None
            and document.file
            and can_view_media(user, document)
        )
    return links


def can_verify_heritage(user):
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return user.system_role in {
        "SYSTEM_ADMIN",
        "FAMILY_HISTORIAN",
    }
