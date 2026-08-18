from django.urls import path

from . import views


app_name = "privacy"


urlpatterns = [
    path(
        "<str:resource_type>/<uuid:object_id>/",
        views.edit_privacy,
        name="edit_privacy",
    ),
    path(
        "request/<uuid:policy_id>/",
        views.request_access,
        name="request_access",
    ),
    path(
        "requests/",
        views.access_request_list,
        name="access_request_list",
    ),

    path(
        "requests/<uuid:request_id>/approve/<str:duration>/",
        views.approve_access_request,
        name="approve_access_request",
    ),

    path(
        "requests/<uuid:request_id>/reject/",
        views.reject_access_request,
        name="reject_access_request",
    ),
    path(
        "<uuid:policy_id>/access/",
        views.manage_access,
        name="manage_access",
    ),

    path(
        "<uuid:policy_id>/access/grant/",
        views.grant_selected_user,
        name="grant_selected_user",
    ),

    path(
        "access/grant/<uuid:grant_id>/revoke/",
        views.revoke_access_grant,
        name="revoke_access_grant",
    ),
]