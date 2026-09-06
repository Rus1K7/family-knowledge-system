from django.contrib import admin
from django.db import transaction

from audit.models import AuditEvent
from audit.services import log_audit_event
from .forms import RelationshipAdminForm
from .permissions import is_system_admin
from .relationships import lock_relationship_graph

from .models import Person, ProfileOwnership, Relationship


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = (
        "first_name",
        "last_name",
        "birth_date",
        "is_living",
        "profile_status",
    )


@admin.register(ProfileOwnership)
class ProfileOwnershipAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "user",
        "status",
    )


@admin.register(Relationship)
class RelationshipAdmin(admin.ModelAdmin):
    form = RelationshipAdminForm
    readonly_fields = ("created_by", "created_at")

    def has_add_permission(self, request):
        return is_system_admin(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request.user) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return is_system_admin(request.user) and super().has_delete_permission(request, obj)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST":
            with transaction.atomic():
                lock_relationship_graph()
                return super().changeform_view(request, object_id, form_url, extra_context)
        return super().changeform_view(request, object_id, form_url, extra_context)

    @staticmethod
    def snapshot(obj):
        return {
            "person_a_id": str(obj.person_a_id),
            "person_b_id": str(obj.person_b_id),
            "relationship_type": obj.relationship_type,
            "status": obj.status,
        }

    def save_model(self, request, obj, form, change):
        old = self.snapshot(Relationship.objects.get(pk=obj.pk)) if change else None
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        new = self.snapshot(obj)
        if old == new:
            return
        log_audit_event(
            actor=request.user,
            action=AuditEvent.Action.UPDATE_RELATIONSHIP if change else AuditEvent.Action.CREATE_RELATIONSHIP,
            person=obj.person_a, resource_type="RELATIONSHIP", object_id=obj.pk,
            details={"old": old, "new": new} if change else new,
        )

    def delete_model(self, request, obj):
        with transaction.atomic():
            lock_relationship_graph()
            log_audit_event(
                actor=request.user, action=AuditEvent.Action.DELETE_RELATIONSHIP,
                person=obj.person_a, resource_type="RELATIONSHIP", object_id=obj.pk,
                details=self.snapshot(obj),
            )
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            lock_relationship_graph()
            for obj in queryset:
                self.delete_model(request, obj)

    list_display = (
        "person_a",
        "relationship_type",
        "person_b",
        "status",
    )
