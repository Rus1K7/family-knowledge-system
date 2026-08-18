import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from family.models import Person


class PrivacyPolicy(models.Model):
    class ResourceType(models.TextChoices):
        EMPLOYMENT = "EMPLOYMENT", _("Место работы")
        EDUCATION = "EDUCATION", _("Образование")
        SKILL = "SKILL", _("Навык")
        HELP_OFFER = "HELP_OFFER", _("Предложение помощи")
        BIOGRAPHY = "BIOGRAPHY", _("Биография")
        LIFE_EVENT = "LIFE_EVENT", _("Событие жизни")

    class Visibility(models.TextChoices):
        FAMILY = "FAMILY", _("Вся семья")
        SELECTED_USERS = "SELECTED_USERS", _("Выбранные пользователи")
        REQUEST_ONLY = "REQUEST_ONLY", _("Только по запросу")
        OWNER_ONLY = "OWNER_ONLY", _("Только владелец")
        PRIVATE = "PRIVATE", _("Скрыто")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="privacy_policies",
        verbose_name=_("Владелец данных"),
    )

    resource_type = models.CharField(
        _("Тип данных"),
        max_length=30,
        choices=ResourceType.choices,
    )

    object_id = models.UUIDField(
        _("ID записи"),
    )

    visibility = models.CharField(
        _("Видимость"),
        max_length=30,
        choices=Visibility.choices,
        default=Visibility.FAMILY,
    )

    show_existence = models.BooleanField(
        _("Показывать существование скрытых данных"),
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Политика приватности")
        verbose_name_plural = _("Политики приватности")

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "resource_type",
                    "object_id",
                ],
                name="unique_privacy_policy_per_resource",
            ),
        ]

    def __str__(self):
        return (
            f"{self.person}: "
            f"{self.get_resource_type_display()} — "
            f"{self.get_visibility_display()}"
        )


class AccessGrant(models.Model):
    class Action(models.TextChoices):
        VIEW = "VIEW", _("Просмотр")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    policy = models.ForeignKey(
        PrivacyPolicy,
        on_delete=models.CASCADE,
        related_name="grants",
        verbose_name=_("Политика"),
    )

    grantee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="privacy_grants",
        verbose_name=_("Кому разрешено"),
    )

    action = models.CharField(
        _("Действие"),
        max_length=20,
        choices=Action.choices,
        default=Action.VIEW,
    )

    valid_until = models.DateTimeField(
        _("Действует до"),
        null=True,
        blank=True,
    )

    revoked_at = models.DateTimeField(
        _("Отозвано"),
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _("Разрешение доступа")
        verbose_name_plural = _("Разрешения доступа")

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "policy",
                    "grantee",
                    "action",
                ],
                condition=models.Q(
                    revoked_at__isnull=True
                ),
                name="unique_active_access_grant",
            ),
        ]

    def __str__(self):
        return f"{self.grantee} → {self.policy}"


class AccessRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Ожидает рассмотрения")
        APPROVED = "APPROVED", _("Одобрено")
        REJECTED = "REJECTED", _("Отклонено")
        CANCELLED = "CANCELLED", _("Отменено")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    policy = models.ForeignKey(
        PrivacyPolicy,
        on_delete=models.CASCADE,
        related_name="access_requests",
        verbose_name=_("Политика"),
    )

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="access_requests",
        verbose_name=_("Запросил"),
    )

    reason = models.TextField(
        _("Причина запроса"),
        blank=True,
    )

    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_access_requests",
        verbose_name=_("Рассмотрел"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Запрос доступа")
        verbose_name_plural = _("Запросы доступа")

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "policy",
                    "requester",
                ],
                condition=models.Q(
                    status="PENDING"
                ),
                name="unique_pending_access_request",
            ),
        ]

    def __str__(self):
        return (
            f"{self.requester} → "
            f"{self.policy} ({self.status})"
        )