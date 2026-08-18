from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class FamilyUserAdmin(UserAdmin):
    list_display = (
        "username",
        "email",
        "system_role",
        "status",
        "is_staff",
        "is_active",
    )

    list_filter = (
        "system_role",
        "status",
        "is_staff",
        "is_active",
    )

    fieldsets = UserAdmin.fieldsets + (
        (
            "Family Knowledge System",
            {
                "fields": (
                    "status",
                    "system_role",
                    "mfa_enabled",
                    "disabled_at",
                )
            },
        ),
    )