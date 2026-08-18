from collections import deque

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.shortcuts import redirect

from .forms import AddRelativeForm
from .models import Person, ProfileOwnership, Relationship

from .permissions import (
    can_manage_person,
    is_system_admin,
)
from privacy.models import (
    AccessRequest,
    PrivacyPolicy,
)
from privacy.permissions import (
    can_see_resource_existence,
    can_view_resource,
    get_policy,
)
from heritage.models import (
    Biography,
    SourceLink,
)

def build_generation_levels(persons, relationships):
    """
    Вычисляет поколение каждого человека.

    Правила:
    - родитель находится на 1 уровень выше ребёнка;
    - приёмный родитель также на 1 уровень выше;
    - супруги/партнёры находятся на одном уровне;
    - братья/сёстры находятся на одном уровне;
    - уровень не хранится в БД;
    - после добавления новых предков все уровни пересчитываются.
    """

    person_ids = {
        str(person.id)
        for person in persons
    }

    # Для каждого человека:
    # сосед -> разница уровней
    #
    # Например:
    # Parent -> Child = +1
    # Child -> Parent = -1
    # Spouse -> Spouse = 0
    graph = {
        person_id: []
        for person_id in person_ids
    }

    for relationship in relationships:
        a_id = str(relationship.person_a_id)
        b_id = str(relationship.person_b_id)

        relation_type = relationship.relationship_type

        if relation_type in {
            Relationship.Type.PARENT_CHILD,
            Relationship.Type.ADOPTIVE_PARENT,
        }:
            # person_a = родитель
            # person_b = ребёнок
            graph[a_id].append((b_id, 1))
            graph[b_id].append((a_id, -1))

        elif relation_type in {
            Relationship.Type.SPOUSE,
            Relationship.Type.PARTNER,
            Relationship.Type.SIBLING,
        }:
            graph[a_id].append((b_id, 0))
            graph[b_id].append((a_id, 0))

        # GUARDIAN пока не используем
        # для определения поколения.

    levels = {}
    conflicts = []

    # Семья потенциально может состоять
    # из нескольких пока не связанных веток.
    for start_person_id in person_ids:

        if start_person_id in levels:
            continue

        component = []

        queue = deque([start_person_id])
        levels[start_person_id] = 0

        while queue:
            current_id = queue.popleft()
            component.append(current_id)

            current_level = levels[current_id]

            for neighbour_id, offset in graph[current_id]:
                expected_level = current_level + offset

                if neighbour_id not in levels:
                    levels[neighbour_id] = expected_level
                    queue.append(neighbour_id)

                elif levels[neighbour_id] != expected_level:
                    conflicts.append(
                        {
                            "person_id": neighbour_id,
                            "current_level": levels[neighbour_id],
                            "expected_level": expected_level,
                        }
                    )

        # Нормализуем ветку:
        # самый верхний известный предок = уровень 0.
        component_levels = [
            levels[person_id]
            for person_id in component
        ]

        minimum_level = min(component_levels)

        if minimum_level != 0:
            for person_id in component:
                levels[person_id] -= minimum_level

    return levels, conflicts


@login_required
def family_home(request):
    persons = list(
        Person.objects.all().order_by(
            "last_name",
            "first_name",
        )
    )

    relationships = list(
        Relationship.objects
        .filter(
            status=Relationship.Status.VERIFIED
        )
        .select_related(
            "person_a",
            "person_b",
        )
    )

    levels, conflicts = build_generation_levels(
        persons,
        relationships,
    )

    nodes = []

    for person in persons:
        person_id = str(person.id)

        nodes.append(
            {
                "id": person_id,
                "label": str(person),
                "url": f"/family/person/{person.id}/",
                "level": levels.get(person_id, 0),
            }
        )

    edges = []

    for relationship in relationships:
        edge = {
            "from": str(relationship.person_a_id),
            "to": str(relationship.person_b_id),
            "type": relationship.relationship_type,
        }

        if relationship.relationship_type in {
            Relationship.Type.PARENT_CHILD,
            Relationship.Type.ADOPTIVE_PARENT,
        }:
            edge["kind"] = "parent"

        elif relationship.relationship_type in {
            Relationship.Type.SPOUSE,
            Relationship.Type.PARTNER,
        }:
            edge["kind"] = "partner"

        elif relationship.relationship_type == Relationship.Type.SIBLING:
            edge["kind"] = "sibling"

        else:
            edge["kind"] = "other"

        edges.append(edge)

    return render(
        request,
        "family/home.html",
        {
            "nodes": nodes,
            "edges": edges,
            "generation_conflicts": conflicts,

            "can_admin":
                is_system_admin(request.user),
        },
    )

@login_required
def person_detail(request, person_id):
    person = get_object_or_404(
        Person,
        id=person_id,
    )

    relationships_from = list(
        Relationship.objects
        .filter(
            person_a=person,
            status=Relationship.Status.VERIFIED,
        )
        .select_related("person_b")
    )

    relationships_to = list(
        Relationship.objects
        .filter(
            person_b=person,
            status=Relationship.Status.VERIFIED,
        )
        .select_related("person_a")
    )

    parents = []
    children = []
    spouses = []
    siblings = []

    for relationship in relationships_from:

        if relationship.relationship_type in {
            Relationship.Type.PARENT_CHILD,
            Relationship.Type.ADOPTIVE_PARENT,
        }:
            children.append(
                relationship.person_b
            )

        elif relationship.relationship_type in {
            Relationship.Type.SPOUSE,
            Relationship.Type.PARTNER,
        }:
            spouses.append(
                relationship.person_b
            )

        elif (
            relationship.relationship_type
            == Relationship.Type.SIBLING
        ):
            siblings.append(
                relationship.person_b
            )

    for relationship in relationships_to:

        if relationship.relationship_type in {
            Relationship.Type.PARENT_CHILD,
            Relationship.Type.ADOPTIVE_PARENT,
        }:
            parents.append(
                relationship.person_a
            )

        elif relationship.relationship_type in {
            Relationship.Type.SPOUSE,
            Relationship.Type.PARTNER,
        }:
            spouses.append(
                relationship.person_a
            )

        elif (
            relationship.relationship_type
            == Relationship.Type.SIBLING
        ):
            siblings.append(
                relationship.person_a
            )

    can_manage = can_manage_person(
        request.user,
        person,
    )
    pending_access_requests_count = 0

    if can_manage:

        if is_system_admin(request.user):

            pending_access_requests_count = (
                AccessRequest.objects
                .filter(
                    status=AccessRequest.Status.PENDING,
                )
                .count()
            )

        else:

            pending_access_requests_count = (
                AccessRequest.objects
                .filter(
                    policy__person=person,
                    status=AccessRequest.Status.PENDING,
                )
                .count()
            )

    employment_items = []
    education_items = []
    skill_items = []
    help_offer_items = []
    biography_item = None
    life_event_items = []

    for employment in person.employments.all():
        can_view = can_view_resource(
            request.user,
            person,
            PrivacyPolicy.ResourceType.EMPLOYMENT,
            employment.id,
        )

        show_existence = can_see_resource_existence(
            request.user,
            person,
            PrivacyPolicy.ResourceType.EMPLOYMENT,
            employment.id,
        )

        policy = get_policy(
            PrivacyPolicy.ResourceType.EMPLOYMENT,
            employment.id,
        )

        if can_view:
            employment_items.append(
                {
                    "object": employment,
                    "locked": False,
                }
            )

        elif show_existence:
            employment_items.append(
                {
                    "object": employment,
                    "locked": True,
                    "policy": policy,
                    "requestable": (
                            policy is not None
                            and policy.visibility
                            == PrivacyPolicy.Visibility.REQUEST_ONLY
                    ),
                }
            )

    for education in person.educations.all():
        can_view = can_view_resource(
            request.user,
            person,
            PrivacyPolicy.ResourceType.EDUCATION,
            education.id,
        )

        show_existence = can_see_resource_existence(
            request.user,
            person,
            PrivacyPolicy.ResourceType.EDUCATION,
            education.id,
        )

        policy = get_policy(
            PrivacyPolicy.ResourceType.EDUCATION,
            education.id,
        )

        if can_view:
            education_items.append(
                {
                    "object": education,
                    "locked": False,
                }
            )

        elif show_existence:
            education_items.append(
                {
                    "object": education,
                    "locked": True,
                    "policy": policy,
                    "requestable": (
                            policy is not None
                            and policy.visibility
                            == PrivacyPolicy.Visibility.REQUEST_ONLY
                    ),
                }
            )

    for skill in person.skills.all():
        can_view = can_view_resource(
            request.user,
            person,
            PrivacyPolicy.ResourceType.SKILL,
            skill.id,
        )

        show_existence = can_see_resource_existence(
            request.user,
            person,
            PrivacyPolicy.ResourceType.SKILL,
            skill.id,
        )

        policy = get_policy(
            PrivacyPolicy.ResourceType.SKILL,
            skill.id,
        )

        if can_view:
            skill_items.append(
                {
                    "object": skill,
                    "locked": False,
                }
            )

        elif show_existence:
            skill_items.append(
                {
                    "object": skill,
                    "locked": True,
                    "policy": policy,
                    "requestable": (
                            policy is not None
                            and policy.visibility
                            == PrivacyPolicy.Visibility.REQUEST_ONLY
                    ),
                }
            )

    for offer in person.help_offers.filter(is_active=True):
        can_view = can_view_resource(
            request.user,
            person,
            PrivacyPolicy.ResourceType.HELP_OFFER,
            offer.id,
        )

        show_existence = can_see_resource_existence(
            request.user,
            person,
            PrivacyPolicy.ResourceType.HELP_OFFER,
            offer.id,
        )

        policy = get_policy(
            PrivacyPolicy.ResourceType.HELP_OFFER,
            offer.id,
        )

        if can_view:
            help_offer_items.append(
                {
                    "object": offer,
                    "locked": False,
                }
            )

        elif show_existence:
            help_offer_items.append(
                {
                    "object": offer,
                    "locked": True,
                    "policy": policy,
                    "requestable": (
                            policy is not None
                            and policy.visibility
                            == PrivacyPolicy.Visibility.REQUEST_ONLY
                    ),
                }
            )

        biography = (
            Biography.objects
            .filter(person=person)
            .first()
        )

        if biography is not None:
            can_view = can_view_resource(
                request.user,
                person,
                PrivacyPolicy.ResourceType.BIOGRAPHY,
                biography.id,
            )

            show_existence = can_see_resource_existence(
                request.user,
                person,
                PrivacyPolicy.ResourceType.BIOGRAPHY,
                biography.id,
            )

            policy = get_policy(
                PrivacyPolicy.ResourceType.BIOGRAPHY,
                biography.id,
            )

            source_links = list(
                SourceLink.objects
                .filter(
                    resource_type=(
                        SourceLink.ResourceType.BIOGRAPHY
                    ),
                    object_id=biography.id,
                )
                .select_related("source")
            )

            if can_view:
                biography_item = {
                    "object": biography,
                    "locked": False,
                    "source_links": source_links,
                }

            elif show_existence:
                biography_item = {
                    "object": biography,
                    "locked": True,
                    "policy": policy,
                    "requestable": (
                            policy is not None
                            and policy.visibility
                            == PrivacyPolicy.Visibility.REQUEST_ONLY
                    ),
                }

    for event in person.life_events.all():
        can_view = can_view_resource(
            request.user,
            person,
            PrivacyPolicy.ResourceType.LIFE_EVENT,
            event.id,
        )

        show_existence = can_see_resource_existence(
            request.user,
            person,
            PrivacyPolicy.ResourceType.LIFE_EVENT,
            event.id,
        )

        policy = get_policy(
            PrivacyPolicy.ResourceType.LIFE_EVENT,
            event.id,
        )

        source_links = list(
            SourceLink.objects
            .filter(
                resource_type=(
                    SourceLink.ResourceType.LIFE_EVENT
                ),
                object_id=event.id,
            )
            .select_related("source")
        )

        if can_view:
            life_event_items.append(
                {
                    "object": event,
                    "locked": False,
                    "source_links": source_links,
                }
            )

        elif show_existence:
            life_event_items.append(
                {
                    "object": event,
                    "locked": True,
                    "policy": policy,
                    "requestable": (
                            policy is not None
                            and policy.visibility
                            == PrivacyPolicy.Visibility.REQUEST_ONLY
                    ),
                }
            )


    return render(
        request,
        "family/person_detail.html",
        {
            "person": person,

            "parents": parents,
            "children": children,
            "spouses": spouses,
            "siblings": siblings,

            "employment_items": employment_items,
            "education_items": education_items,
            "skill_items": skill_items,
            "help_offer_items": help_offer_items,

            "biography_item": biography_item,
            "life_event_items": life_event_items,

            "can_manage": can_manage,
            "pending_access_requests_count": pending_access_requests_count,
        },
    )

@staff_member_required
@transaction.atomic
def add_relative(request, person_id):
    person = get_object_or_404(
        Person,
        id=person_id,
    )

    if request.method == "POST":
        form = AddRelativeForm(
            request.POST,
            current_person=person,
        )

        if form.is_valid():
            relative = form.cleaned_data[
                "existing_person"
            ]

            if relative is None:
                relative = Person.objects.create(
                    first_name=form.cleaned_data[
                        "first_name"
                    ],
                    middle_name=form.cleaned_data[
                        "middle_name"
                    ],
                    last_name=form.cleaned_data[
                        "last_name"
                    ],
                    birth_date=form.cleaned_data[
                        "birth_date"
                    ],
                    profile_status=(
                        Person.ProfileStatus.UNCLAIMED
                    ),
                )

            relation_type = form.cleaned_data[
                "relation_type"
            ]

            if relation_type == "PARENT":
                Relationship.objects.get_or_create(
                    person_a=relative,
                    person_b=person,
                    relationship_type=(
                        Relationship.Type.PARENT_CHILD
                    ),
                    defaults={
                        "status":
                            Relationship.Status.VERIFIED,
                        "created_by":
                            request.user,
                    },
                )

            elif relation_type == "CHILD":
                Relationship.objects.get_or_create(
                    person_a=person,
                    person_b=relative,
                    relationship_type=(
                        Relationship.Type.PARENT_CHILD
                    ),
                    defaults={
                        "status":
                            Relationship.Status.VERIFIED,
                        "created_by":
                            request.user,
                    },
                )

            elif relation_type == "SPOUSE":
                already_exists = (
                    Relationship.objects.filter(
                        person_a=person,
                        person_b=relative,
                        relationship_type=(
                            Relationship.Type.SPOUSE
                        ),
                    ).exists()
                    or
                    Relationship.objects.filter(
                        person_a=relative,
                        person_b=person,
                        relationship_type=(
                            Relationship.Type.SPOUSE
                        ),
                    ).exists()
                )

                if not already_exists:
                    Relationship.objects.create(
                        person_a=person,
                        person_b=relative,
                        relationship_type=(
                            Relationship.Type.SPOUSE
                        ),
                        status=(
                            Relationship.Status.VERIFIED
                        ),
                        created_by=request.user,
                    )

            return redirect(
                "family:person_detail",
                person_id=person.id,
            )

    else:
        form = AddRelativeForm(
            current_person=person,
        )

    return render(
        request,
        "family/add_relative.html",
        {
            "person": person,
            "form": form,
        },
    )

@login_required
def my_profile(request):
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
        return render(
            request,
            "family/no_profile.html",
        )

    return redirect(
        "family:person_detail",
        person_id=ownership.person.id,
    )