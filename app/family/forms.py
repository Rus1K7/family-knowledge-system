from django import forms
from django.utils import timezone
import uuid

from .models import Person, Relationship, RelativeProposal, PartnershipPeriod
from .relationships import validate_ancestry, couple_relationships


class RelativeProposalForm(forms.ModelForm):
    submission_id = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)

    class Meta:
        model = RelativeProposal
        fields = ["relation_type", "existing_person", "first_name", "middle_name", "last_name", "birth_date",
                  "is_living", "death_date", "biography", "invitation_email"]
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"}),
                   "death_date": forms.DateInput(attrs={"type": "date"}),
                   "biography": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, mode="new", anchor=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode, self.anchor = mode, anchor
        self.fields["relation_type"].label = "Кем этот человек приходится выбранному родственнику"
        if mode == "existing":
            for name in ("first_name", "middle_name", "last_name", "birth_date", "is_living",
                         "death_date", "biography", "invitation_email"):
                self.fields.pop(name)
            people = Person.objects.exclude(profile_status=Person.ProfileStatus.ARCHIVED)
            if user is not None:
                from privacy.person_visibility import visible_people
                people = visible_people(user, people)
            if anchor:
                people = people.exclude(pk=anchor.pk)
            self.fields["existing_person"].queryset = people.order_by("last_name", "first_name")
            self.fields["existing_person"].required = True
        else:
            self.fields.pop("existing_person")

    def clean(self):
        data = super().clean()
        if self.mode == "existing":
            relative = data.get("existing_person")
            if relative and self.anchor and data.get("relation_type") in {"PARENT", "CHILD"}:
                parent, child = (relative, self.anchor) if data["relation_type"] == "PARENT" else (self.anchor, relative)
                validate_ancestry(parent.pk, child.pk)
            if relative:
                self.instance.first_name = relative.first_name
                self.instance.middle_name = relative.middle_name
                self.instance.last_name = relative.last_name
                self.instance.is_living = relative.is_living
            return data
        today = timezone.localdate()
        birth, death = data.get("birth_date"), data.get("death_date")
        if birth and birth > today:
            self.add_error("birth_date", "Дата рождения не может быть в будущем.")
        if death and (death > today or (birth and death < birth)):
            self.add_error("death_date", "Проверьте дату смерти: она не может быть раньше рождения или в будущем.")
        if data.get("is_living") and death:
            self.add_error("death_date", "Для живого человека дата смерти не указывается.")
        if not data.get("is_living") and data.get("invitation_email"):
            self.add_error("invitation_email", "Приглашение возможно только для живого человека.")
        data["invitation_email"] = data.get("invitation_email", "").lower()
        return data


class RelativeReviewForm(forms.Form):
    decision = forms.ChoiceField(choices=[("approve", "Одобрить"), ("reject", "Отклонить")])
    comment = forms.CharField(label="Комментарий к решению", required=False, max_length=2000,
                              widget=forms.Textarea(attrs={"rows": 3}))


class AddRelativeForm(forms.Form):
    class RelationType:
        PARENT = "PARENT"
        CHILD = "CHILD"
        SPOUSE = "SPOUSE"

    RELATION_CHOICES = [
        (RelationType.PARENT, "Родитель"),
        (RelationType.CHILD, "Ребёнок"),
        (RelationType.SPOUSE, "Супруг / супруга"),
        ("PARTNER", "Партнёр"),
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


class PartnershipPeriodForm(forms.ModelForm):
    class Meta:
        model = PartnershipPeriod
        fields = ["kind", "state", "start_year", "end_year"]
        help_texts = {"start_year": "Если год неизвестен, оставьте поле пустым.",
                      "end_year": "Развод или расставание не изменяет родительские связи."}

    def clean(self):
        data = super().clean()
        if self.instance.relationship_id and all(k in data for k in ("kind", "state", "start_year", "end_year")):
            relation = self.instance.relationship
            periods = PartnershipPeriod.objects.filter(relationship__in=couple_relationships(
                relation.person_a_id, relation.person_b_id)).exclude(pk=self.instance.pk)
            if data["state"] == "CURRENT" and periods.filter(state="CURRENT").exists():
                raise forms.ValidationError("У этой пары уже есть текущий период. Исправьте его или укажите завершение перед добавлением нового.")
            if periods.filter(**{k: data[k] for k in ("kind", "state", "start_year", "end_year")}).exists():
                raise forms.ValidationError("Такая запись уже есть. Исправьте существующую запись вместо добавления копии.")
        return data


class RelationshipAdminForm(forms.ModelForm):
    class Meta:
        model = Relationship
        fields = ["person_a", "person_b", "relationship_type", "status"]

    def clean(self):
        data = super().clean()
        a, b, kind = data.get("person_a"), data.get("person_b"), data.get("relationship_type")
        if not a or not b or not kind:
            return data
        if self.instance.pk and self.instance.periods.exists():
            previous = Relationship.objects.get(pk=self.instance.pk)
            if {a.pk, b.pk} != {previous.person_a_id, previous.person_b_id} or kind not in {Relationship.Type.SPOUSE, Relationship.Type.PARTNER}:
                raise forms.ValidationError("У связи есть история отношений. Нельзя перенести её на других людей или изменить на родительскую связь.")
        if a.pk == b.pk:
            raise forms.ValidationError("Нельзя связать человека с самим собой.")
        existing = (couple_relationships(a.pk, b.pk) if kind in {Relationship.Type.SPOUSE, Relationship.Type.PARTNER}
                    else Relationship.objects.filter(relationship_type=kind)).exclude(pk=self.instance.pk)
        duplicate = existing.filter(person_a=a, person_b=b).exists()
        if kind in {Relationship.Type.SPOUSE, Relationship.Type.PARTNER, Relationship.Type.SIBLING}:
            duplicate = duplicate or existing.filter(person_a=b, person_b=a).exists()
        if duplicate:
            raise forms.ValidationError("Такая родственная связь уже существует.")
        if kind in {Relationship.Type.PARENT_CHILD, Relationship.Type.ADOPTIVE_PARENT}:
            validate_ancestry(a.pk, b.pk, exclude_id=self.instance.pk)
        return data
