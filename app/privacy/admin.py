from django.contrib import admin

from .models import (
    AccessGrant,
    AccessRequest,
    PrivacyPolicy,
)
from .models import PersonVisibility, PersonVisibilityException, PersonHideRequest, VisibilityLink


class PresenceReadOnlyAdmin(admin.ModelAdmin):
    """Use audited workflow screens for changes, never bypass owner decisions here."""
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PersonVisibility)
class PersonVisibilityAdmin(PresenceReadOnlyAdmin):
    list_display = ('person', 'choice', 'forced_hidden', 'chosen_at')
    list_filter = ('choice', 'forced_hidden')


@admin.register(PersonVisibilityException)
class PersonVisibilityExceptionAdmin(PresenceReadOnlyAdmin):
    list_display = ('person', 'viewer', 'decision', 'granted_by')


@admin.register(PersonHideRequest)
class PersonHideRequestAdmin(PresenceReadOnlyAdmin):
    list_display = ('person', 'status', 'created_at', 'reviewer')
    list_filter = ('status',)


@admin.register(VisibilityLink)
class VisibilityLinkAdmin(PresenceReadOnlyAdmin):
    list_display = ('kind', 'creator', 'status', 'expires_at')
    list_filter = ('kind', 'status')


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
