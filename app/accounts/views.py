from datetime import timedelta
import logging

from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.models import AuditEvent
from audit.services import log_audit_event
from family.models import Person, ProfileOwnership
from family.permissions import is_system_admin

from .forms import (
    InvitationAcceptForm,
    InvitationCreateForm,
)
from .models import Invitation

User = get_user_model()
logger = logging.getLogger(__name__)


def send_invitation_email(invitation, invitation_url):
    from .invitation_delivery import deliver, DeliveryBlocked
    try:
        return deliver(invitation, invitation.created_by, lambda path: invitation_url, mailer=send_mail)
    except DeliveryBlocked:
        logger.warning('Invitation delivery no longer allowed: %s', invitation.pk)


@login_required
@transaction.atomic
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

            person = get_object_or_404(
                Person.objects.select_for_update(),
                id=invitation.person_id,
            )

            already_owned = (
                ProfileOwnership.objects
                .filter(
                    person=person,
                    status=(
                        ProfileOwnership.Status.CONFIRMED
                    ),
                )
                .exists()
            )

            pending_invitation = (
                Invitation.objects
                .filter(
                    person=person,
                    status=Invitation.Status.PENDING,
                    expires_at__gt=timezone.now(),
                )
                .exists()
            )

            email_is_used = User.objects.filter(
                email__iexact=invitation.email,
            ).exists()

            if already_owned:
                form.add_error(
                    "person",
                    "У этого человека уже есть аккаунт.",
                )

            elif pending_invitation:
                form.add_error(
                    "person",
                    "Для этого человека уже создано "
                    "активное приглашение.",
                )

            elif email_is_used:
                form.add_error(
                    "email",
                    "Пользователь с таким email уже существует.",
                )

            else:
                invitation.person = person

                invitation.created_by = (
                    request.user
                )

                invitation.expires_at = (
                    timezone.now()
                    + timedelta(days=7)
                )

                invitation.save()

                log_audit_event(
                    actor=request.user,
                    action=AuditEvent.Action.CREATE_INVITATION,
                    person=invitation.person,
                    resource_type="INVITATION",
                    object_id=invitation.id,
                    details={
                        "invitation_id": str(invitation.id),
                        "email": invitation.email,
                        "expires_at": (
                            invitation.expires_at.isoformat()
                        ),
                    },
                )

                invitation_url = (
                    request.build_absolute_uri(
                        reverse(
                            "accounts:accept_invitation",
                            args=[invitation.token],
                        )
                    )
                )

                transaction.on_commit(
                    lambda: send_invitation_email(
                        invitation,
                        invitation_url,
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
            request.POST,
            email=invitation.email,
        )

        if form.is_valid():

            with transaction.atomic():

                person = get_object_or_404(
                    Person.objects.select_for_update(),
                    id=invitation.person_id,
                )

                invitation = (
                    Invitation.objects
                    .select_for_update()
                    .get(
                        id=invitation.id
                    )
                )
                invitation.person = person

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
                        person=person,
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
                if (
                    User.objects
                    .filter(
                        email__iexact=invitation.email,
                    )
                    .exists()
                ):
                    return render(
                        request,
                        "accounts/invitation_invalid.html",
                        {
                            "invitation": invitation,
                        },
                    )

                # Только теперь создаём пользователя.
                try:
                    with transaction.atomic():
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

                except IntegrityError:
                    return render(
                        request,
                        "accounts/invitation_invalid.html",
                        {
                            "invitation": invitation,
                        },
                    )

                ProfileOwnership.objects.create(
                    user=user,
                    person=person,
                    status=(
                        ProfileOwnership
                        .Status.CONFIRMED
                    ),
                    claimed_at=timezone.now(),
                    verified_at=timezone.now(),
                )

                if (
                    person.profile_status
                    != Person.ProfileStatus.CLAIMED
                ):
                    person.profile_status = (
                        Person.ProfileStatus.CLAIMED
                    )
                    person.save(
                        update_fields=[
                            "profile_status",
                        ]
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

                log_audit_event(
                    actor=user,
                    action=AuditEvent.Action.ACCEPT_INVITATION,
                    person=person,
                    resource_type="INVITATION",
                    object_id=invitation.id,
                    details={
                        "invitation_id": str(invitation.id),
                        "email": invitation.email,
                        "user_id": str(user.id),
                    },
                )

            login(
                request,
                user,
            )

            return redirect(
                "family:my_profile"
            )

    else:
        form = InvitationAcceptForm(
            email=invitation.email,
        )

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
        Invitation.objects
        .select_for_update()
        .select_related("person"),
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

        log_audit_event(
            actor=request.user,
            action=AuditEvent.Action.CANCEL_INVITATION,
            person=invitation.person,
            resource_type="INVITATION",
            object_id=invitation.id,
            details={
                "invitation_id": str(invitation.id),
                "email": invitation.email,
            },
        )

    return redirect(
        "accounts:invitation_list"
    )
