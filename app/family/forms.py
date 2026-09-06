from django import forms

from .models import Person, Relationship
from .relationships import validate_ancestry


class AddRelativeForm(forms.Form):
    class RelationType:
        PARENT = "PARENT"
        CHILD = "CHILD"
        SPOUSE = "SPOUSE"

    RELATION_CHOICES = [
        (RelationType.PARENT, "Родитель"),
        (RelationType.CHILD, "Ребёнок"),
        (RelationType.SPOUSE, "Супруг / супруга"),
    ]

    relation_type = forms.ChoiceField(
        label="Кем приходится",
        choices=RELATION_CHOICES,
    )

    existing_person = forms.ModelChoiceField(
        label="Выбрать существующего человека",
        queryset=Person.objects.none(),
        required=False,
    )

    first_name = forms.CharField(
        label="Имя нового человека",
        max_length=150,
        required=False,
    )

    middle_name = forms.CharField(
        label="Отчество",
        max_length=150,
        required=False,
    )

    last_name = forms.CharField(
        label="Фамилия",
        max_length=150,
        required=False,
    )

    birth_date = forms.DateField(
        label="Дата рождения",
        required=False,
        widget=forms.DateInput(
            attrs={"type": "date"}
        ),
    )

    def __init__(self, *args, current_person=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_person = current_person

        queryset = Person.objects.all()

        if current_person:
            queryset = queryset.exclude(
                id=current_person.id
            )

        self.fields["existing_person"].queryset = queryset

    def clean(self):
        cleaned_data = super().clean()

        existing = cleaned_data.get("existing_person")
        first_name = cleaned_data.get("first_name")

        if not existing and not first_name:
            raise forms.ValidationError(
                "Выберите существующего человека "
                "или укажите имя нового родственника."
            )

        relation_type = cleaned_data.get("relation_type")
        if existing and self.current_person and relation_type in {"PARENT", "CHILD"}:
            parent, child = (
                (existing, self.current_person)
                if relation_type == "PARENT"
                else (self.current_person, existing)
            )
            validate_ancestry(parent.id, child.id)

        return cleaned_data


class RelationshipAdminForm(forms.ModelForm):
    class Meta:
        model = Relationship
        fields = ["person_a", "person_b", "relationship_type", "status"]

    def clean(self):
        data = super().clean()
        a, b, kind = data.get("person_a"), data.get("person_b"), data.get("relationship_type")
        if not a or not b or not kind:
            return data
        if a.pk == b.pk:
            raise forms.ValidationError("Нельзя связать человека с самим собой.")
        existing = Relationship.objects.filter(relationship_type=kind).exclude(pk=self.instance.pk)
        duplicate = existing.filter(person_a=a, person_b=b).exists()
        if kind in {Relationship.Type.SPOUSE, Relationship.Type.PARTNER, Relationship.Type.SIBLING}:
            duplicate = duplicate or existing.filter(person_a=b, person_b=a).exists()
        if duplicate:
            raise forms.ValidationError("Такая родственная связь уже существует.")
        if kind in {Relationship.Type.PARENT_CHILD, Relationship.Type.ADOPTIVE_PARENT}:
            validate_ancestry(a.pk, b.pk, exclude_id=self.instance.pk)
        return data
