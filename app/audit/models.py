import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditEvent(models.Model):
    class Action(models.TextChoices):
        VIEW_PRIVATE_RESOURCE = (
            "VIEW_PRIVATE_RESOURCE",
            _("Просмотр закрытых данных"),
        )

        VIEW_MEDIA = (
            "VIEW_MEDIA",
            _("Просмотр файла"),
        )

        APPROVE_MEDIA = (
            "APPROVE_MEDIA",
            _("Одобрение файла"),
        )

        REJECT_MEDIA = (
            "REJECT_MEDIA",
            _("Отклонение файла"),
        )

        VERIFY_HERITAGE = (
            "VERIFY_HERITAGE",
            _("Проверка исторических данных"),
        )

        GRANT_ACCESS = (
            "GRANT_ACCESS",
            _("Выдача доступа"),
        )

        REVOKE_ACCESS = (
            "REVOKE_ACCESS",
            _("Отзыв доступа"),
        )

        APPROVE_CHANGE = (
            "APPROVE_CHANGE",
            _("Одобрение изменения"),
        )

        REJECT_CHANGE = (
            "REJECT_CHANGE",
            _("Отклонение изменения"),
        )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
        verbose_name=_("Пользователь"),
    )

    action = models.CharField(
        _("Действие"),
        max_length=50,
        choices=Action.choices,
    )

    person = models.ForeignKey(
        "family.Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
        verbose_name=_("Человек"),
    )

    resource_type = models.CharField(
        _("Тип объекта"),
        max_length=50,
        blank=True,
    )

    object_id = models.UUIDField(
        _("ID объекта"),
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        _("Дата"),
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _("Событие аудита")
        verbose_name_plural = _("Журнал аудита")

        ordering = [
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "action",
                    "created_at",
                ]
            ),
            models.Index(
                fields=[
                    "person",
                    "created_at",
                ]
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_action_display()} — "
            f"{self.created_at}"
        )