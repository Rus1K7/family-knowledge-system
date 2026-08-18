from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from family.models import Person
from profiles.models import ProfileChangeRequest

from .forms import HelpOfferForm
from .models import HelpOffer

from django.core.exceptions import PermissionDenied

from family.permissions import can_manage_person

@login_required
def add_help_offer(request, person_id):
    person = get_object_or_404(
        Person,
        id=person_id,
    )
    if not can_manage_person(
            request.user,
            person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    if request.method == "POST":
        form = HelpOfferForm(request.POST)

        if form.is_valid():
            ProfileChangeRequest.objects.create(
                resource_type=(
                    ProfileChangeRequest.ResourceType.HELP_OFFER
                ),
                object_id=None,
                action=ProfileChangeRequest.Action.CREATE,
                proposed_data={
                    "person_id": str(person.id),
                    "title": form.cleaned_data["title"],
                    "category": form.cleaned_data["category"],
                    "description": form.cleaned_data["description"],
                    "is_active": form.cleaned_data["is_active"],
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=person.id,
            )

    else:
        form = HelpOfferForm()

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": person,
            "title": "Предложить помощь",
        },
    )


@login_required
def edit_help_offer(request, offer_id):
    offer = get_object_or_404(
        HelpOffer,
        id=offer_id,
    )
    if not can_manage_person(
            request.user,
            offer.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    pending_request = ProfileChangeRequest.objects.filter(
        resource_type=ProfileChangeRequest.ResourceType.HELP_OFFER,
        object_id=offer.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).first()

    if pending_request:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": offer.person,
                "change_request": pending_request,
            },
        )

    if request.method == "POST":
        form = HelpOfferForm(
            request.POST,
            instance=offer,
        )

        if form.is_valid():
            ProfileChangeRequest.objects.create(
                resource_type=(
                    ProfileChangeRequest.ResourceType.HELP_OFFER
                ),
                object_id=offer.id,
                action=ProfileChangeRequest.Action.EDIT,
                proposed_data={
                    "title": form.cleaned_data["title"],
                    "category": form.cleaned_data["category"],
                    "description": form.cleaned_data["description"],
                    "is_active": form.cleaned_data["is_active"],
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=offer.person.id,
            )

    else:
        form = HelpOfferForm(
            instance=offer,
        )

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": offer.person,
            "title": "Предложить изменение",
        },
    )


@login_required
def delete_help_offer(request, offer_id):
    offer = get_object_or_404(
        HelpOffer,
        id=offer_id,
    )
    if not can_manage_person(
            request.user,
            offer.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    pending_request = ProfileChangeRequest.objects.filter(
        resource_type=ProfileChangeRequest.ResourceType.HELP_OFFER,
        object_id=offer.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).first()

    if pending_request:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": offer.person,
                "change_request": pending_request,
            },
        )

    if request.method == "POST":
        ProfileChangeRequest.objects.create(
            resource_type=(
                ProfileChangeRequest.ResourceType.HELP_OFFER
            ),
            object_id=offer.id,
            action=ProfileChangeRequest.Action.DELETE,
            requested_by=request.user,
        )

        return redirect(
            "family:person_detail",
            person_id=offer.person.id,
        )

    return render(
        request,
        "profiles/confirm_delete.html",
        {
            "person": offer.person,
            "object": offer,
            "title": "Запросить удаление предложения помощи",
        },
    )