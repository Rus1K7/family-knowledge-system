from django import forms

from .models import (
    Biography,
    LifeEvent,
    Source,
    SourceLink,
)

class BiographyForm(forms.ModelForm):
    class Meta:
        model = Biography

        fields = [
            "text",
        ]

        widgets = {
            "text": forms.Textarea(
                attrs={
                    "rows": 12,
                }
            ),
        }


class LifeEventForm(forms.ModelForm):
    class Meta:
        model = LifeEvent

        fields = [
            "event_type",
            "title",
            "start_date",
            "end_date",
            "date_precision",
            "place",
            "description",
        ]

        widgets = {
            "start_date": forms.DateInput(
                attrs={"type": "date"},
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date"},
            ),
            "description": forms.Textarea(
                attrs={"rows": 5},
            ),
        }




class SourceCreateForm(forms.ModelForm):
    relation_type = forms.ChoiceField(
        label="Роль источника",
        choices=SourceLink.RelationType.choices,
        initial=SourceLink.RelationType.SUPPORTS,
    )

    link_note = forms.CharField(
        label="Комментарий к связи",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3}
        ),
    )

    class Meta:
        model = Source

        fields = [
            "source_type",
            "title",
            "author",
            "source_date",
            "url",
            "citation",
            "notes",
        ]

        widgets = {
            "source_date": forms.DateInput(
                attrs={"type": "date"},
            ),
            "citation": forms.Textarea(
                attrs={"rows": 4},
            ),
            "notes": forms.Textarea(
                attrs={"rows": 4},
            ),
        }


class ExistingSourceLinkForm(forms.Form):
    source = forms.ModelChoiceField(
        label="Источник",
        queryset=Source.objects.all(),
    )

    relation_type = forms.ChoiceField(
        label="Роль источника",
        choices=SourceLink.RelationType.choices,
        initial=SourceLink.RelationType.SUPPORTS,
    )

    note = forms.CharField(
        label="Комментарий к связи",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3}
        ),
    )