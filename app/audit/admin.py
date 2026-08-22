from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "actor",
        "action",
        "person",
        "resource_type",
        "object_id",
    )

    list_filter = (
        "action",
        "created_at",
    )

    search_fields = (
        "actor__username",
        "actor__email",
        "person__first_name",
        "person__last_name",
    )

    readonly_fields = (
        "id",
        "actor",
        "action",
        "person",
        "resource_type",
        "object_id",
        "created_at",
    )

    ordering = (
        "-created_at",
    )

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        return False