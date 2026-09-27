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

    if user.has_perm("family.manage_family_relationships"):
        return True

    return ProfileOwnership.objects.filter(
        user=user,
        status=ProfileOwnership.Status.CONFIRMED,
    ).exists()


def can_manage_person(user, person):
    return user_owns_person(user, person)


def can_manage_relationships(user):
    return is_system_admin(user) or (has_active_account(user)
        and user.has_perm("family.manage_family_relationships"))


def can_propose_person(user, person):
    """Contribution permission does not grant ownership or access to private material."""
    return is_system_admin(user) or is_family_member(user)


def can_propose_resource(user, person, resource_type, object_id):
    if not can_propose_person(user, person):
        return False
    from privacy.permissions import can_view_resource
    return can_manage_person(user, person) or can_view_resource(user, person, resource_type, object_id)
