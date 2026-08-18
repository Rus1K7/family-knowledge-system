from django.urls import path

from . import views


app_name = "profiles"


urlpatterns = [
    path(
        "person/<uuid:person_id>/employment/add/",
        views.add_employment,
        name="add_employment",
    ),

    path(
        "person/<uuid:person_id>/education/add/",
        views.add_education,
        name="add_education",
    ),

    path(
        "person/<uuid:person_id>/skill/add/",
        views.add_skill,
        name="add_skill",
        ),
    path(
        "employment/<uuid:employment_id>/edit/",
        views.edit_employment,
        name="edit_employment",
    ),

    path(
        "employment/<uuid:employment_id>/delete/",
        views.delete_employment,
        name="delete_employment",
    ),

    path(
        "education/<uuid:education_id>/edit/",
        views.edit_education,
        name="edit_education",
    ),

    path(
        "education/<uuid:education_id>/delete/",
        views.delete_education,
        name="delete_education",
    ),

    path(
        "skill/<uuid:skill_id>/edit/",
        views.edit_skill,
        name="edit_skill",
    ),

    path(
        "skill/<uuid:skill_id>/delete/",
        views.delete_skill,
        name="delete_skill",
    ),
path(
    "changes/",
    views.change_request_list,
    name="change_request_list",
),

path(
    "changes/<uuid:request_id>/approve/",
    views.approve_change_request,
    name="approve_change_request",
),

path(
    "changes/<uuid:request_id>/reject/",
    views.reject_change_request,
    name="reject_change_request",
),
]