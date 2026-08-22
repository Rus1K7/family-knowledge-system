def can_verify_heritage(user):
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return user.system_role in {
        "SYSTEM_ADMIN",
        "FAMILY_HISTORIAN",
    }