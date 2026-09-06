from .models import ProfileOwnership


def has_active_account(user):
    if not user.is_authenticated:
        return False

    return (
        user.is_active
        and getattr(user, "status", None) == "ACTIVE"
    )


def is_system_admin(user):
    if not has_active_account(user):
        return False

    return (
        user.is_superuser
        or user.system_role == "SYSTEM_ADMIN"
    )


def user_owns_person(user, person):
    if not has_active_account(user):
        return False

    if is_system_admin(user):
        return True

    return ProfileOwnership.objects.filter(
        user=user,
        person=person,
        status=ProfileOwnership.Status.CONFIRMED,
    ).exists()


def is_family_member(user):
    if not has_active_account(user):
        return False

    return ProfileOwnership.objects.filter(
        user=user,
        status=ProfileOwnership.Status.CONFIRMED,
    ).exists()


def can_manage_person(user, person):
    return user_owns_person(user, person)
