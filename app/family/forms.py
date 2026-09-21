from django import forms
from django.utils import timezone
import uuid

from .models import Person, Relationship, RelativeProposal
from .relationships import validate_ancestry


class RelativeProposalForm(forms.ModelForm):
    submission_id = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)

    class Meta:
        model = RelativeProposal
        fields = ["relation_type", "first_name", "middle_name", "last_name", "birth_date",
                  "is_living", "death_date", "biography", "invitation_email"]
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"}),
                   "death_date": forms.DateInput(attrs={"type": "date"}),
                   "biography": forms.Textarea(attrs={"rows": 5})}

    def clean(self):
        data = super().clean()
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
    email = forms.EmailField(label="Адрес приглашения", required=False)
    send_invitation = forms.BooleanField(label="Отправить приглашение после одобрения", required=False)
    comment = forms.CharField(label="Комментарий к решению", required=False, max_length=2000,
                              widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        data = super().clean()
        if data.get("decision") == "approve" and data.get("send_invitation") and not data.get("email"):
            self.add_error("email", "Укажите адрес для приглашения или снимите отметку отправки.")
        return data


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
