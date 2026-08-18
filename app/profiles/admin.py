from django.contrib import admin

from .models import Education, Employment, Skill


@admin.register(Employment)
class EmploymentAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "organization",
        "position",
        "is_current",
    )

    list_filter = (
        "is_current",
    )

    search_fields = (
        "person__first_name",
        "person__last_name",
        "organization",
        "position",
    )


@admin.register(Education)
class EducationAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "institution",
        "degree",
        "field_of_study",
    )

    search_fields = (
        "person__first_name",
        "person__last_name",
        "institution",
        "field_of_study",
    )


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "name",
    )

    search_fields = (
        "person__first_name",
        "person__last_name",
        "name",
    )