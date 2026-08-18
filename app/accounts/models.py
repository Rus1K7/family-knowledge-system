import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

class User(AbstractUser):
    class Status(models.TextChoices):
        INVITED = "INVITED", _("Приглашён")
        ACTIVE = "ACTIVE", _("Активен")
        SUSPENDED = "SUSPENDED", _("Приостановлен")
        DISABLED = "DISABLED", _("Отключён")

    class SystemRole(models.TextChoices):
        FAMILY_MEMBER = "FAMILY_MEMBER", _("Член семьи")
        FAMILY_HISTORIAN = "FAMILY_HISTORIAN", _("Семейный историк")
        SYSTEM_ADMIN = "SYSTEM_ADMIN", _("Системный администратор")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    email = models.EmailField(
        unique=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    system_role = models.CharField(
        max_length=30,
        choices=SystemRole.choices,
        default=SystemRole.FAMILY_MEMBER,
    )

    mfa_enabled = models.BooleanField(
        default=False,
    )

    disabled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.email or self.username


from django.conf import settings
from django.utils import timezone

from family.models import Person


class Invitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Ожидает")
        ACCEPTED = "ACCEPTED", _("Принято")
        CANCELLED = "CANCELLED", _("Отменено")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="invitations",
        verbose_name=_("Человек"),
    )

    email = models.EmailField(
        _("Email"),
    )

    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invitations",
        verbose_name=_("Создал"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    expires_at = models.DateTimeField(
        _("Действует до"),
    )

    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    def is_valid(self):
        return (
            self.status == self.Status.PENDING
            and self.expires_at > timezone.now()
        )

    def __str__(self):
        return f"{self.person} → {self.email}"