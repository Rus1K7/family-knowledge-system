from django.urls import path

from . import views


app_name = "heritage"


urlpatterns = [
    path(
        "person/<uuid:person_id>/biography/add/",
        views.add_biography,
        name="add_biography",
    ),
    path(
        "biography/<uuid:biography_id>/edit/",
        views.edit_biography,
        name="edit_biography",
    ),
    path(
        "biography/<uuid:biography_id>/delete/",
        views.delete_biography,
        name="delete_biography",
    ),

    path(
        "person/<uuid:person_id>/events/add/",
        views.add_life_event,
        name="add_life_event",
    ),
    path(
        "events/<uuid:event_id>/edit/",
        views.edit_life_event,
        name="edit_life_event",
    ),
    path(
        "events/<uuid:event_id>/delete/",
        views.delete_life_event,
        name="delete_life_event",
    ),
    path(
        "source/<str:resource_type>/<uuid:object_id>/create/",
        views.create_source_for_resource,
        name="create_source_for_resource",
    ),

    path(
        "source/<str:resource_type>/<uuid:object_id>/attach/",
        views.attach_existing_source,
        name="attach_existing_source",
    ),

    path(
        "source-link/<uuid:link_id>/detach/",
        views.detach_source,
        name="detach_source",
    ),
    path(
        "verify/<str:resource_type>/<uuid:object_id>/",
        views.verify_resource,
        name="verify_resource",
    ),
    path(
        "person/<uuid:person_id>/media/upload/",
        views.upload_media_asset,
        name="upload_media_asset",
    ),
    path(
        "media/<uuid:media_id>/file/",
        views.serve_media_asset,
        name="serve_media_asset",
    ),
    path(
        "media/moderation/",
        views.media_moderation_list,
        name="media_moderation_list",
    ),

    path(
        "media/<uuid:media_id>/approve/",
        views.approve_media_asset,
        name="approve_media_asset",
    ),

    path(
        "media/<uuid:media_id>/reject/",
        views.reject_media_asset,
        name="reject_media_asset",
    ),
]
