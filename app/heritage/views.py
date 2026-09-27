from django.contrib import messages
from family.permissions import can_propose_person, can_propose_resource, can_manage_relationships
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from audit.models import AuditEvent
from audit.services import log_audit_event
from family.models import Person
from family.permissions import can_manage_person, is_system_admin
from profiles.models import ProfileChangeRequest
from profiles.services import submit_change_request
from privacy.models import PrivacyPolicy

from .forms import (
    BiographyForm,
    ExistingSourceLinkForm,
    LifeEventForm,
    SourceCreateForm,
    SourceEditForm,
    VerificationForm,
    MediaAssetUploadForm,
    MediaAssetMetadataForm,
)

from .models import (
    Biography,
    LifeEvent,
    SourceLink,
    Verification,
    MediaAsset,
    Source,
)

from .permissions import can_verify_heritage, can_view_media


logger = logging.getLogger(__name__)

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


def get_source_person(source):
    for link in source.links.all():
        model = HERITAGE_RESOURCE_MODELS.get(link.resource_type)
        if model is None:
            continue

        resource = (
            model.objects
            .select_related("person")
            .filter(id=link.object_id)
            .first()
        )
        if resource is not None:
            return resource.person

    return None


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

    if not can_propose_person(request.user, person):
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
            proposal, created = submit_change_request(
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
            messages.info(request, "Предложение отправлено на одобрение." if created else "Для этой записи уже есть предложение на рассмотрении. Новые изменения не отправлены.")

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

    if not can_propose_resource(request.user, biography.person, "BIOGRAPHY", biography.id):
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
            proposal, created = submit_change_request(
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
            messages.info(request, "Предложение отправлено на одобрение." if created else "Для этой записи уже есть предложение на рассмотрении. Новые изменения не отправлены.")

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

    if not can_propose_resource(request.user, biography.person, "BIOGRAPHY", biography.id):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    if request.method == "POST":
        proposal, created = submit_change_request(
            resource_type=(
                ProfileChangeRequest.ResourceType.BIOGRAPHY
            ),
            object_id=biography.id,
            action=ProfileChangeRequest.Action.DELETE,
            requested_by=request.user,
        )
        messages.info(request, "Предложение отправлено на одобрение." if created else "Для этой записи уже есть предложение на рассмотрении. Новые изменения не отправлены.")

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

    if not can_propose_person(request.user, person):
        raise PermissionDenied

    if request.method == "POST":
        form = LifeEventForm(
            request.POST
        )

        if form.is_valid():
            proposal, created = submit_change_request(
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
            messages.info(request, "Предложение отправлено на одобрение." if created else "Для этой записи уже есть предложение на рассмотрении. Новые изменения не отправлены.")

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

    if not can_propose_resource(request.user, event.person, "LIFE_EVENT", event.id):
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
            proposal, created = submit_change_request(
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
            messages.info(request, "Предложение отправлено на одобрение." if created else "Для этой записи уже есть предложение на рассмотрении. Новые изменения не отправлены.")

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

    if not can_propose_resource(request.user, event.person, "LIFE_EVENT", event.id):
        raise PermissionDenied

    if request.method == "POST":
        proposal, created = submit_change_request(
            resource_type=(
                ProfileChangeRequest.ResourceType.LIFE_EVENT
            ),
            object_id=event.id,
            action=ProfileChangeRequest.Action.DELETE,
            requested_by=request.user,
        )
        messages.info(request, "Предложение отправлено на одобрение." if created else "Для этой записи уже есть предложение на рассмотрении. Новые изменения не отправлены.")

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
            request.POST,
            user=request.user,
            person=resource.person,
            lock_document=True,
        )

        if form.is_valid():
            source = form.save(
                commit=False
            )

            source.created_by = request.user
            source.save()

            source_link = SourceLink.objects.create(
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

            log_audit_event(
                actor=request.user,
                action=AuditEvent.Action.CREATE_SOURCE,
                person=resource.person,
                resource_type=resource_type,
                object_id=resource.id,
                details={
                    "source_id": str(source.id),
                    "source_link_id": str(source_link.id),
                    "source_type": source.source_type,
                    "relation_type": source_link.relation_type,
                    **(
                        {"document_id": str(source.document_id)}
                        if source.document_id is not None
                        else {}
                    ),
                },
            )

            return redirect(
                "family:person_detail",
                person_id=resource.person.id,
            )

    else:
        form = SourceCreateForm(user=request.user, person=resource.person)

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
def edit_source(request, source_id):
    source = get_object_or_404(
        Source.objects.select_for_update(),
        id=source_id,
    )

    if source.status == Source.Status.ARCHIVED:
        raise Http404

    if not (
        is_system_admin(request.user)
        or source.created_by_id == request.user.id
    ):
        raise PermissionDenied(
            "Только автор источника или администратор может его изменять."
        )

    person = get_source_person(source)
    editable_fields = [
        "source_type",
        "title",
        "author",
        "source_date",
        "url",
        "citation",
        "notes",
    ]
    old_values = {
        field_name: getattr(source, field_name)
        for field_name in editable_fields
    }

    if request.method == "POST":
        form = SourceEditForm(request.POST, instance=source)

        if form.is_valid():
            changed_fields = [
                field_name
                for field_name in editable_fields
                if old_values[field_name]
                != form.cleaned_data[field_name]
            ]

            form.save()

            if changed_fields:
                log_audit_event(
                    actor=request.user,
                    action=AuditEvent.Action.UPDATE_SOURCE,
                    person=person,
                    resource_type="SOURCE",
                    object_id=source.id,
                    details={
                        "source_id": str(source.id),
                        "changed_fields": sorted(changed_fields),
                    },
                )

            if person is not None:
                return redirect(
                    "family:person_detail",
                    person_id=person.id,
                )

            return redirect("family:home")

    else:
        form = SourceEditForm(instance=source)

    return render(
        request,
        "heritage/source_form.html",
        {
            "form": form,
            "resource": source,
            "person": person,
            "title": "Изменить источник",
        },
    )


@login_required
@require_POST
@transaction.atomic
def archive_source(request, source_id):
    source = get_object_or_404(
        Source.objects.select_for_update(),
        id=source_id,
    )

    if not (
        is_system_admin(request.user)
        or source.created_by_id == request.user.id
    ):
        raise PermissionDenied(
            "Только автор источника или администратор может его архивировать."
        )

    if source.status == Source.Status.ARCHIVED:
        person = get_source_person(source)
        if person is not None:
            return redirect(
                "family:person_detail",
                person_id=person.id,
            )
        return redirect("family:home")

    person = get_source_person(source)
    source.status = Source.Status.ARCHIVED
    source.save(update_fields=["status", "updated_at"])

    log_audit_event(
        actor=request.user,
        action=AuditEvent.Action.ARCHIVE_SOURCE,
        person=person,
        resource_type="SOURCE",
        object_id=source.id,
        details={
            "source_id": str(source.id),
            "previous_status": Source.Status.ACTIVE,
            "status": source.status,
        },
    )

    if person is not None:
        return redirect(
            "family:person_detail",
            person_id=person.id,
        )

    return redirect("family:home")

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
            request.POST,
            user=request.user,
            person=resource.person,
            lock_source=True,
        )

        if form.is_valid():
            source = form.cleaned_data[
                "source"
            ]

            relation_type = form.cleaned_data[
                "relation_type"
            ]
            note = form.cleaned_data["note"]

            source_link, created = (
                SourceLink.objects.update_or_create(
                    source=source,
                    resource_type=resource_type,
                    object_id=resource.id,
                    defaults={},
                    create_defaults={
                        "relation_type":
                            relation_type,
                        "note": note,
                        "created_by":
                            request.user,
                    },
                )
            )

            if created:
                log_audit_event(
                    actor=request.user,
                    action=AuditEvent.Action.ATTACH_SOURCE,
                    person=resource.person,
                    resource_type=resource_type,
                    object_id=resource.id,
                    details={
                        "source_id": str(source.id),
                        "source_link_id": str(source_link.id),
                        "relation_type": source_link.relation_type,
                    },
                )

            else:
                changed_fields = []

                if source_link.relation_type != relation_type:
                    source_link.relation_type = relation_type
                    changed_fields.append("relation_type")

                if source_link.note != note:
                    source_link.note = note
                    changed_fields.append("note")

                if changed_fields:
                    source_link.save(
                        update_fields=changed_fields,
                    )

                    log_audit_event(
                        actor=request.user,
                        action=(
                            AuditEvent.Action.UPDATE_SOURCE_LINK
                        ),
                        person=resource.person,
                        resource_type=resource_type,
                        object_id=resource.id,
                        details={
                            "source_id": str(source.id),
                            "source_link_id": str(source_link.id),
                            "changed_fields": sorted(
                                changed_fields
                            ),
                        },
                    )

            return redirect(
                "family:person_detail",
                person_id=resource.person.id,
            )

    else:
        form = ExistingSourceLinkForm(user=request.user, person=resource.person)

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
    audit_details = {
        "source_id": str(link.source_id),
        "source_link_id": str(link.id),
        "relation_type": link.relation_type,
    }

    link.delete()

    log_audit_event(
        actor=request.user,
        action=AuditEvent.Action.DETACH_SOURCE,
        person=resource.person,
        resource_type=link.resource_type,
        object_id=resource.id,
        details=audit_details,
    )

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

    verification_queryset = Verification.objects

    if request.method == "POST":
        verification_queryset = (
            verification_queryset.select_for_update()
        )

    verification = verification_queryset.filter(
        resource_type=resource_type,
        object_id=resource.id,
    ).first()

    previous_status = (
        verification.status
        if verification is not None
        else None
    )

    if verification is None:
        verification = Verification(
            resource_type=resource_type,
            object_id=resource.id,
            status=Verification.Status.PENDING,
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
                details={
                    "verification_id": str(verification.id),
                    "previous_status": previous_status,
                    "current_status": verification.status,
                },
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

    if not can_propose_person(request.user, person):
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
                    "verified_content_type",
                    "",
                )
            )

            media_asset.file_size = (
                uploaded_file.size
            )

            media_asset.status = (
                MediaAsset.Status.PENDING
            )

            stored_file_name = ""

            try:
                media_asset.save()
                stored_file_name = media_asset.file.name

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

                log_audit_event(
                    actor=request.user,
                    action=AuditEvent.Action.UPLOAD_MEDIA,
                    person=person,
                    resource_type="MEDIA_ASSET",
                    object_id=media_asset.id,
                    details={
                        "media_type": media_asset.media_type,
                        "mime_type": media_asset.mime_type,
                        "file_size": media_asset.file_size,
                        "status": media_asset.status,
                    },
                )

            except Exception:
                if (
                    not stored_file_name
                    and getattr(
                        media_asset.file,
                        "_committed",
                        False,
                    )
                ):
                    stored_file_name = (
                        media_asset.file.name
                    )

                if stored_file_name:
                    try:
                        media_asset.file.storage.delete(
                            stored_file_name
                        )
                    except Exception:
                        logger.exception(
                            "Не удалось удалить файл "
                            "после ошибки загрузки."
                        )

                raise

            messages.success(request, "Файл отправлен на проверку. Семья увидит его после одобрения.")
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

@never_cache
@login_required
def serve_media_asset(request, media_id):
    media_asset = get_object_or_404(
        MediaAsset.objects.select_related(
            "person"
        ),
        id=media_id,
    )

    person = media_asset.person

    if not can_view_media(request.user, media_asset):
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
    if not can_manage_relationships(request.user):
        raise PermissionDenied(
            "Проверять файлы может администратор или участник с правом одобрения."
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
    if not can_manage_relationships(request.user):
        raise PermissionDenied(
            "Проверять файлы может администратор или участник с правом одобрения."
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
    if not can_manage_relationships(request.user):
        raise PermissionDenied(
            "Проверять файлы может администратор или участник с правом одобрения."
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


@login_required
@require_POST
@transaction.atomic
def archive_media_asset(request, media_id):
    media_asset = get_object_or_404(
        MediaAsset.objects.select_related("person"),
        id=media_id,
    )

    if not can_manage_person(request.user, media_asset.person):
        raise PermissionDenied(
            "У вас нет права архивировать этот файл."
        )

    if media_asset.status == MediaAsset.Status.ARCHIVED:
        return redirect(
            "family:person_detail",
            person_id=media_asset.person_id,
        )

    previous_status = media_asset.status
    media_asset.status = MediaAsset.Status.ARCHIVED
    media_asset.save(update_fields=["status", "updated_at"])

    log_audit_event(
        actor=request.user,
        action=AuditEvent.Action.ARCHIVE_MEDIA,
        person=media_asset.person,
        resource_type="MEDIA_ASSET",
        object_id=media_asset.id,
        details={
            "previous_status": previous_status,
            "status": media_asset.status,
        },
    )

    return redirect(
        "family:person_detail",
        person_id=media_asset.person_id,
    )


@login_required
def edit_media_asset(request, media_id):
    media_asset = get_object_or_404(
        MediaAsset.objects.select_related("person"),
        id=media_id,
    )

    if media_asset.status == MediaAsset.Status.ARCHIVED:
        raise Http404

    if not (can_propose_person(request.user, media_asset.person) and can_view_media(request.user, media_asset)):
        raise PermissionDenied(
            "У вас нет права изменять этот файл."
        )

    old_values = {
        "title": media_asset.title,
        "description": media_asset.description,
    }

    if request.method == "POST":
        form = MediaAssetMetadataForm(
            request.POST,
            instance=media_asset,
        )

        if form.is_valid():
            if form.has_changed():
                proposal, created = submit_change_request(
                    resource_type=ProfileChangeRequest.ResourceType.MEDIA_ASSET,
                    object_id=media_asset.pk, action=ProfileChangeRequest.Action.EDIT,
                    requested_by=request.user,
                    proposed_data={key: form.cleaned_data[key] for key in ("title", "description")},
                )
                messages.info(request, "Описание отправлено на одобрение." if created else
                              "Для этого файла уже есть предложение. Новые изменения не отправлены — дождитесь решения.")
            else:
                messages.info(request, "Изменений нет.")

            return redirect(
                "family:person_detail",
                person_id=media_asset.person_id,
            )
    else:
        form = MediaAssetMetadataForm(instance=media_asset)

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": media_asset.person,
            "title": "Предложить описание файла",
        },
    )
