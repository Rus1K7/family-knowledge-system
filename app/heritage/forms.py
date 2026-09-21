from pathlib import Path

from django import forms
from django.db.models import Q

from .models import (
    Biography,
    LifeEvent,
    MediaAsset,
    Source,
    SourceLink,
    Verification,
)
from .permissions import available_source_documents
from .file_validation import UnsafeMediaError, validate_media_content


ALLOWED_MEDIA_EXTENSIONS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
    "application/pdf": {".pdf"},
}


def detect_media_content_type(header):
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    if (
        len(header) >= 12
        and header.startswith(b"RIFF")
        and header[8:12] == b"WEBP"
    ):
        return "image/webp"

    if header.startswith(b"%PDF-"):
        return "application/pdf"

    return None

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
    def __init__(self, *args, user=None, person=None, lock_document=False, **kwargs):
        super().__init__(*args, **kwargs)
        documents = available_source_documents(user, person)
        if lock_document:
            documents = documents.select_for_update()
        self.fields["document"].queryset = documents
        self.fields["document"].help_text = (
            "Необязательно. Одобренный PDF этого профиля. "
            "Доступ к файлу определяется его настройками приватности; "
            "название и описание источника видны вместе с биографией или событием."
        )

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("document") is not None
            and cleaned_data.get("source_type") != Source.SourceType.DOCUMENT
        ):
            self.add_error("source_type", "Для PDF выберите тип источника «Документ».")
        return cleaned_data

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
            "document",
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


class SourceEditForm(forms.ModelForm):
    def clean_source_type(self):
        source_type = self.cleaned_data["source_type"]
        if self.instance.document_id is not None and source_type != Source.SourceType.DOCUMENT:
            raise forms.ValidationError("Для PDF выберите тип источника «Документ».")
        return source_type

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
    def __init__(self, *args, user=None, person=None, lock_source=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.documents = available_source_documents(user, person)
        self.lock_source = lock_source
        sources = self.fields["source"].queryset.filter(
            Q(document__isnull=True) | Q(document__in=self.documents)
        )
        if lock_source:
            sources = sources.select_for_update(of=("self",))
        self.fields["source"].queryset = sources

    def clean_source(self):
        source = self.cleaned_data["source"]
        if self.lock_source and source.document_id is not None:
            # Lock and recheck the document after locking the source: it may
            # have been archived while the submitted form was being validated.
            if not self.documents.select_for_update().filter(
                id=source.document_id,
            ).exists():
                raise forms.ValidationError("Документ больше недоступен для привязки.")
        return source

    source = forms.ModelChoiceField(
        label="Источник",
        queryset=Source.objects.filter(
            status=Source.Status.ACTIVE,
        ),
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

        declared_content_type = getattr(
            uploaded_file,
            "content_type",
            "",
        ).split(";", 1)[0].strip().lower()

        if declared_content_type not in ALLOWED_MEDIA_EXTENSIONS:
            raise forms.ValidationError(
                "Разрешены JPG, PNG, WebP и PDF."
            )

        uploaded_file.seek(0)
        header = uploaded_file.read(16)
        uploaded_file.seek(0)

        detected_content_type = detect_media_content_type(
            header
        )

        if detected_content_type != declared_content_type:
            raise forms.ValidationError(
                "Содержимое файла не соответствует заявленному формату."
            )

        extension = Path(uploaded_file.name).suffix.lower()

        if extension not in ALLOWED_MEDIA_EXTENSIONS[detected_content_type]:
            raise forms.ValidationError(
                "Расширение файла не соответствует его формату."
            )

        try:
            validate_media_content(uploaded_file, detected_content_type)
        except UnsafeMediaError as error:
            raise forms.ValidationError(str(error)) from error

        uploaded_file.verified_content_type = (
            detected_content_type
        )

        return uploaded_file

    def clean(self):
        cleaned_data = super().clean()
        media_type = cleaned_data.get("media_type")
        uploaded_file = cleaned_data.get("file")

        if uploaded_file is None:
            return cleaned_data

        content_type = getattr(
            uploaded_file,
            "verified_content_type",
            "",
        )

        if (
            media_type == MediaAsset.MediaType.PHOTO
            and not content_type.startswith("image/")
        ):
            self.add_error(
                "file",
                "Для типа «Фотография» выберите изображение.",
            )

        if (
            media_type == MediaAsset.MediaType.DOCUMENT
            and content_type != "application/pdf"
        ):
            self.add_error(
                "file",
                "Для типа «Документ» выберите PDF-файл.",
            )

        return cleaned_data


class MediaAssetMetadataForm(forms.ModelForm):
    class Meta:
        model = MediaAsset
        fields = [
            "title",
            "description",
        ]

        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 4},
            ),
        }
