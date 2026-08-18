from django import forms
from django.contrib.auth import get_user_model

from family.models import ProfileOwnership

from .models import PrivacyPolicy


User = get_user_model()


class PrivacyPolicyForm(forms.ModelForm):
    class Meta:
        model = PrivacyPolicy

        fields = [
            "visibility",
            "show_existence",
        ]


class AccessRequestForm(forms.Form):
    reason = forms.CharField(
        label="Почему вам нужен доступ?",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Коротко укажите причину запроса",
            }
        ),
    )

class SelectedUserGrantForm(forms.Form):
    user = forms.ModelChoiceField(
        label="Разрешить доступ пользователю",
        queryset=User.objects.none(),
    )

    def __init__(
        self,
        *args,
        current_user=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        family_user_ids = (
            ProfileOwnership.objects
            .filter(
                status=ProfileOwnership.Status.CONFIRMED,
            )
            .values_list(
                "user_id",
                flat=True,
            )
        )

        queryset = User.objects.filter(
            id__in=family_user_ids,
            is_active=True,
        )

        if current_user is not None:
            queryset = queryset.exclude(
                id=current_user.id,
            )

        self.fields["user"].queryset = (
            queryset.order_by(
                "last_name",
                "first_name",
                "username",
            )
        )