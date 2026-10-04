from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache

from audit.models import AuditEvent
from audit.services import log_audit_event
from family.models import Person
from family.permissions import is_system_admin, can_invite_relatives

from .forms import (
    InvitationCreateForm,
)
from .models import Invitation

User = get_user_model()


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def create_invitation(request):
    if not can_invite_relatives(request.user):
        raise PermissionDenied
    if request.method == 'GET':
        return redirect(reverse('accounts:invitation_hub') + '?type=family&new=1')
    from django.core.exceptions import ValidationError
    from .invite_policy import create_family
    form = InvitationCreateForm(request.POST, user=request.user)
    if form.is_valid():
        try:
            invitation, created = create_family(
                request.user, form.cleaned_data['person'], form.cleaned_data['email'],
                request.build_absolute_uri)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Приглашение создано. Результат отправки показан ниже.'
                             if created else 'Открыто существующее приглашение. Повторную отправку выполняет администратор.')
            return redirect('accounts:invitation_hub_detail', kind='family', pk=invitation.pk)
    return render(request, 'accounts/create_invitation.html', {'form': form})


@never_cache
@require_http_methods(['GET', 'POST'])
def accept_invitation(request, token):
    from .family_acceptance import accept
    return accept(request, token)


@login_required
@never_cache
@require_http_methods(['GET'])
def invitation_list(request):
    return redirect(reverse('accounts:invitation_hub') + '?kind=family')


@login_required
@never_cache
@require_POST
@transaction.atomic
def cancel_invitation(
    request,
    invitation_id,
):
    actor = User.objects.select_for_update(no_key=True).get(pk=request.user.pk)
    if not can_invite_relatives(actor):
        raise PermissionDenied(
            "У вас нет доступа к управлению приглашениями."
        )

    invitations = Invitation.objects
    if not is_system_admin(actor):
        invitations = invitations.filter(created_by=actor)
    target = get_object_or_404(invitations.only('person_id'), id=invitation_id)
    Person.objects.select_for_update(no_key=True).get(pk=target.person_id)
    invitation = get_object_or_404(
        invitations.select_for_update(),
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
            actor=actor,
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
