import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from family.models import Person
from django.conf import settings


class Employment(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="employments",
        verbose_name=_("Человек"),
    )

    organization = models.CharField(
        _("Организация"),
        max_length=255,
    )

    position = models.CharField(
        _("Должность"),
        max_length=255,
        blank=True,
    )

    start_date = models.DateField(
        _("Дата начала"),
        null=True,
        blank=True,
    )

    end_date = models.DateField(
        _("Дата окончания"),
        null=True,
        blank=True,
    )

    is_current = models.BooleanField(
        _("Текущее место работы"),
        default=False,
    )

    description = models.TextField(
        _("Описание"),
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Место работы")
        verbose_name_plural = _("Места работы")
        ordering = ["-is_current", "-start_date"]

    def __str__(self):
        if self.position:
            return f"{self.person}: {self.position} — {self.organization}"

        return f"{self.person}: {self.organization}"


class Education(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="educations",
        verbose_name=_("Человек"),
    )

    institution = models.CharField(
        _("Учебное заведение"),
        max_length=255,
    )

    degree = models.CharField(
        _("Степень / уровень образования"),
        max_length=255,
        blank=True,
    )

    field_of_study = models.CharField(
        _("Специальность"),
        max_length=255,
        blank=True,
    )

    start_year = models.PositiveIntegerField(
        _("Год начала"),
        null=True,
        blank=True,
    )

    end_year = models.PositiveIntegerField(
        _("Год окончания"),
        null=True,
        blank=True,
    )

    description = models.TextField(
        _("Описание"),
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Образование")
        verbose_name_plural = _("Образование")
        ordering = ["-end_year", "-start_year"]

    def __str__(self):
        return f"{self.person}: {self.institution}"


class Skill(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="skills",
        verbose_name=_("Человек"),
    )

    name = models.CharField(
        _("Навык"),
        max_length=150,
    )

    description = models.TextField(
        _("Описание"),
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Навык")
        verbose_name_plural = _("Навыки")
        ordering = ["name"]

    def __str__(self):
        return f"{self.person}: {self.name}"

class ProfileChangeRequest(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", _("Добавление")
        EDIT = "EDIT", _("Редактирование")
        DELETE = "DELETE", _("Удаление")

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Ожидает рассмотрения")
        APPROVED = "APPROVED", _("Одобрено")
        REJECTED = "REJECTED", _("Отклонено")
        CANCELLED = "CANCELLED", _("Отменено")

    class ResourceType(models.TextChoices):
        EMPLOYMENT = "EMPLOYMENT", _("Место работы")
        EDUCATION = "EDUCATION", _("Образование")
        SKILL = "SKILL", _("Навык")
        HELP_OFFER = "HELP_OFFER", _("Предложение помощи")
        BIOGRAPHY = "BIOGRAPHY", _("Биография")
        LIFE_EVENT = "LIFE_EVENT", _("Событие жизни")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    resource_type = models.CharField(
        _("Тип данных"),
        max_length=30,
        choices=ResourceType.choices,
    )

    object_id = models.UUIDField(
        _("ID записи"),
        null=True,
        blank=True,
    )

    action = models.CharField(
        _("Действие"),
        max_length=20,
        choices=Action.choices,
    )

    proposed_data = models.JSONField(
        _("Предлагаемые данные"),
        default=dict,
        blank=True,
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="profile_change_requests",
        verbose_name=_("Автор запроса"),
    )

    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_profile_change_requests",
        verbose_name=_("Рассмотрел"),
    )

    requested_at = models.DateTimeField(
        _("Дата запроса"),
        auto_now_add=True,
    )

    reviewed_at = models.DateTimeField(
        _("Дата рассмотрения"),
        null=True,
        blank=True,
    )

    comment = models.TextField(
        _("Комментарий"),
        blank=True,
    )

    class Meta:
        verbose_name = _("Запрос на изменение")
        verbose_name_plural = _("Запросы на изменения")
        ordering = ["-requested_at"]

    def __str__(self):
        return (
            f"{self.get_action_display()} — "
            f"{self.get_resource_type_display()}"
        )