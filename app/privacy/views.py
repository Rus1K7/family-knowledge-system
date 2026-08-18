from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from family.permissions import can_manage_person
from network.models import HelpOffer
from profiles.models import Education, Employment, Skill
from heritage.models import Biography, LifeEvent
from .forms import PrivacyPolicyForm
from .models import PrivacyPolicy

from django.contrib.auth.decorators import login_required

RESOURCE_MODELS = {
    PrivacyPolicy.ResourceType.EMPLOYMENT: Employment,
    PrivacyPolicy.ResourceType.EDUCATION: Education,
    PrivacyPolicy.ResourceType.SKILL: Skill,
    PrivacyPolicy.ResourceType.HELP_OFFER: HelpOffer,

    PrivacyPolicy.ResourceType.BIOGRAPHY: Biography,
    PrivacyPolicy.ResourceType.LIFE_EVENT: LifeEvent,
}


from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from family.models import ProfileOwnership

from family.permissions import (
    can_manage_person,
    is_system_admin,
)

from .forms import (
    AccessRequestForm,
    PrivacyPolicyForm,
    SelectedUserGrantForm,
)

from .models import (
    AccessGrant,
    AccessRequest,
    PrivacyPolicy,
)

from django.db import models


def get_resource(resource_type, object_id):
    model = RESOURCE_MODELS.get(resource_type)

    if model is None:
        raise PermissionDenied(
            "Неизвестный тип данных."
        )

    return get_object_or_404(
        model,
        id=object_id,
    )

@login_required
def edit_privacy(request, resource_type, object_id):
    resource = get_resource(
        resource_type,
        object_id,
    )

    person = resource.person

    if not can_manage_person(
        request.user,
        person,
    ):
        raise PermissionDenied(
            "Вы не можете менять приватность этого профиля."
        )

    policy, created = PrivacyPolicy.objects.get_or_create(
        person=person,
        resource_type=resource_type,
        object_id=resource.id,
        defaults={
            "visibility":
                PrivacyPolicy.Visibility.FAMILY,
            "show_existence": True,
        },
    )

    if request.method == "POST":
        form = PrivacyPolicyForm(
            request.POST,
            instance=policy,
        )

        if form.is_valid():
            form.save()

            return redirect(
                "family:person_detail",
                person_id=person.id,
            )

    else:
        form = PrivacyPolicyForm(
            instance=policy,
        )

    return render(
        request,
        "privacy/edit_privacy.html",
        {
            "form": form,
            "person": person,
            "resource": resource,
            "policy": policy,
        },
    )

@login_required
def request_access(request, policy_id):
    policy = get_object_or_404(
        PrivacyPolicy.objects.select_related("person"),
        id=policy_id,
    )

    if (
        policy.visibility
        != PrivacyPolicy.Visibility.REQUEST_ONLY
    ):
        raise PermissionDenied(
            "Для этой информации нельзя запросить доступ."
        )

    if can_manage_person(
        request.user,
        policy.person,
    ):
        return redirect(
            "family:person_detail",
            person_id=policy.person.id,
        )

    active_grant = AccessGrant.objects.filter(
        policy=policy,
        grantee=request.user,
        action=AccessGrant.Action.VIEW,
        revoked_at__isnull=True,
    ).filter(
        models.Q(valid_until__isnull=True)
        | models.Q(valid_until__gt=timezone.now())
    ).exists()

    if active_grant:
        return redirect(
            "family:person_detail",
            person_id=policy.person.id,
        )

    if request.method == "POST":
        form = AccessRequestForm(
            request.POST
        )

        if form.is_valid():
            AccessRequest.objects.get_or_create(
                policy=policy,
                requester=request.user,
                status=AccessRequest.Status.PENDING,
                defaults={
                    "reason":
                        form.cleaned_data["reason"],
                },
            )

            return redirect(
                "family:person_detail",
                person_id=policy.person.id,
            )

    else:
        form = AccessRequestForm()

    return render(
        request,
        "privacy/request_access.html",
        {
            "form": form,
            "policy": policy,
            "person": policy.person,
        },
    )
def get_resource_or_none(
    resource_type,
    object_id,
):
    model = RESOURCE_MODELS.get(resource_type)

    if model is None:
        return None

    return model.objects.filter(
        id=object_id,
    ).first()

@login_required
def access_request_list(request):
    access_requests = (
        AccessRequest.objects
        .filter(
            status=AccessRequest.Status.PENDING,
        )
        .select_related(
            "policy",
            "policy__person",
            "requester",
        )
        .order_by("-created_at")
    )

    # Администратор MVP видит все запросы.
    if not is_system_admin(request.user):

        ownership = (
            ProfileOwnership.objects
            .filter(
                user=request.user,
                status=ProfileOwnership.Status.CONFIRMED,
            )
            .select_related("person")
            .first()
        )

        if ownership is None:
            access_requests = access_requests.none()

        else:
            access_requests = access_requests.filter(
                policy__person=ownership.person,
            )

    items = []

    for access_request in access_requests:

        resource = get_resource_or_none(
            access_request.policy.resource_type,
            access_request.policy.object_id,
        )

        items.append(
            {
                "request": access_request,
                "resource": resource,
            }
        )

    return render(
        request,
        "privacy/access_request_list.html",
        {
            "items": items,
        },
    )

@login_required
@require_POST
@transaction.atomic
def approve_access_request(
    request,
    request_id,
    duration,
):
    access_request = get_object_or_404(
        AccessRequest.objects
        .select_for_update()
        .select_related(
            "policy",
            "policy__person",
            "requester",
        ),
        id=request_id,
    )

    if (
        access_request.status
        != AccessRequest.Status.PENDING
    ):
        raise PermissionDenied(
            "Этот запрос уже рассмотрен."
        )

    if not can_manage_person(
        request.user,
        access_request.policy.person,
    ):
        raise PermissionDenied(
            "Вы не можете рассматривать этот запрос."
        )

    now = timezone.now()

    if duration == "24h":
        valid_until = now + timedelta(hours=24)

    elif duration == "7d":
        valid_until = now + timedelta(days=7)

    elif duration == "forever":
        valid_until = None

    else:
        raise PermissionDenied(
            "Неизвестный срок доступа."
        )

    grant = (
        AccessGrant.objects
        .filter(
            policy=access_request.policy,
            grantee=access_request.requester,
            action=AccessGrant.Action.VIEW,
            revoked_at__isnull=True,
        )
        .first()
    )

    if grant is None:
        AccessGrant.objects.create(
            policy=access_request.policy,
            grantee=access_request.requester,
            action=AccessGrant.Action.VIEW,
            valid_until=valid_until,
        )

    else:
        grant.valid_until = valid_until

        grant.save(
            update_fields=[
                "valid_until",
            ]
        )

    access_request.status = (
        AccessRequest.Status.APPROVED
    )

    access_request.reviewed_by = request.user
    access_request.reviewed_at = now

    access_request.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
        ]
    )

    return redirect(
        "privacy:access_request_list",
    )

@login_required
@require_POST
@transaction.atomic
def reject_access_request(
    request,
    request_id,
):
    access_request = get_object_or_404(
        AccessRequest.objects
        .select_for_update()
        .select_related(
            "policy",
            "policy__person",
        ),
        id=request_id,
    )

    if (
        access_request.status
        != AccessRequest.Status.PENDING
    ):
        raise PermissionDenied(
            "Этот запрос уже рассмотрен."
        )

    if not can_manage_person(
        request.user,
        access_request.policy.person,
    ):
        raise PermissionDenied(
            "Вы не можете рассматривать этот запрос."
        )

    access_request.status = (
        AccessRequest.Status.REJECTED
    )

    access_request.reviewed_by = request.user
    access_request.reviewed_at = timezone.now()

    access_request.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
        ]
    )

    return redirect(
        "privacy:access_request_list",
    )

@login_required
def manage_access(request, policy_id):
    policy = get_object_or_404(
        PrivacyPolicy.objects.select_related(
            "person"
        ),
        id=policy_id,
    )

    if not can_manage_person(
        request.user,
        policy.person,
    ):
        raise PermissionDenied(
            "Вы не можете управлять доступом к этой информации."
        )

    grants = (
        AccessGrant.objects
        .filter(
            policy=policy,
            revoked_at__isnull=True,
        )
        .select_related("grantee")
        .order_by("-created_at")
    )

    form = SelectedUserGrantForm(
        current_user=request.user,
    )

    return render(
        request,
        "privacy/manage_access.html",
        {
            "policy": policy,
            "person": policy.person,
            "grants": grants,
            "form": form,
        },
    )

@login_required
@require_POST
@transaction.atomic
def grant_selected_user(request, policy_id):
    policy = get_object_or_404(
        PrivacyPolicy.objects
        .select_for_update()
        .select_related("person"),
        id=policy_id,
    )

    if not can_manage_person(
        request.user,
        policy.person,
    ):
        raise PermissionDenied(
            "Вы не можете управлять доступом к этой информации."
        )

    if (
        policy.visibility
        != PrivacyPolicy.Visibility.SELECTED_USERS
    ):
        raise PermissionDenied(
            "Выбранных пользователей можно добавлять "
            "только для режима «Выбранные пользователи»."
        )

    form = SelectedUserGrantForm(
        request.POST,
        current_user=request.user,
    )

    if form.is_valid():
        grantee = form.cleaned_data["user"]

        grant = (
            AccessGrant.objects
            .filter(
                policy=policy,
                grantee=grantee,
                action=AccessGrant.Action.VIEW,
                revoked_at__isnull=True,
            )
            .first()
        )

        if grant is None:
            AccessGrant.objects.create(
                policy=policy,
                grantee=grantee,
                action=AccessGrant.Action.VIEW,
                valid_until=None,
            )

        else:
            # Например, существовал истёкший
            # временный доступ.
            grant.valid_until = None

            grant.save(
                update_fields=[
                    "valid_until",
                ]
            )

    return redirect(
        "privacy:manage_access",
        policy_id=policy.id,
    )

@login_required
@require_POST
@transaction.atomic
def revoke_access_grant(request, grant_id):
    grant = get_object_or_404(
        AccessGrant.objects
        .select_for_update()
        .select_related(
            "policy",
            "policy__person",
        ),
        id=grant_id,
    )

    if not can_manage_person(
        request.user,
        grant.policy.person,
    ):
        raise PermissionDenied(
            "Вы не можете отзывать этот доступ."
        )

    if grant.revoked_at is None:
        grant.revoked_at = timezone.now()

        grant.save(
            update_fields=[
                "revoked_at",
            ]
        )

    return redirect(
        "privacy:manage_access",
        policy_id=grant.policy.id,
    )