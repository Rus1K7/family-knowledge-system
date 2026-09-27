from collections import deque

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import redirect

from audit.models import AuditEvent
from audit.services import log_audit_event

from .models import Person, ProfileOwnership, Relationship
from .tree_data import build_family_groups, graph_data
from .portraits import portrait_url
from django.views.decorators.cache import never_cache
from .tree_presentation import kinship_labels
from .focused_tree import arrange_from_person
from .journey_navigation import back_context
from django.urls import reverse

from .permissions import (
    can_manage_relationships,
    can_manage_person,
    is_family_member,
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
    Source,
    SourceLink,
    Verification,
    MediaAsset,
)
from heritage.permissions import (
    can_verify_heritage,
    prepare_source_documents,
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
    for start_person_id in sorted(person_ids):

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
def requests_home(request):
    if not (is_system_admin(request.user) or is_family_member(request.user)):
        raise PermissionDenied("Доступ к семейному пространству не подтверждён.")
    return render(request, "family/requests.html")


@login_required
def family_home(request):
    if not (is_system_admin(request.user) or is_family_member(request.user)):
        raise PermissionDenied("Доступ к семейному пространству не подтверждён.")
    query = request.GET.get("q", "").strip()[:150]
    people = Person.objects.order_by("last_name", "first_name", "id")
    for word in query.split():
        people = people.filter(
            Q(first_name__icontains=word) | Q(last_name__icontains=word)
            | Q(middle_name__icontains=word)
        )
    own_id = ProfileOwnership.objects.filter(
        user=request.user, status=ProfileOwnership.Status.CONFIRMED,
    ).values_list("person_id", flat=True).first()
    return render(request, "family/directory.html", {
        "page_obj": Paginator(people, 24).get_page(request.GET.get("page")),
        "query": query, "own_person_id": own_id,
        "can_admin": is_system_admin(request.user),
    })


@login_required
@never_cache
def family_tree(request):
    if not (is_system_admin(request.user) or is_family_member(request.user)):
        raise PermissionDenied("Доступ к семейному пространству не подтверждён.")
    persons = list(Person.objects.select_related("portrait", "portrait__person").order_by("last_name", "first_name", "id"))
    relationships = list(Relationship.objects.filter(status=Relationship.Status.VERIFIED)
        .select_related("person_a", "person_b").prefetch_related("periods"))
    levels, conflicts = build_generation_levels(persons, relationships)
    groups, extra_links = build_family_groups(persons, relationships)
    focus_id = request.GET.get("person", "")
    focus = next((p for p in persons if str(p.pk) == focus_id), None)
    # Selection highlights a person; it never removes anyone from the common graph.
    nodes, edges, connectors = graph_data(persons, groups, extra_links, levels,
                                         {group["id"] for group in groups})
    root_id = request.GET.get('root') or focus_id
    focused_person = next((p for p in persons if str(p.pk) == root_id), None)
    focused_view = bool(focused_person and request.GET.get('scope') == 'person')
    branches = arrange_from_person(nodes, connectors, extra_links, root_id) if focused_view else []
    person_by_id = {str(p.pk): p for p in persons}
    kinship = kinship_labels(persons, relationships)
    for node in nodes:
        if node["kind"] == "family":
            node["title"] = node["label"]
            node["label"] = ""
        elif node["kind"] == "person":
            node["add_url"] = reverse("family:add_relative", args=[node["id"]])
            node["propose_url"] = reverse("family:propose_person", args=[node["id"]])
            person = person_by_id[node["id"]]
            born = str(person.birth_date.year) if person.birth_date else ""
            died = str(person.death_date.year) if person.death_date else ""
            node.update(portrait_url=portrait_url(request.user, person), relatives=kinship[node['id']],
                        first_name=person.first_name, middle_name=person.middle_name,
                        last_name=person.last_name, is_living=person.is_living,
                        initials=(person.first_name[:1] + (person.last_name[:1] or person.middle_name[:1])).upper(),
                        life_label=(f"{born or '?'}–{died}" if died else
                                    (f"{born} · память" if born and not person.is_living else born)))
    return render(request, "family/home.html", {
        "nodes": nodes, "edges": edges, "connectors": connectors,
        "family_groups": groups, "extra_links": extra_links, "people": persons,
        "focus": focus, "focus_id": str(focus.pk) if focus else "",
        "generation_conflicts": conflicts, "person_count": len(persons),
        "can_admin": can_manage_relationships(request.user),
        "focused_view": focused_view, "focus_branches": branches,
        "focused_person": focused_person if focused_view else None,
    })

@login_required
@never_cache
def person_detail(request, person_id):
    if not (
        is_system_admin(request.user)
        or is_family_member(request.user)
    ):
        raise PermissionDenied(
            "Доступ к семейному пространству не подтверждён."
        )

    person = get_object_or_404(
        Person,
        id=person_id,
    )
    can_verify = can_verify_heritage(
        request.user
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
    couple_histories = []
    seen_partners = set()
    for union in list(relationships_from) + list(relationships_to):
        if union.relationship_type in {Relationship.Type.SPOUSE, Relationship.Type.PARTNER} and union.status == Relationship.Status.VERIFIED:
            other = union.person_b if union.person_a_id == person.pk else union.person_a
            if other.pk not in seen_partners:
                seen_partners.add(other.pk)
                couple_histories.append({"person": other, "relationship": union})

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

    def log_granted_resource_view(
        resource_type,
        object_id,
        policy,
    ):
        if (
            can_manage
            or policy is None
            or policy.visibility not in {
                PrivacyPolicy.Visibility.SELECTED_USERS,
                PrivacyPolicy.Visibility.REQUEST_ONLY,
            }
        ):
            return

        log_audit_event(
            actor=request.user,
            action=AuditEvent.Action.VIEW_PRIVATE_RESOURCE,
            person=person,
            resource_type=resource_type,
            object_id=object_id,
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
    media_items = []

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
            log_granted_resource_view(
                PrivacyPolicy.ResourceType.EMPLOYMENT,
                employment.id,
                policy,
            )
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
            log_granted_resource_view(
                PrivacyPolicy.ResourceType.EDUCATION,
                education.id,
                policy,
            )
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
            log_granted_resource_view(
                PrivacyPolicy.ResourceType.SKILL,
                skill.id,
                policy,
            )
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
            log_granted_resource_view(
                PrivacyPolicy.ResourceType.HELP_OFFER,
                offer.id,
                policy,
            )
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


    # -----------------------------
    # BIOGRAPHY
    # -----------------------------

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
                source__status=Source.Status.ACTIVE,
            )
            .select_related("source__document__person")
        )

        verification = (
            Verification.objects
            .filter(
                resource_type=(
                    Verification.ResourceType.BIOGRAPHY
                ),
                object_id=biography.id,
            )
            .select_related("reviewed_by")
            .first()
        )

        if can_view:
            log_granted_resource_view(
                PrivacyPolicy.ResourceType.BIOGRAPHY,
                biography.id,
                policy,
            )
            biography_item = {
                "object": biography,
                "locked": False,
                "source_links": prepare_source_documents(request.user, source_links),
                "verification": verification,
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


    # -----------------------------
    # LIFE EVENTS
    # -----------------------------

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
                source__status=Source.Status.ACTIVE,
            )
            .select_related("source__document__person")
        )

        verification = (
            Verification.objects
            .filter(
                resource_type=(
                    Verification.ResourceType.LIFE_EVENT
                ),
                object_id=event.id,
            )
            .select_related("reviewed_by")
            .first()
        )

        if can_view:
            log_granted_resource_view(
                PrivacyPolicy.ResourceType.LIFE_EVENT,
                event.id,
                policy,
            )
            life_event_items.append(
                {
                    "object": event,
                    "locked": False,
                    "source_links": prepare_source_documents(request.user, source_links),
                    "verification": verification,
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

    # -----------------------------
    # MEDIA
    # -----------------------------

    for media_asset in (
        person.media_assets
        .all()
        .order_by("-created_at")
    ):
        if media_asset.status == MediaAsset.Status.ARCHIVED:
            continue

        # Неодобренные файлы видит только
        # владелец профиля или администратор.
        if (
            media_asset.status
            != MediaAsset.Status.APPROVED
            and not can_manage
            and media_asset.uploaded_by_id != request.user.pk
            and not can_manage_relationships(request.user)
        ):
            continue

        from heritage.permissions import can_view_media
        can_view = can_view_media(request.user, media_asset)

        show_existence = can_see_resource_existence(
            request.user,
            person,
            PrivacyPolicy.ResourceType.MEDIA_ASSET,
            media_asset.id,
        )

        policy = get_policy(
            PrivacyPolicy.ResourceType.MEDIA_ASSET,
            media_asset.id,
        )

        if can_view:
            media_items.append(
                {
                    "object": media_asset,
                    "locked": False,
                }
            )

        elif show_existence:
            media_items.append(
                {
                    "object": media_asset,
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
            **back_context(request, reverse("family:home")),
            "person": person,

            "parents": parents,
            "portrait_url": portrait_url(request.user, person),
            "children": children,
            "spouses": list({p.pk: p for p in spouses}.values()),
            "couple_histories": couple_histories,
            "siblings": siblings,

            "employment_items": employment_items,
            "education_items": education_items,
            "skill_items": skill_items,
            "help_offer_items": help_offer_items,

            "biography_item": biography_item,
            "life_event_items": life_event_items,
            "media_items": media_items,

            "can_manage": can_manage,
            "pending_access_requests_count": pending_access_requests_count,
            "can_verify": can_verify,
            "can_admin": is_system_admin(request.user),
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
