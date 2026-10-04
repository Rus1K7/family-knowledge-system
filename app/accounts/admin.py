from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, AccountAccessRequest, AssistedAccount


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
                    "can_invite_friends",
                    "disabled_at",
                )
            },
        ),
    )


class AssistedReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    def has_view_permission(self, request, obj=None):
        from family.permissions import is_system_admin
        return is_system_admin(request.user) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AccountAccessRequest)
class AccountAccessRequestAdmin(AssistedReadOnlyAdmin):
    list_display = ('id', 'requester', 'status', 'created_at', 'reviewed_at')
    list_filter = ('status',)


@admin.register(AssistedAccount)
class AssistedAccountAdmin(AssistedReadOnlyAdmin):
    list_display = ('user', 'issued_by', 'issued_at')
    fields = ('user', 'issued_by', 'issued_at')
