from django.contrib import admin

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
    list_display = (
        "person_a",
        "relationship_type",
        "person_b",
        "status",
    )