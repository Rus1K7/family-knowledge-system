from django.urls import path

from . import views
from . import relative_requests
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from accounts.forms import ActivePasswordResetForm
from accounts.recovery import ActivePasswordResetConfirmView, PasswordResetRequestView

app_name = "family"


urlpatterns = [
    path("requests/", views.requests_home, name="requests"),
    path("person/<uuid:person_id>/propose-relative/", relative_requests.propose_relative, name="propose_relative"),
    path("relatives/proposals/", relative_requests.relative_proposals, name="relative_proposals"),
    path("relatives/proposals/<uuid:proposal_id>/", relative_requests.relative_proposal, name="relative_proposal"),
    path("tree/", views.family_tree, name="tree"),
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
        "password-reset/",
        PasswordResetRequestView.as_view(
            template_name="accounts/password_reset_form.html",
            form_class=ActivePasswordResetForm,
            email_template_name="accounts/password_reset_email.txt",
            subject_template_name="accounts/password_reset_subject.txt",
            success_url=reverse_lazy("family:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        ActivePasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("family:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),

    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
]
