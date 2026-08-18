from django.urls import path

from . import views


app_name = "network"


urlpatterns = [
    path(
        "person/<uuid:person_id>/help/add/",
        views.add_help_offer,
        name="add_help_offer",
    ),

    path(
        "help/<uuid:offer_id>/edit/",
        views.edit_help_offer,
        name="edit_help_offer",
    ),

    path(
        "help/<uuid:offer_id>/delete/",
        views.delete_help_offer,
        name="delete_help_offer",
    ),
]