from django.contrib import admin

from .models import HelpOffer


@admin.register(HelpOffer)
class HelpOfferAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "title",
        "category",
        "is_active",
    )

    list_filter = (
        "category",
        "is_active",
    )

    search_fields = (
        "person__first_name",
        "person__last_name",
        "title",
        "description",
    )