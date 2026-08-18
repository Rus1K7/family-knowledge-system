from django import forms

from .models import Person


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

        return cleaned_data