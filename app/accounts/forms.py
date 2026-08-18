from django import forms
from django.contrib.auth import get_user_model

from family.models import ProfileOwnership
from privacy.models import PrivacyPolicy

from .models import Invitation
from django.utils import timezone

User = get_user_model()


class InvitationCreateForm(forms.ModelForm):
    class Meta:
        model = Invitation

        fields = [
            "person",
            "email",
        ]

    def clean(self):
        cleaned_data = super().clean()

        person = cleaned_data.get("person")
        email = cleaned_data.get("email")

        if person is None:
            return cleaned_data

        already_owned = (
            ProfileOwnership.objects
            .filter(
                person=person,
                status=ProfileOwnership.Status.CONFIRMED,
            )
            .exists()
        )

        if already_owned:
            self.add_error(
                "person",
                "У этого человека уже есть аккаунт.",
            )

        pending_invitation = (
            Invitation.objects
            .filter(
                person=person,
                status=Invitation.Status.PENDING,
                expires_at__gt=timezone.now(),
            )
            .exists()
        )

        if pending_invitation:
            self.add_error(
                "person",
                "Для этого человека уже создано активное приглашение.",
            )

        if (
            email
            and User.objects.filter(email=email).exists()
        ):
            self.add_error(
                "email",
                "Пользователь с таким email уже существует.",
            )

        return cleaned_data

class InvitationAcceptForm(forms.Form):
    username = forms.CharField(
        label="Логин",
        max_length=150,
    )

    password1 = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput,
    )

    password2 = forms.CharField(
        label="Повторите пароль",
        widget=forms.PasswordInput,
    )

    def clean_username(self):
        username = self.cleaned_data["username"]

        if User.objects.filter(
            username=username
        ).exists():
            raise forms.ValidationError(
                "Пользователь с таким логином уже существует."
            )

        return username

    def clean(self):
        cleaned_data = super().clean()

        password1 = cleaned_data.get(
            "password1"
        )

        password2 = cleaned_data.get(
            "password2"
        )

        if (
            password1
            and password2
            and password1 != password2
        ):
            self.add_error(
                "password2",
                "Пароли не совпадают.",
            )

        return cleaned_data