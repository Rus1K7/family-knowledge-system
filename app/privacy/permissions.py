from django.utils import timezone

from django.db import models
from django.utils import timezone

from family.permissions import (
    is_system_admin,
    user_owns_person,
)

from .models import AccessGrant, PrivacyPolicy

from family.permissions import (
    is_system_admin,
    user_owns_person,
)

from .models import AccessGrant, PrivacyPolicy


def get_policy(resource_type, object_id):
    return (
        PrivacyPolicy.objects
        .filter(
            resource_type=resource_type,
            object_id=object_id,
        )
        .first()
    )


def has_active_grant(user, policy):
    if not user.is_authenticated:
        return False

    now = timezone.now()

    return (
        AccessGrant.objects
        .filter(
            policy=policy,
            grantee=user,
            action=AccessGrant.Action.VIEW,
            revoked_at__isnull=True,
        )
        .filter(
            models.Q(valid_until__isnull=True)
            | models.Q(valid_until__gt=now)
        )
        .exists()
    )
def can_view_resource(
    user,
    person,
    resource_type,
    object_id,
):
    # Администратор MVP видит всё.
    if is_system_admin(user):
        return True

    # Владелец профиля всегда видит свои данные.
    if user_owns_person(user, person):
        return True

    if not user.is_authenticated:
        return False

    policy = get_policy(
        resource_type,
        object_id,
    )

    # Если политика ещё не задана,
    # для MVP считаем запись доступной семье.
    if policy is None:
        return True

    if (
        policy.visibility
        == PrivacyPolicy.Visibility.FAMILY
    ):
        return True

    if policy.visibility in {
        PrivacyPolicy.Visibility.SELECTED_USERS,
        PrivacyPolicy.Visibility.REQUEST_ONLY,
    }:
        return has_active_grant(
            user,
            policy,
        )

    if policy.visibility in {
        PrivacyPolicy.Visibility.OWNER_ONLY,
        PrivacyPolicy.Visibility.PRIVATE,
    }:
        return False

    return False


def can_see_resource_existence(
    user,
    person,
    resource_type,
    object_id,
):
    if can_view_resource(
        user,
        person,
        resource_type,
        object_id,
    ):
        return True

    policy = get_policy(
        resource_type,
        object_id,
    )

    if policy is None:
        return False

    return policy.show_existence