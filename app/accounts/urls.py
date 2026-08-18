from django.urls import path

from . import views


app_name = "accounts"


urlpatterns = [
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