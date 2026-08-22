from django import forms

from .models import (
    Biography,
    LifeEvent,
    MediaAsset,
    Source,
    SourceLink,
    Verification,
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

class VerificationForm(forms.ModelForm):
    class Meta:
        model = Verification

        fields = [
            "status",
            "comment",
        ]

        widgets = {
            "comment": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),
        }

class MediaAssetUploadForm(forms.ModelForm):
    class Meta:
        model = MediaAsset

        fields = [
            "media_type",
            "title",
            "description",
            "file",
        ]

        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),
        }

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]

        max_size = 20 * 1024 * 1024

        if uploaded_file.size > max_size:
            raise forms.ValidationError(
                "Размер файла не должен превышать 20 МБ."
            )

        allowed_content_types = {
            "image/jpeg",
            "image/png",
            "image/webp",
            "application/pdf",
        }

        content_type = getattr(
            uploaded_file,
            "content_type",
            "",
        )

        if content_type not in allowed_content_types:
            raise forms.ValidationError(
                "Разрешены JPG, PNG, WebP и PDF."
            )

        return uploaded_file