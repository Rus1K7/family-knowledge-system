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
from privacy.models import PrivacyPolicy

from django.http import FileResponse, Http404

from .forms import (
    BiographyForm,
    ExistingSourceLinkForm,
    LifeEventForm,
    SourceCreateForm,
    VerificationForm,
    MediaAssetUploadForm,
)

from .models import (
    Biography,
    LifeEvent,
    SourceLink,
    Verification,
    MediaAsset,
)

from django.utils import timezone
from .permissions import can_verify_heritage

from django.db import transaction
from django.views.decorators.http import require_POST

from family.permissions import (
    can_manage_person,
    is_system_admin,
)
from privacy.permissions import can_view_resource

from audit.models import AuditEvent
from audit.services import log_audit_event

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

            log_audit_event(
                actor=request.user,
                action=AuditEvent.Action.VERIFY_HERITAGE,
                person=resource.person,
                resource_type=resource_type,
                object_id=resource.id,
            )

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

@login_required
@transaction.atomic
def upload_media_asset(request, person_id):
    person = get_object_or_404(
        Person,
        id=person_id,
    )

    if not can_manage_person(
        request.user,
        person,
    ):
        raise PermissionDenied(
            "У вас нет права добавлять файлы этому человеку."
        )

    if request.method == "POST":
        form = MediaAssetUploadForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():
            media_asset = form.save(
                commit=False
            )

            media_asset.person = person
            media_asset.uploaded_by = (
                request.user
            )

            uploaded_file = (
                form.cleaned_data["file"]
            )

            media_asset.original_filename = (
                uploaded_file.name
            )

            media_asset.mime_type = (
                getattr(
                    uploaded_file,
                    "content_type",
                    "",
                )
            )

            media_asset.file_size = (
                uploaded_file.size
            )

            media_asset.status = (
                MediaAsset.Status.PENDING
            )

            media_asset.save()

            PrivacyPolicy.objects.get_or_create(
                person=person,
                resource_type=(
                    PrivacyPolicy.ResourceType.MEDIA_ASSET
                ),
                object_id=media_asset.id,
                defaults={
                    "visibility":
                        PrivacyPolicy.Visibility.FAMILY,
                    "show_existence": True,
                },
            )

            return redirect(
                "family:person_detail",
                person_id=person.id,
            )

    else:
        form = MediaAssetUploadForm()

    return render(
        request,
        "heritage/media_upload_form.html",
        {
            "form": form,
            "person": person,
        },
    )

@login_required
def serve_media_asset(request, media_id):
    media_asset = get_object_or_404(
        MediaAsset.objects.select_related(
            "person"
        ),
        id=media_id,
    )

    person = media_asset.person

    can_manage = can_manage_person(
        request.user,
        person,
    )

    if (
        media_asset.status
        != MediaAsset.Status.APPROVED
        and not can_manage
        and not is_system_admin(request.user)
    ):
        raise Http404

    if not can_manage and not is_system_admin(
        request.user
    ):
        can_view = can_view_resource(
            request.user,
            person,
            PrivacyPolicy.ResourceType.MEDIA_ASSET,
            media_asset.id,
        )

        if not can_view:
            raise Http404

    if not media_asset.file:
        raise Http404

    storage = media_asset.file.storage

    if not storage.exists(
        media_asset.file.name
    ):
        raise Http404

    file_handle = storage.open(
        media_asset.file.name,
        "rb",
    )

    log_audit_event(
        actor=request.user,
        action=AuditEvent.Action.VIEW_MEDIA,
        person=person,
        resource_type="MEDIA_ASSET",
        object_id=media_asset.id,
    )

    as_attachment = (
        media_asset.media_type
        == MediaAsset.MediaType.DOCUMENT
    )

    return FileResponse(
        file_handle,
        as_attachment=as_attachment,
        filename=(
            media_asset.original_filename
            or media_asset.file.name
        ),
        content_type=(
            media_asset.mime_type
            or "application/octet-stream"
        ),
    )

@login_required
def media_moderation_list(request):
    if not is_system_admin(request.user):
        raise PermissionDenied(
            "Только системный администратор может проверять файлы."
        )

    pending_media = (
        MediaAsset.objects
        .filter(
            status=MediaAsset.Status.PENDING
        )
        .select_related(
            "person",
            "uploaded_by",
        )
        .order_by("created_at")
    )

    return render(
        request,
        "heritage/media_moderation_list.html",
        {
            "pending_media": pending_media,
        },
    )


@login_required
@require_POST
@transaction.atomic
def approve_media_asset(request, media_id):
    if not is_system_admin(request.user):
        raise PermissionDenied(
            "Только системный администратор может проверять файлы."
        )

    media_asset = get_object_or_404(
        MediaAsset.objects.select_for_update(),
        id=media_id,
    )

    if media_asset.status == MediaAsset.Status.PENDING:
        media_asset.status = (
            MediaAsset.Status.APPROVED
        )

        media_asset.reviewed_by = (
            request.user
        )

        media_asset.reviewed_at = (
            timezone.now()
        )

        media_asset.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            ]
        )

        log_audit_event(
            actor=request.user,
            action=AuditEvent.Action.APPROVE_MEDIA,
            person=media_asset.person,
            resource_type="MEDIA_ASSET",
            object_id=media_asset.id,
        )

    return redirect(
        "heritage:media_moderation_list"
    )


@login_required
@require_POST
@transaction.atomic
def reject_media_asset(request, media_id):
    if not is_system_admin(request.user):
        raise PermissionDenied(
            "Только системный администратор может проверять файлы."
        )

    media_asset = get_object_or_404(
        MediaAsset.objects.select_for_update(),
        id=media_id,
    )

    if media_asset.status == MediaAsset.Status.PENDING:
        media_asset.status = (
            MediaAsset.Status.REJECTED
        )

        media_asset.reviewed_by = (
            request.user
        )

        media_asset.reviewed_at = (
            timezone.now()
        )

        media_asset.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            ]
        )

        log_audit_event(
            actor=request.user,
            action=AuditEvent.Action.REJECT_MEDIA,
            person=media_asset.person,
            resource_type="MEDIA_ASSET",
            object_id=media_asset.id,
        )

    return redirect(
        "heritage:media_moderation_list"
    )