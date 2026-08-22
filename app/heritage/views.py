from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from family.models import Person
from family.permissions import can_manage_person
from profiles.models import ProfileChangeRequest

from .forms import (
    BiographyForm,
    ExistingSourceLinkForm,
    LifeEventForm,
    SourceCreateForm,
    VerificationForm,
)

from .models import (
    Biography,
    LifeEvent,
    SourceLink,
    Verification,
)

from django.utils import timezone
from .permissions import can_verify_heritage

from django.db import transaction
from django.views.decorators.http import require_POST

HERITAGE_RESOURCE_MODELS = {
    SourceLink.ResourceType.BIOGRAPHY: Biography,
    SourceLink.ResourceType.LIFE_EVENT: LifeEvent,
}


def get_heritage_resource(
    resource_type,
    object_id,
):
    model = HERITAGE_RESOURCE_MODELS.get(
        resource_type
    )

    if model is None:
        raise PermissionDenied(
            "Неизвестный тип объекта."
        )

    return get_object_or_404(
        model,
        id=object_id,
    )

def serialize_date(value):
    if value is None:
        return None

    return value.isoformat()


@login_required
def add_biography(request, person_id):
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

    if Biography.objects.filter(
        person=person
    ).exists():
        biography = Biography.objects.get(
            person=person
        )

        return redirect(
            "heritage:edit_biography",
            biography_id=biography.id,
        )

    pending = ProfileChangeRequest.objects.filter(
        resource_type=(
            ProfileChangeRequest.ResourceType.BIOGRAPHY
        ),
        action=ProfileChangeRequest.Action.CREATE,
        status=ProfileChangeRequest.Status.PENDING,
        proposed_data__person_id=str(person.id),
    ).first()

    if pending:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": person,
                "change_request": pending,
            },
        )

    if request.method == "POST":
        form = BiographyForm(
            request.POST
        )

        if form.is_valid():
            ProfileChangeRequest.objects.create(
                resource_type=(
                    ProfileChangeRequest.ResourceType.BIOGRAPHY
                ),
                object_id=None,
                action=ProfileChangeRequest.Action.CREATE,
                proposed_data={
                    "person_id": str(person.id),
                    "text": form.cleaned_data["text"],
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=person.id,
            )

    else:
        form = BiographyForm()

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": person,
            "title": "Предложить биографию",
        },
    )

@login_required
def edit_biography(request, biography_id):
    biography = get_object_or_404(
        Biography,
        id=biography_id,
    )

    if not can_manage_person(
        request.user,
        biography.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    pending = ProfileChangeRequest.objects.filter(
        resource_type=(
            ProfileChangeRequest.ResourceType.BIOGRAPHY
        ),
        object_id=biography.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).first()

    if pending:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": biography.person,
                "change_request": pending,
            },
        )

    if request.method == "POST":
        form = BiographyForm(
            request.POST,
            instance=biography,
        )

        if form.is_valid():
            ProfileChangeRequest.objects.create(
                resource_type=(
                    ProfileChangeRequest.ResourceType.BIOGRAPHY
                ),
                object_id=biography.id,
                action=ProfileChangeRequest.Action.EDIT,
                proposed_data={
                    "text": form.cleaned_data["text"],
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=biography.person.id,
            )

    else:
        form = BiographyForm(
            instance=biography
        )

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": biography.person,
            "title": "Предложить изменение биографии",
        },
    )

@login_required
def delete_biography(request, biography_id):
    biography = get_object_or_404(
        Biography,
        id=biography_id,
    )

    if not can_manage_person(
        request.user,
        biography.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    if request.method == "POST":
        ProfileChangeRequest.objects.get_or_create(
            resource_type=(
                ProfileChangeRequest.ResourceType.BIOGRAPHY
            ),
            object_id=biography.id,
            action=ProfileChangeRequest.Action.DELETE,
            status=ProfileChangeRequest.Status.PENDING,
            defaults={
                "requested_by": request.user,
            },
        )

        return redirect(
            "family:person_detail",
            person_id=biography.person.id,
        )

    return render(
        request,
        "profiles/confirm_delete.html",
        {
            "person": biography.person,
            "object": biography,
            "title": "Запросить удаление биографии",
        },
    )

@login_required
def add_life_event(request, person_id):
    person = get_object_or_404(
        Person,
        id=person_id,
    )

    if not can_manage_person(
        request.user,
        person,
    ):
        raise PermissionDenied

    if request.method == "POST":
        form = LifeEventForm(
            request.POST
        )

        if form.is_valid():
            ProfileChangeRequest.objects.create(
                resource_type=(
                    ProfileChangeRequest.ResourceType.LIFE_EVENT
                ),
                object_id=None,
                action=ProfileChangeRequest.Action.CREATE,
                proposed_data={
                    "person_id": str(person.id),
                    "event_type":
                        form.cleaned_data["event_type"],
                    "title":
                        form.cleaned_data["title"],
                    "start_date": serialize_date(
                        form.cleaned_data["start_date"]
                    ),
                    "end_date": serialize_date(
                        form.cleaned_data["end_date"]
                    ),
                    "date_precision":
                        form.cleaned_data["date_precision"],
                    "place":
                        form.cleaned_data["place"],
                    "description":
                        form.cleaned_data["description"],
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=person.id,
            )

    else:
        form = LifeEventForm()

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": person,
            "title": "Предложить событие жизни",
        },
    )

@login_required
def edit_life_event(request, event_id):
    event = get_object_or_404(
        LifeEvent,
        id=event_id,
    )

    if not can_manage_person(
        request.user,
        event.person,
    ):
        raise PermissionDenied

    pending = ProfileChangeRequest.objects.filter(
        resource_type=(
            ProfileChangeRequest.ResourceType.LIFE_EVENT
        ),
        object_id=event.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).first()

    if pending:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": event.person,
                "change_request": pending,
            },
        )

    if request.method == "POST":
        form = LifeEventForm(
            request.POST,
            instance=event,
        )

        if form.is_valid():
            ProfileChangeRequest.objects.create(
                resource_type=(
                    ProfileChangeRequest.ResourceType.LIFE_EVENT
                ),
                object_id=event.id,
                action=ProfileChangeRequest.Action.EDIT,
                proposed_data={
                    "event_type":
                        form.cleaned_data["event_type"],
                    "title":
                        form.cleaned_data["title"],
                    "start_date": serialize_date(
                        form.cleaned_data["start_date"]
                    ),
                    "end_date": serialize_date(
                        form.cleaned_data["end_date"]
                    ),
                    "date_precision":
                        form.cleaned_data["date_precision"],
                    "place":
                        form.cleaned_data["place"],
                    "description":
                        form.cleaned_data["description"],
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=event.person.id,
            )

    else:
        form = LifeEventForm(
            instance=event
        )

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": event.person,
            "title": "Предложить изменение события",
        },
    )

@login_required
def delete_life_event(request, event_id):
    event = get_object_or_404(
        LifeEvent,
        id=event_id,
    )

    if not can_manage_person(
        request.user,
        event.person,
    ):
        raise PermissionDenied

    if request.method == "POST":
        ProfileChangeRequest.objects.get_or_create(
            resource_type=(
                ProfileChangeRequest.ResourceType.LIFE_EVENT
            ),
            object_id=event.id,
            action=ProfileChangeRequest.Action.DELETE,
            status=ProfileChangeRequest.Status.PENDING,
            defaults={
                "requested_by": request.user,
            },
        )

        return redirect(
            "family:person_detail",
            person_id=event.person.id,
        )

    return render(
        request,
        "profiles/confirm_delete.html",
        {
            "person": event.person,
            "object": event,
            "title": "Запросить удаление события",
        },
    )

@login_required
@transaction.atomic
def create_source_for_resource(
    request,
    resource_type,
    object_id,
):
    resource = get_heritage_resource(
        resource_type,
        object_id,
    )

    if not can_manage_person(
        request.user,
        resource.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    if request.method == "POST":
        form = SourceCreateForm(
            request.POST
        )

        if form.is_valid():
            source = form.save(
                commit=False
            )

            source.created_by = request.user
            source.save()

            SourceLink.objects.create(
                source=source,
                resource_type=resource_type,
                object_id=resource.id,
                relation_type=form.cleaned_data[
                    "relation_type"
                ],
                note=form.cleaned_data[
                    "link_note"
                ],
                created_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=resource.person.id,
            )

    else:
        form = SourceCreateForm()

    return render(
        request,
        "heritage/source_form.html",
        {
            "form": form,
            "resource": resource,
            "person": resource.person,
            "title": "Добавить новый источник",
        },
    )

@login_required
@transaction.atomic
def attach_existing_source(
    request,
    resource_type,
    object_id,
):
    resource = get_heritage_resource(
        resource_type,
        object_id,
    )

    if not can_manage_person(
        request.user,
        resource.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    if request.method == "POST":
        form = ExistingSourceLinkForm(
            request.POST
        )

        if form.is_valid():
            source = form.cleaned_data[
                "source"
            ]

            SourceLink.objects.update_or_create(
                source=source,
                resource_type=resource_type,
                object_id=resource.id,
                defaults={
                    "relation_type":
                        form.cleaned_data[
                            "relation_type"
                        ],
                    "note":
                        form.cleaned_data[
                            "note"
                        ],
                    "created_by":
                        request.user,
                },
            )

            return redirect(
                "family:person_detail",
                person_id=resource.person.id,
            )

    else:
        form = ExistingSourceLinkForm()

    return render(
        request,
        "heritage/source_form.html",
        {
            "form": form,
            "resource": resource,
            "person": resource.person,
            "title":
                "Привязать существующий источник",
        },
    )

@login_required
@require_POST
@transaction.atomic
def detach_source(
    request,
    link_id,
):
    link = get_object_or_404(
        SourceLink.objects.select_for_update(),
        id=link_id,
    )

    resource = get_heritage_resource(
        link.resource_type,
        link.object_id,
    )

    if not can_manage_person(
        request.user,
        resource.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    person_id = resource.person.id

    link.delete()

    return redirect(
        "family:person_detail",
        person_id=person_id,
    )

@login_required
@transaction.atomic
def verify_resource(
    request,
    resource_type,
    object_id,
):
    resource = get_heritage_resource(
        resource_type,
        object_id,
    )

    if not can_verify_heritage(
        request.user
    ):
        raise PermissionDenied(
            "У вас нет права проверять исторические данные."
        )

    verification, created = (
        Verification.objects.get_or_create(
            resource_type=resource_type,
            object_id=resource.id,
            defaults={
                "status":
                    Verification.Status.PENDING,
            },
        )
    )

    if request.method == "POST":
        form = VerificationForm(
            request.POST,
            instance=verification,
        )

        if form.is_valid():
            verification = form.save(
                commit=False
            )

            verification.reviewed_by = (
                request.user
            )

            verification.reviewed_at = (
                timezone.now()
            )

            verification.save()

            return redirect(
                "family:person_detail",
                person_id=resource.person.id,
            )

    else:
        form = VerificationForm(
            instance=verification
        )

    return render(
        request,
        "heritage/verification_form.html",
        {
            "form": form,
            "resource": resource,
            "person": resource.person,
            "verification": verification,
        },
    )