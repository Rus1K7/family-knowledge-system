import uuid

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditEvent(models.Model):
    class Action(models.TextChoices):
        CREATE_PERSON = "CREATE_PERSON", _("Создание человека")
        UPDATE_RELATIONSHIP = "UPDATE_RELATIONSHIP", _("Изменение родственной связи")
        DELETE_RELATIONSHIP = "DELETE_RELATIONSHIP", _("Удаление родственной связи")
        CREATE_RELATIONSHIP = (
            "CREATE_RELATIONSHIP",
            _("Создание родственной связи"),
        )

        VIEW_PRIVATE_RESOURCE = (
            "VIEW_PRIVATE_RESOURCE",
            _("Просмотр закрытых данных"),
        )

        UPLOAD_MEDIA = (
            "UPLOAD_MEDIA",
            _("Загрузка файла"),
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

        ARCHIVE_MEDIA = (
            "ARCHIVE_MEDIA",
            _("Архивирование файла"),
        )

        UPDATE_MEDIA = (
            "UPDATE_MEDIA",
            _("Изменение описания файла"),
        )

        VERIFY_HERITAGE = (
            "VERIFY_HERITAGE",
            _("Проверка исторических данных"),
        )

        CREATE_SOURCE = (
            "CREATE_SOURCE",
            _("Создание источника"),
        )

        UPDATE_SOURCE = (
            "UPDATE_SOURCE",
            _("Изменение источника"),
        )

        ARCHIVE_SOURCE = (
            "ARCHIVE_SOURCE",
            _("Архивирование источника"),
        )

        ATTACH_SOURCE = (
            "ATTACH_SOURCE",
            _("Привязка источника"),
        )

        UPDATE_SOURCE_LINK = (
            "UPDATE_SOURCE_LINK",
            _("Изменение связи с источником"),
        )

        DETACH_SOURCE = (
            "DETACH_SOURCE",
            _("Отвязка источника"),
        )

        UPDATE_PRIVACY_POLICY = (
            "UPDATE_PRIVACY_POLICY",
            _("Изменение приватности"),
        )

        REQUEST_ACCESS = (
            "REQUEST_ACCESS",
            _("Запрос доступа"),
        )

        REJECT_ACCESS = (
            "REJECT_ACCESS",
            _("Отклонение запроса доступа"),
        )

        CREATE_INVITATION = (
            "CREATE_INVITATION",
            _("Создание приглашения"),
        )

        ACCEPT_INVITATION = (
            "ACCEPT_INVITATION",
            _("Принятие приглашения"),
        )

        CANCEL_INVITATION = (
            "CANCEL_INVITATION",
            _("Отмена приглашения"),
        )

        REQUEST_CHANGE = (
            "REQUEST_CHANGE",
            _("Создание заявки на изменение"),
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

    details = models.JSONField(
        _("Контекст"),
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
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
