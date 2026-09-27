from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import Q

from .models import Relationship


def lock_relationship_graph():
    """Call inside a transaction before validating or changing the graph."""
    with connection.cursor() as cursor:
        cursor.execute("LOCK TABLE family_relationship IN SHARE ROW EXCLUSIVE MODE")


def validate_ancestry(parent_id, child_id, *, exclude_id=None):
    children = {}
    edges = Relationship.objects.filter(relationship_type__in=[
        Relationship.Type.PARENT_CHILD,
        Relationship.Type.ADOPTIVE_PARENT,
    ])
    if exclude_id is not None:
        edges = edges.exclude(pk=exclude_id)
    for ancestor_id, descendant_id in edges.values_list("person_a_id", "person_b_id"):
        children.setdefault(ancestor_id, []).append(descendant_id)
    pending = [child_id]
    visited = set()
    while pending:
        current = pending.pop()
        if current == parent_id:
            raise ValidationError(
                "Эта связь создаёт цикл: человек не может быть своим предком."
            )
        if current not in visited:
            visited.add(current)
            pending.extend(children.get(current, []))


def couple_relationships(a, b):
    """One pair can have legacy spouse/partner edges; keep all its history together."""
    return Relationship.objects.filter(
        Q(person_a_id=a, person_b_id=b) | Q(person_a_id=b, person_b_id=a),
        relationship_type__in=[Relationship.Type.SPOUSE, Relationship.Type.PARTNER],
    ).order_by("id")
