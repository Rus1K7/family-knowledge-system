from django.urls import path, include

from . import views
from . import delivery_views
from . import assisted_views
from . import hub_views, family_acceptance


app_name = "accounts"


legacy_patterns = [
    path('access/requests/', assisted_views.access_requests, name='access_requests'),
    path('access/request/', assisted_views.access_request_create, name='access_request_create'),
    path('access/requests/<uuid:pk>/cancel/', assisted_views.access_request_cancel, name='access_request_cancel'),
    path('access/manage/', assisted_views.assisted_manage, name='assisted_manage'),
    path('access/create/', assisted_views.assisted_create, name='assisted_create'),
    path('access/requests/<uuid:pk>/reject/', assisted_views.assisted_reject, name='assisted_reject'),
    path('access/accounts/<uuid:pk>/reissue/', assisted_views.assisted_reissue, name='assisted_reissue'),
    path('access/accounts/<uuid:pk>/show/', assisted_views.assisted_show, name='assisted_show'),
    path('invitations/delivery/', delivery_views.delivery_list, name='delivery_list'),
    path('invitations/delivery/<str:kind>/<uuid:pk>/', delivery_views.delivery_detail, name='delivery_detail'),
    path(
        "invite/create/",
        views.create_invitation,
        name="create_invitation",
    ),

    path(
        "invite/<uuid:token>/",
        views.accept_invitation,
        name="accept_invitation",
    ),
    path(
        "invitations/",
        views.invitation_list,
        name="invitation_list",
    ),

    path(
        "invitations/<uuid:invitation_id>/cancel/",
        views.cancel_invitation,
        name="cancel_invitation",
    ),
]

urlpatterns = [
    path('invitations/', hub_views.hub, name='invitation_hub'),
    path('invitations/<str:kind>/<uuid:pk>/', hub_views.detail, name='invitation_hub_detail'),
    path('invitations/verify/<str:verification>/', family_acceptance.verify_invitation,
         name='verify_family_invitation'),
    path('family/', include(legacy_patterns)),
]
