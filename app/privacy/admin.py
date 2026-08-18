from django.contrib import admin

from .models import (
    AccessGrant,
    AccessRequest,
    PrivacyPolicy,
)


@admin.register(PrivacyPolicy)
class PrivacyPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "resource_type",
        "visibility",
        "show_existence",
    )

    list_filter = (
        "resource_type",
        "visibility",
    )


@admin.register(AccessGrant)
class AccessGrantAdmin(admin.ModelAdmin):
    list_display = (
        "policy",
        "grantee",
        "action",
        "valid_until",
        "revoked_at",
    )


@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display = (
        "policy",
        "requester",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
    )