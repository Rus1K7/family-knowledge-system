from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.models import User
from audit.models import AuditEvent
from audit.services import log_audit_event
from family.permissions import can_manage_person
from family.models import Person
from heritage.models import Biography, LifeEvent
from network.models import HelpOffer

from .forms import EducationForm, EmploymentForm, SkillForm
from .models import (
    Education,
    Employment,
    ProfileChangeRequest,
    Skill,
)
from .services import submit_change_request

def system_admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        is_admin = (
            request.user.is_superuser
            or request.user.system_role == User.SystemRole.SYSTEM_ADMIN
        )

        if not is_admin:
            raise PermissionDenied

        return view_func(request, *args, **kwargs)

    return wrapper

def get_change_target(change_request):
    model_map = {
        ProfileChangeRequest.ResourceType.EMPLOYMENT: Employment,
        ProfileChangeRequest.ResourceType.EDUCATION: Education,
        ProfileChangeRequest.ResourceType.SKILL: Skill,
        ProfileChangeRequest.ResourceType.HELP_OFFER: HelpOffer,
        ProfileChangeRequest.ResourceType.BIOGRAPHY: Biography,
        ProfileChangeRequest.ResourceType.LIFE_EVENT: LifeEvent,
    }

    model = model_map.get(
        change_request.resource_type
    )

    if model is None:
        return None

    return model.objects.filter(
        id=change_request.object_id
    ).first()


def get_change_person(change_request):
    if (
        change_request.action
        == ProfileChangeRequest.Action.CREATE
    ):
        person_id = change_request.proposed_data.get(
            "person_id"
        )

        if not person_id:
            return None

        return Person.objects.filter(
            id=person_id
        ).first()

    target = get_change_target(change_request)

    if target is None:
        return None

    return target.person


@login_required
def my_change_requests(request):
    requests = ProfileChangeRequest.objects.filter(
        requested_by=request.user,
    ).order_by("-requested_at", "-id")
    page = Paginator(requests, 20).get_page(request.GET.get("page"))
    return render(request, "profiles/my_changes.html", {"page_obj": page})


@system_admin_required
def change_request_list(request):
    change_requests = (
        ProfileChangeRequest.objects
        .filter(
            status=ProfileChangeRequest.Status.PENDING
        )
        .select_related(
            "requested_by",
        )
        .order_by(
            "requested_at"
        )
    )

    items = []

    for change_request in change_requests:
        target = None
        target_person = None

        if (
            change_request.action
            == ProfileChangeRequest.Action.CREATE
        ):
            person_id = change_request.proposed_data.get(
                "person_id"
            )

            if person_id:
                target_person = (
                    Person.objects
                    .filter(id=person_id)
                    .first()
                )

        else:
            target = get_change_target(
                change_request
            )

            if target is not None:
                target_person = target.person

        proposed_rows = []

        for field_name, value in (
            change_request.proposed_data.items()
        ):
            proposed_rows.append(
                {
                    "field": field_name,
                    "value": value,
                }
            )

        items.append(
            {
                "request": change_request,
                "target": target,
                "person": target_person,
                "proposed_rows": proposed_rows,
            }
        )

    return render(
        request,
        "profiles/change_request_list.html",
        {
            "items": items,
        },
    )
@system_admin_required
@require_POST
@transaction.atomic
def approve_change_request(request, request_id):
    change_request = get_object_or_404(
        ProfileChangeRequest.objects.select_for_update(),
        id=request_id,
        status=ProfileChangeRequest.Status.PENDING,
    )

    data = change_request.proposed_data
    audit_person = None
    audit_object_id = change_request.object_id

    #
    # CREATE
    #
    if (
        change_request.action
        == ProfileChangeRequest.Action.CREATE
    ):
        person = get_object_or_404(
            Person,
            id=data["person_id"],
        )

        if (
            change_request.resource_type
            == ProfileChangeRequest.ResourceType.EMPLOYMENT
        ):
            target = Employment.objects.create(
                person=person,
                organization=data.get(
                    "organization",
                    "",
                ),
                position=data.get(
                    "position",
                    "",
                ),
                start_date=(
                    parse_date(data["start_date"])
                    if data.get("start_date")
                    else None
                ),
                end_date=(
                    parse_date(data["end_date"])
                    if data.get("end_date")
                    else None
                ),
                is_current=data.get(
                    "is_current",
                    False,
                ),
                description=data.get(
                    "description",
                    "",
                ),
            )

        elif (
            change_request.resource_type
            == ProfileChangeRequest.ResourceType.EDUCATION
        ):
            target = Education.objects.create(
                person=person,
                institution=data.get(
                    "institution",
                    "",
                ),
                degree=data.get(
                    "degree",
                    "",
                ),
                field_of_study=data.get(
                    "field_of_study",
                    "",
                ),
                start_year=data.get(
                    "start_year"
                ),
                end_year=data.get(
                    "end_year"
                ),
                description=data.get(
                    "description",
                    "",
                ),
            )

        elif (
            change_request.resource_type
            == ProfileChangeRequest.ResourceType.SKILL
        ):
            target = Skill.objects.create(
                person=person,
                name=data.get(
                    "name",
                    "",
                ),
                description=data.get(
                    "description",
                    "",
                ),
            )
        elif (
                change_request.resource_type
                == ProfileChangeRequest.ResourceType.HELP_OFFER
        ):
            target = HelpOffer.objects.create(
                person=person,
                title=data.get(
                    "title",
                    "",
                ),
                category=data.get(
                    "category",
                    HelpOffer.Category.OTHER,
                ),
                description=data.get(
                    "description",
                    "",
                ),
                is_active=data.get(
                    "is_active",
                    True,
                ),
            )
        elif (
                change_request.resource_type
                == ProfileChangeRequest.ResourceType.BIOGRAPHY
        ):
            person = get_object_or_404(
                Person,
                id=data["person_id"],
            )

            target = Biography.objects.create(
                person=person,
                text=data["text"],
                created_by=change_request.requested_by,
            )
        elif (
                change_request.resource_type
                == ProfileChangeRequest.ResourceType.LIFE_EVENT
        ):
            person = get_object_or_404(
                Person,
                id=data["person_id"],
            )

            target = LifeEvent.objects.create(
                person=person,
                event_type=data["event_type"],
                title=data["title"],
                start_date=parse_date(
                    data["start_date"]
                ) if data.get("start_date") else None,
                end_date=parse_date(
                    data["end_date"]
                ) if data.get("end_date") else None,
                date_precision=data["date_precision"],
                place=data.get("place", ""),
                description=data.get(
                    "description",
                    "",
                ),
                created_by=change_request.requested_by,
            )

        else:
            raise PermissionDenied(
                "Неизвестный тип создаваемых данных."
            )

        audit_person = person
        audit_object_id = target.id

    #
    # EDIT / DELETE
    #
    else:
        target = get_change_target(
            change_request
        )

        if target is None:
            raise PermissionDenied(
                "Исходная запись не существует."
            )

        audit_person = target.person
        audit_object_id = target.id

        if (
            change_request.action
            == ProfileChangeRequest.Action.DELETE
        ):
            target.delete()

        elif (
            change_request.action
            == ProfileChangeRequest.Action.EDIT
        ):

            if (
                change_request.resource_type
                == ProfileChangeRequest.ResourceType.EMPLOYMENT
            ):
                target.organization = data.get(
                    "organization",
                    "",
                )

                target.position = data.get(
                    "position",
                    "",
                )

                target.start_date = (
                    parse_date(data["start_date"])
                    if data.get("start_date")
                    else None
                )

                target.end_date = (
                    parse_date(data["end_date"])
                    if data.get("end_date")
                    else None
                )

                target.is_current = data.get(
                    "is_current",
                    False,
                )

                target.description = data.get(
                    "description",
                    "",
                )

                target.save()

            elif (
                change_request.resource_type
                == ProfileChangeRequest.ResourceType.EDUCATION
            ):
                target.institution = data.get(
                    "institution",
                    "",
                )

                target.degree = data.get(
                    "degree",
                    "",
                )

                target.field_of_study = data.get(
                    "field_of_study",
                    "",
                )

                target.start_year = data.get(
                    "start_year"
                )

                target.end_year = data.get(
                    "end_year"
                )

                target.description = data.get(
                    "description",
                    "",
                )

                target.save()

            elif (
                change_request.resource_type
                == ProfileChangeRequest.ResourceType.SKILL
            ):
                target.name = data.get(
                    "name",
                    "",
                )

                target.description = data.get(
                    "description",
                    "",
                )

                target.save()
            elif (
                    change_request.resource_type
                    == ProfileChangeRequest.ResourceType.HELP_OFFER
            ):
                target.title = data.get(
                    "title",
                    "",
                )

                target.category = data.get(
                    "category",
                    HelpOffer.Category.OTHER,
                )

                target.description = data.get(
                    "description",
                    "",
                )

                target.is_active = data.get(
                    "is_active",
                    True,
                )

                target.save()
            elif (
                    change_request.resource_type
                    == ProfileChangeRequest.ResourceType.BIOGRAPHY
            ):
                target.text = data["text"]

                target.save(
                    update_fields=[
                        "text",
                        "updated_at",
                    ]
                )
            elif (
                    change_request.resource_type
                    == ProfileChangeRequest.ResourceType.LIFE_EVENT
            ):
                target.event_type = data["event_type"]
                target.title = data["title"]

                target.start_date = (
                    parse_date(data["start_date"])
                    if data.get("start_date")
                    else None
                )

                target.end_date = (
                    parse_date(data["end_date"])
                    if data.get("end_date")
                    else None
                )

                target.date_precision = data["date_precision"]
                target.place = data.get("place", "")
                target.description = data.get(
                    "description",
                    "",
                )

                target.save()

    change_request.status = (
        ProfileChangeRequest.Status.APPROVED
    )

    change_request.reviewed_by = request.user
    change_request.reviewed_at = timezone.now()

    change_request.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
        ]
    )

    log_audit_event(
        actor=request.user,
        action=AuditEvent.Action.APPROVE_CHANGE,
        person=audit_person,
        resource_type=change_request.resource_type,
        object_id=audit_object_id,
        details={
            "request_id": str(change_request.id),
            "requester_id": str(change_request.requested_by_id),
            "change_action": change_request.action,
            "target_id": (
                str(audit_object_id)
                if audit_object_id is not None
                else None
            ),
        },
    )

    return redirect(
        "profiles:change_request_list"
    )

@system_admin_required
@require_POST
@transaction.atomic
def reject_change_request(request, request_id):
    change_request = get_object_or_404(
        ProfileChangeRequest.objects.select_for_update(),
        id=request_id,
        status=ProfileChangeRequest.Status.PENDING,
    )

    audit_person = get_change_person(
        change_request
    )

    change_request.status = (
        ProfileChangeRequest.Status.REJECTED
    )

    change_request.reviewed_by = request.user
    change_request.reviewed_at = timezone.now()

    change_request.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
        ]
    )

    log_audit_event(
        actor=request.user,
        action=AuditEvent.Action.REJECT_CHANGE,
        person=audit_person,
        resource_type=change_request.resource_type,
        object_id=change_request.object_id,
        details={
            "request_id": str(change_request.id),
            "requester_id": str(change_request.requested_by_id),
            "change_action": change_request.action,
            "target_id": (
                str(change_request.object_id)
                if change_request.object_id is not None
                else None
            ),
        },
    )

    return redirect(
        "profiles:change_request_list"
    )

@login_required
def add_employment(request, person_id):
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
        form = EmploymentForm(request.POST)

        if form.is_valid():
            submit_change_request(
                resource_type=(
                    ProfileChangeRequest.ResourceType.EMPLOYMENT
                ),
                object_id=None,
                action=ProfileChangeRequest.Action.CREATE,
                proposed_data={
                    "person_id": str(person.id),

                    "organization": (
                        form.cleaned_data["organization"]
                    ),

                    "position": (
                        form.cleaned_data["position"]
                    ),

                    "start_date": (
                        form.cleaned_data["start_date"].isoformat()
                        if form.cleaned_data["start_date"]
                        else None
                    ),

                    "end_date": (
                        form.cleaned_data["end_date"].isoformat()
                        if form.cleaned_data["end_date"]
                        else None
                    ),

                    "is_current": (
                        form.cleaned_data["is_current"]
                    ),

                    "description": (
                        form.cleaned_data["description"]
                    ),
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=person.id,
            )

    else:
        form = EmploymentForm()

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": person,
            "title": "Предложить место работы",
        },
    )

@login_required
def add_education(request, person_id):
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
        form = EducationForm(request.POST)

        if form.is_valid():
            submit_change_request(
                resource_type=(
                    ProfileChangeRequest.ResourceType.EDUCATION
                ),
                object_id=None,
                action=ProfileChangeRequest.Action.CREATE,
                proposed_data={
                    "person_id": str(person.id),

                    "institution": (
                        form.cleaned_data["institution"]
                    ),

                    "degree": (
                        form.cleaned_data["degree"]
                    ),

                    "field_of_study": (
                        form.cleaned_data["field_of_study"]
                    ),

                    "start_year": (
                        form.cleaned_data["start_year"]
                    ),

                    "end_year": (
                        form.cleaned_data["end_year"]
                    ),

                    "description": (
                        form.cleaned_data["description"]
                    ),
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=person.id,
            )

    else:
        form = EducationForm()

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": person,
            "title": "Предложить образование",
        },
    )

@login_required
def add_skill(request, person_id):
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
        form = SkillForm(request.POST)

        if form.is_valid():
            submit_change_request(
                resource_type=(
                    ProfileChangeRequest.ResourceType.SKILL
                ),
                object_id=None,
                action=ProfileChangeRequest.Action.CREATE,
                proposed_data={
                    "person_id": str(person.id),

                    "name": (
                        form.cleaned_data["name"]
                    ),

                    "description": (
                        form.cleaned_data["description"]
                    ),
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=person.id,
            )

    else:
        form = SkillForm()

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": person,
            "title": "Предложить навык",
        },
    )


@login_required
def edit_employment(request, employment_id):
    employment = get_object_or_404(
        Employment,
        id=employment_id,
    )

    if not can_manage_person(
            request.user,
            employment.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    # Не разрешаем создать второй запрос,
    # пока предыдущий ещё рассматривается.
    pending_request = ProfileChangeRequest.objects.filter(
        resource_type=ProfileChangeRequest.ResourceType.EMPLOYMENT,
        object_id=employment.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).first()

    if pending_request:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": employment.person,
                "change_request": pending_request,
            },
        )

    if request.method == "POST":
        form = EmploymentForm(
            request.POST,
            instance=employment,
        )

        if form.is_valid():

            # ВАЖНО:
            # здесь НЕТ form.save()

            submit_change_request(
                resource_type=(
                    ProfileChangeRequest.ResourceType.EMPLOYMENT
                ),
                object_id=employment.id,
                action=ProfileChangeRequest.Action.EDIT,
                proposed_data={
                    "organization": form.cleaned_data["organization"],
                    "position": form.cleaned_data["position"],
                    "start_date": (
                        form.cleaned_data["start_date"].isoformat()
                        if form.cleaned_data["start_date"]
                        else None
                    ),
                    "end_date": (
                        form.cleaned_data["end_date"].isoformat()
                        if form.cleaned_data["end_date"]
                        else None
                    ),
                    "is_current": form.cleaned_data["is_current"],
                    "description": form.cleaned_data["description"],
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=employment.person.id,
            )

    else:
        form = EmploymentForm(
            instance=employment,
        )

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": employment.person,
            "title": "Предложить изменение места работы",
        },
    )

@login_required
def edit_education(request, education_id):
    education = get_object_or_404(
        Education,
        id=education_id,
    )
    if not can_manage_person(
            request.user,
            education.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    pending_request = ProfileChangeRequest.objects.filter(
        resource_type=ProfileChangeRequest.ResourceType.EDUCATION,
        object_id=education.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).first()

    if pending_request:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": education.person,
                "change_request": pending_request,
            },
        )

    if request.method == "POST":
        form = EducationForm(
            request.POST,
            instance=education,
        )

        if form.is_valid():

            submit_change_request(
                resource_type=(
                    ProfileChangeRequest.ResourceType.EDUCATION
                ),
                object_id=education.id,
                action=ProfileChangeRequest.Action.EDIT,
                proposed_data={
                    "institution": form.cleaned_data["institution"],
                    "degree": form.cleaned_data["degree"],
                    "field_of_study": form.cleaned_data["field_of_study"],
                    "start_year": form.cleaned_data["start_year"],
                    "end_year": form.cleaned_data["end_year"],
                    "description": form.cleaned_data["description"],
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=education.person.id,
            )

    else:
        form = EducationForm(
            instance=education,
        )

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": education.person,
            "title": "Предложить изменение образования",
        },
    )

@login_required
def edit_skill(request, skill_id):
    skill = get_object_or_404(
        Skill,
        id=skill_id,
    )
    if not can_manage_person(
            request.user,
            skill.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    pending_request = ProfileChangeRequest.objects.filter(
        resource_type=ProfileChangeRequest.ResourceType.SKILL,
        object_id=skill.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).first()

    if pending_request:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": skill.person,
                "change_request": pending_request,
            },
        )

    if request.method == "POST":
        form = SkillForm(
            request.POST,
            instance=skill,
        )

        if form.is_valid():

            submit_change_request(
                resource_type=(
                    ProfileChangeRequest.ResourceType.SKILL
                ),
                object_id=skill.id,
                action=ProfileChangeRequest.Action.EDIT,
                proposed_data={
                    "name": form.cleaned_data["name"],
                    "description": form.cleaned_data["description"],
                },
                requested_by=request.user,
            )

            return redirect(
                "family:person_detail",
                person_id=skill.person.id,
            )

    else:
        form = SkillForm(
            instance=skill,
        )

    return render(
        request,
        "profiles/form.html",
        {
            "form": form,
            "person": skill.person,
            "title": "Предложить изменение навыка",
        },
    )

@login_required
def delete_employment(request, employment_id):
    employment = get_object_or_404(
        Employment,
        id=employment_id,
    )
    if not can_manage_person(
            request.user,
            employment.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    pending_request = ProfileChangeRequest.objects.filter(
        resource_type=ProfileChangeRequest.ResourceType.EMPLOYMENT,
        object_id=employment.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).first()

    if pending_request:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": employment.person,
                "change_request": pending_request,
            },
        )

    if request.method == "POST":
        submit_change_request(
            resource_type=ProfileChangeRequest.ResourceType.EMPLOYMENT,
            object_id=employment.id,
            action=ProfileChangeRequest.Action.DELETE,
            requested_by=request.user,
        )

        return redirect(
            "family:person_detail",
            person_id=employment.person.id,
        )

    return render(
        request,
        "profiles/confirm_delete.html",
        {
            "person": employment.person,
            "object": employment,
            "title": "Запросить удаление места работы",
        },
    )

@login_required
def delete_education(request, education_id):
    education = get_object_or_404(
        Education,
        id=education_id,
    )
    if not can_manage_person(
            request.user,
            education.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    pending_request = ProfileChangeRequest.objects.filter(
        resource_type=ProfileChangeRequest.ResourceType.EDUCATION,
        object_id=education.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).first()

    if pending_request:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": education.person,
                "change_request": pending_request,
            },
        )

    if request.method == "POST":
        submit_change_request(
            resource_type=ProfileChangeRequest.ResourceType.EDUCATION,
            object_id=education.id,
            action=ProfileChangeRequest.Action.DELETE,
            requested_by=request.user,
        )

        return redirect(
            "family:person_detail",
            person_id=education.person.id,
        )

    return render(
        request,
        "profiles/confirm_delete.html",
        {
            "person": education.person,
            "object": education,
            "title": "Запросить удаление образования",
        },
    )

@login_required
def delete_skill(request, skill_id):
    skill = get_object_or_404(
        Skill,
        id=skill_id,
    )
    if not can_manage_person(
            request.user,
            skill.person,
    ):
        raise PermissionDenied(
            "Вы не можете изменять этот профиль."
        )

    pending_request = ProfileChangeRequest.objects.filter(
        resource_type=ProfileChangeRequest.ResourceType.SKILL,
        object_id=skill.id,
        status=ProfileChangeRequest.Status.PENDING,
    ).first()

    if pending_request:
        return render(
            request,
            "profiles/change_pending.html",
            {
                "person": skill.person,
                "change_request": pending_request,
            },
        )

    if request.method == "POST":
        submit_change_request(
            resource_type=ProfileChangeRequest.ResourceType.SKILL,
            object_id=skill.id,
            action=ProfileChangeRequest.Action.DELETE,
            requested_by=request.user,
        )

        return redirect(
            "family:person_detail",
            person_id=skill.person.id,
        )

    return render(
        request,
        "profiles/confirm_delete.html",
        {
            "person": skill.person,
            "object": skill,
            "title": "Запросить удаление навыка",
        },
    )
