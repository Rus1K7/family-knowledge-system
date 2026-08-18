from django.contrib import admin

from .models import (
    Biography,
    LifeEvent,
    Source,
    SourceLink,
)

@admin.register(Biography)
class BiographyAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "created_by",
        "updated_at",
    )

    search_fields = (
        "person__first_name",
        "person__last_name",
        "text",
    )


@admin.register(LifeEvent)
class LifeEventAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "title",
        "event_type",
        "start_date",
        "place",
    )

    list_filter = (
        "event_type",
        "date_precision",
    )

    search_fields = (
        "title",
        "description",
        "place",
        "person__first_name",
        "person__last_name",
    )

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "source_type",
        "author",
        "source_date",
        "created_by",
    )

    list_filter = (
        "source_type",
    )

    search_fields = (
        "title",
        "author",
        "citation",
        "notes",
    )


@admin.register(SourceLink)
class SourceLinkAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "resource_type",
        "relation_type",
        "object_id",
        "created_by",
    )

    list_filter = (
        "resource_type",
        "relation_type",
    )