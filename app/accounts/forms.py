from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm as DjangoPasswordResetForm
from django.contrib.auth.password_validation import (
    password_validators_help_text_html,
    validate_password,
)
from django.core.exceptions import ValidationError

from family.models import ProfileOwnership

from .models import Invitation
from .login_throttle import reserve_password_reset_email

User = get_user_model()


class ActivePasswordResetForm(DjangoPasswordResetForm):
    """Keep password recovery aligned with the status-aware login backend."""

    def get_users(self, email):
        return (
            user
            for user in super().get_users(email)
            if user.status == User.Status.ACTIVE
        )

    def save(self, **kwargs):
        if reserve_password_reset_email(self.cleaned_data["email"]):
            return super().save(**kwargs)


class InvitationCreateForm(forms.ModelForm):
    identity_confirmed = forms.BooleanField(label='Я приглашаю этого родственника с его согласия и указал его почту')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .relative_invites import eligible_people
        self.fields['person'].queryset = (eligible_people(user) if user is not None
                                         else self.fields['person'].queryset.none())
        self.fields['person'].label = 'Родственник из дерева'
        self.fields['person'].empty_label = 'Выберите родственника'
        self.fields['email'].label = 'Почта родственника'
        self.fields['email'].widget.attrs.update({'autocomplete': 'email', 'inputmode': 'email'})

    class Meta:
        model = Invitation

        fields = [
            "person",
            "email",
        ]

    def clean_email(self):
        return self.cleaned_data["email"].lower()

    def clean(self):
        cleaned_data = super().clean()

        person = cleaned_data.get("person")
        if person is None:
            return cleaned_data

        if not person.is_living or person.profile_status == person.ProfileStatus.ARCHIVED:
            self.add_error("person", "Нельзя пригласить умершего человека или архивный профиль.")
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

        return cleaned_data

class InvitationAcceptForm(forms.Form):
    username = forms.CharField(
        label="Логин",
        max_length=150,
    )

    password1 = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput,
        help_text=password_validators_help_text_html(),
    )

    password2 = forms.CharField(
        label="Повторите пароль",
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, email="", **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email

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

        username = cleaned_data.get(
            "username"
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

        if password1:
            candidate_user = User(
                username=username or "",
                email=self.email,
            )

            try:
                validate_password(
                    password1,
                    user=candidate_user,
                )
            except ValidationError as error:
                self.add_error(
                    "password1",
                    error,
                )

        return cleaned_data
