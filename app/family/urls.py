from django.urls import path

from . import views
from django.contrib.auth import views as auth_views

app_name = "family"


urlpatterns = [
    path(
        "",
        views.family_home,
        name="home",
    ),

    path(
        "person/<uuid:person_id>/",
        views.person_detail,
        name="person_detail",
    ),

    path(
        "person/<uuid:person_id>/add-relative/",
        views.add_relative,
        name="add_relative",
    ),
    path(
        "me/",
        views.my_profile,
        name="my_profile",
    ),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="family/login.html"
        ),
        name="login",
    ),

    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
]