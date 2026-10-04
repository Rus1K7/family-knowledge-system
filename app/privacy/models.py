import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from family.models import Person


class PersonVisibility(models.Model):
    class Choice(models.TextChoices):
        UNDECIDED = 'UNDECIDED', 'Выбор не сделан'
        OPEN = 'OPEN', 'Разрешён показ родственникам'
        HIDDEN = 'HIDDEN', 'Скрыт от родственников'

    person = models.OneToOneField(Person, on_delete=models.CASCADE, primary_key=True)
    choice = models.CharField(max_length=12, choices=Choice.choices, default=Choice.UNDECIDED)
    chosen_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name='+')
    chosen_at = models.DateTimeField(null=True, blank=True)
    forced_hidden = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class PersonVisibilityException(models.Model):
    class Decision(models.TextChoices):
        ALLOW = 'ALLOW', 'Разрешить'
        DENY = 'DENY', 'Скрыть'

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='+')
    viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    decision = models.CharField(max_length=5, choices=Decision.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['person', 'viewer'], name='unique_person_visibility_viewer')]


class VisibilityLink(models.Model):
    class Kind(models.TextChoices):
        OFFER = 'OFFER', 'Предложить доступ к моему профилю'
        REQUEST = 'REQUEST', 'Попросить доступ к профилю'

    class Status(models.TextChoices):
        WAITING = 'WAITING', 'Ожидает перехода'
        CLAIMED = 'CLAIMED', 'Ожидает подтверждения владельца'
        APPROVED = 'APPROVED', 'Доступ разрешён'
        REJECTED = 'REJECTED', 'Отклонено'
        REVOKED = 'REVOKED', 'Отозвано'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name='+')
    kind = models.CharField(max_length=8, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)


class PersonHideRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Ожидает решения'
        APPROVED = 'APPROVED', 'Одобрено'
        REJECTED = 'REJECTED', 'Отклонено'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='+')
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reason = models.TextField(max_length=2000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.PROTECT, related_name='+')
    review_reason = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['person', 'requester'],
            condition=models.Q(status='PENDING'), name='unique_pending_person_hide')]


class PrivacyPolicy(models.Model):
    class ResourceType(models.TextChoices):
        EMPLOYMENT = "EMPLOYMENT", _("Место работы")
        EDUCATION = "EDUCATION", _("Образование")
        SKILL = "SKILL", _("Навык")
        HELP_OFFER = "HELP_OFFER", _("Предложение помощи")
        BIOGRAPHY = "BIOGRAPHY", _("Биография")
        LIFE_EVENT = "LIFE_EVENT", _("Событие жизни")
        MEDIA_ASSET = "MEDIA_ASSET", _("Фото / документ")

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
