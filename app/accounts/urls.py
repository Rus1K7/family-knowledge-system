from django.urls import path

from . import views
from . import delivery_views


app_name = "accounts"


urlpatterns = [
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
