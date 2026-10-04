from django.urls import path

from . import views
from .visibility_views import choose_visibility
from . import visibility_access as presence


app_name = "privacy"


urlpatterns = [
    path('visibility/choice/', choose_visibility, name='choose_visibility'),
    path('visibility/', presence.dashboard, name='visibility_dashboard'),
    path('visibility/link/create/', presence.create_link, name='visibility_create_link'),
    path('visibility/exception/', presence.set_exception, name='visibility_set_exception'),
    path('visibility/link/<uuid:token>/', presence.link_detail, name='visibility_link'),
    path('visibility/link/<uuid:token>/decide/', presence.decide_link, name='visibility_decide_link'),
    path('visibility/exception/<int:pk>/', presence.exception_decision, name='visibility_exception'),
    path('visibility/hide/<uuid:person_id>/', presence.request_hide, name='request_person_hide'),
    path('visibility/hide-requests/', presence.hide_requests, name='hide_requests'),
    path('visibility/hide-requests/<uuid:pk>/', presence.review_hide, name='review_person_hide'),
    path('visibility/restore/<uuid:person_id>/', presence.restore_visibility, name='restore_person_visibility'),
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
    path(
        "<str:resource_type>/<uuid:object_id>/",
        views.edit_privacy,
        name="edit_privacy",
    ),
]
