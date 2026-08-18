from datetime import timedelta

from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone

from family.models import ProfileOwnership
from family.permissions import is_system_admin

from .forms import (
    InvitationAcceptForm,
    InvitationCreateForm,
)
from .models import Invitation

from django.urls import reverse
from django.views.decorators.http import require_POST

User = get_user_model()

@login_required
def create_invitation(request):
    if not is_system_admin(
        request.user
    ):
        raise PermissionDenied

    if request.method == "POST":
        form = InvitationCreateForm(
            request.POST
        )

        if form.is_valid():
            invitation = form.save(
                commit=False
            )

            invitation.created_by = (
                request.user
            )

            invitation.expires_at = (
                timezone.now()
                + timedelta(days=7)
            )

            invitation.save()

            invitation_url = (
                request.build_absolute_uri(
                    f"/family/invite/"
                    f"{invitation.token}/"
                )
            )

            return render(
                request,
                "accounts/invitation_created.html",
                {
                    "invitation":
                        invitation,
                    "invitation_url":
                        invitation_url,
                },
            )

    else:
        form = InvitationCreateForm()

    return render(
        request,
        "accounts/create_invitation.html",
        {
            "form": form,
        },
    )

def accept_invitation(
    request,
    token,
):
    invitation = get_object_or_404(
        Invitation.objects.select_related(
            "person"
        ),
        token=token,
    )

    if not invitation.is_valid():
        return render(
            request,
            "accounts/invitation_invalid.html",
            {
                "invitation":
                    invitation,
            },
        )

    if request.method == "POST":
        form = InvitationAcceptForm(
            request.POST
        )

        if form.is_valid():

            with transaction.atomic():

                invitation = (
                    Invitation.objects
                    .select_for_update()
                    .select_related("person")
                    .get(
                        id=invitation.id
                    )
                )

                if not invitation.is_valid():
                    return render(
                        request,
                        "accounts/invitation_invalid.html",
                        {
                            "invitation": invitation,
                        },
                    )

                # Проверяем, не появился ли уже аккаунт
                # у этого Person после создания приглашения.
                already_owned = (
                    ProfileOwnership.objects
                    .filter(
                        person=invitation.person,
                        status=ProfileOwnership.Status.CONFIRMED,
                    )
                    .exists()
                )

                if already_owned:
                    return render(
                        request,
                        "accounts/invitation_invalid.html",
                        {
                            "invitation": invitation,
                        },
                    )

                # Проверяем, не зарегистрирован ли уже
                # пользователь с этим email.
                if User.objects.filter(
                        email=invitation.email
                ).exists():
                    return render(
                        request,
                        "accounts/invitation_invalid.html",
                        {
                            "invitation": invitation,
                        },
                    )

                # Только теперь создаём пользователя.
                user = User.objects.create_user(
                    username=form.cleaned_data[
                        "username"
                    ],
                    email=invitation.email,
                    password=form.cleaned_data[
                        "password1"
                    ],
                    status=User.Status.ACTIVE,
                    system_role=(
                        User.SystemRole.FAMILY_MEMBER
                    ),
                )

                ProfileOwnership.objects.create(
                    user=user,
                    person=invitation.person,
                    status=(
                        ProfileOwnership
                        .Status.CONFIRMED
                    ),
                    claimed_at=timezone.now(),
                    verified_at=timezone.now(),
                )

                invitation.status = (
                    Invitation.Status.ACCEPTED
                )

                invitation.accepted_at = (
                    timezone.now()
                )

                invitation.save(
                    update_fields=[
                        "status",
                        "accepted_at",
                    ]
                )

            login(
                request,
                user,
            )

            return redirect(
                "family:my_profile"
            )

    else:
        form = InvitationAcceptForm()

    return render(
        request,
        "accounts/accept_invitation.html",
        {
            "form": form,
            "invitation": invitation,
        },
    )

@login_required
def invitation_list(request):
    if not is_system_admin(request.user):
        raise PermissionDenied(
            "У вас нет доступа к управлению приглашениями."
        )

    invitations = (
        Invitation.objects
        .select_related(
            "person",
            "created_by",
        )
        .order_by("-created_at")
    )

    now = timezone.now()
    items = []

    for invitation in invitations:
        is_active = (
            invitation.status
            == Invitation.Status.PENDING
            and invitation.expires_at > now
        )

        if invitation.status == Invitation.Status.ACCEPTED:
            display_status = "Принято"

        elif invitation.status == Invitation.Status.CANCELLED:
            display_status = "Отменено"

        elif invitation.expires_at <= now:
            display_status = "Истекло"

        else:
            display_status = "Активно"

        invitation_url = None

        if is_active:
            invitation_url = request.build_absolute_uri(
                reverse(
                    "accounts:accept_invitation",
                    kwargs={
                        "token": invitation.token,
                    },
                )
            )

        items.append(
            {
                "invitation": invitation,
                "display_status": display_status,
                "is_active": is_active,
                "invitation_url": invitation_url,
            }
        )

    return render(
        request,
        "accounts/invitation_list.html",
        {
            "items": items,
        },
    )

@login_required
@require_POST
@transaction.atomic
def cancel_invitation(
    request,
    invitation_id,
):
    if not is_system_admin(request.user):
        raise PermissionDenied(
            "У вас нет доступа к управлению приглашениями."
        )

    invitation = get_object_or_404(
        Invitation.objects.select_for_update(),
        id=invitation_id,
    )

    if (
        invitation.status
        == Invitation.Status.PENDING
    ):
        invitation.status = (
            Invitation.Status.CANCELLED
        )

        invitation.save(
            update_fields=[
                "status",
            ]
        )

    return redirect(
        "accounts:invitation_list"
    )