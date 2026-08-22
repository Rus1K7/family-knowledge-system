import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from family.models import Person


class Biography(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    person = models.OneToOneField(
        Person,
        on_delete=models.CASCADE,
        related_name="biography",
        verbose_name=_("Человек"),
    )

    text = models.TextField(
        _("Биография"),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_biographies",
        verbose_name=_("Создал"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Биография")
        verbose_name_plural = _("Биографии")

    def __str__(self):
        return f"Биография: {self.person}"


class LifeEvent(models.Model):
    class EventType(models.TextChoices):
        MOVE = "MOVE", _("Переезд")
        EDUCATION = "EDUCATION", _("Образование")
        EMPLOYMENT = "EMPLOYMENT", _("Работа")
        MARRIAGE = "MARRIAGE", _("Брак")
        AWARD = "AWARD", _("Награда")
        MILITARY_SERVICE = (
            "MILITARY_SERVICE",
            _("Военная служба"),
        )
        TRAVEL = "TRAVEL", _("Путешествие")
        FAMILY = "FAMILY", _("Семейное событие")
        OTHER = "OTHER", _("Другое")

    class DatePrecision(models.TextChoices):
        EXACT = "EXACT", _("Точная дата")
        MONTH = "MONTH", _("Известен месяц")
        YEAR = "YEAR", _("Известен только год")
        APPROXIMATE = "APPROXIMATE", _("Примерная дата")
        UNKNOWN = "UNKNOWN", _("Дата неизвестна")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="life_events",
        verbose_name=_("Человек"),
    )

    event_type = models.CharField(
        _("Тип события"),
        max_length=30,
        choices=EventType.choices,
        default=EventType.OTHER,
    )

    title = models.CharField(
        _("Название"),
        max_length=200,
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

    date_precision = models.CharField(
        _("Точность даты"),
        max_length=20,
        choices=DatePrecision.choices,
        default=DatePrecision.EXACT,
    )

    place = models.CharField(
        _("Место"),
        max_length=255,
        blank=True,
    )

    description = models.TextField(
        _("Описание"),
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_life_events",
        verbose_name=_("Создал"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Событие жизни")
        verbose_name_plural = _("События жизни")

        ordering = [
            "start_date",
            "created_at",
        ]

    def __str__(self):
        return f"{self.person}: {self.title}"

class Source(models.Model):
    class SourceType(models.TextChoices):
        ORAL = "ORAL", _("Устный рассказ")
        DOCUMENT = "DOCUMENT", _("Документ")
        PHOTO = "PHOTO", _("Фотография")
        ARCHIVE = "ARCHIVE", _("Архивная запись")
        BOOK = "BOOK", _("Книга / публикация")
        WEBSITE = "WEBSITE", _("Веб-сайт")
        OTHER = "OTHER", _("Другое")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    source_type = models.CharField(
        _("Тип источника"),
        max_length=20,
        choices=SourceType.choices,
        default=SourceType.OTHER,
    )

    title = models.CharField(
        _("Название"),
        max_length=255,
    )

    author = models.CharField(
        _("Автор / рассказчик"),
        max_length=255,
        blank=True,
    )

    source_date = models.DateField(
        _("Дата источника"),
        null=True,
        blank=True,
    )

    url = models.URLField(
        _("Ссылка"),
        blank=True,
    )

    citation = models.TextField(
        _("Описание / ссылка на источник"),
        blank=True,
    )

    notes = models.TextField(
        _("Примечания"),
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sources",
        verbose_name=_("Добавил"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Источник")
        verbose_name_plural = _("Источники")

        ordering = [
            "-source_date",
            "title",
        ]

    def __str__(self):
        return self.title

class SourceLink(models.Model):
    class ResourceType(models.TextChoices):
        BIOGRAPHY = "BIOGRAPHY", _("Биография")
        LIFE_EVENT = "LIFE_EVENT", _("Событие жизни")

    class RelationType(models.TextChoices):
        SUPPORTS = "SUPPORTS", _("Подтверждает")
        CONTRADICTS = "CONTRADICTS", _("Противоречит")
        CONTEXT = "CONTEXT", _("Дополнительный контекст")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    source = models.ForeignKey(
        Source,
        on_delete=models.CASCADE,
        related_name="links",
        verbose_name=_("Источник"),
    )

    resource_type = models.CharField(
        _("Тип объекта"),
        max_length=30,
        choices=ResourceType.choices,
    )

    object_id = models.UUIDField(
        _("ID объекта"),
    )

    relation_type = models.CharField(
        _("Роль источника"),
        max_length=20,
        choices=RelationType.choices,
        default=RelationType.SUPPORTS,
    )

    note = models.TextField(
        _("Комментарий к связи"),
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_source_links",
        verbose_name=_("Добавил связь"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _("Связь с источником")
        verbose_name_plural = _("Связи с источниками")

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "source",
                    "resource_type",
                    "object_id",
                ],
                name="unique_source_resource_link",
            ),
        ]

    def __str__(self):
        return (
            f"{self.source} → "
            f"{self.get_resource_type_display()}"
        )

class Verification(models.Model):
    class ResourceType(models.TextChoices):
        BIOGRAPHY = "BIOGRAPHY", _("Биография")
        LIFE_EVENT = "LIFE_EVENT", _("Событие жизни")

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Черновик")
        PENDING = "PENDING", _("Ожидает проверки")
        VERIFIED = "VERIFIED", _("Подтверждено")
        REJECTED = "REJECTED", _("Отклонено")
        DISPUTED = "DISPUTED", _("Спорное")
        ARCHIVED = "ARCHIVED", _("Архивировано")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    resource_type = models.CharField(
        _("Тип объекта"),
        max_length=30,
        choices=ResourceType.choices,
    )

    object_id = models.UUIDField(
        _("ID объекта"),
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
        related_name="heritage_verifications",
        verbose_name=_("Проверил"),
    )

    comment = models.TextField(
        _("Комментарий"),
        blank=True,
    )

    reviewed_at = models.DateTimeField(
        _("Дата проверки"),
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Проверка достоверности")
        verbose_name_plural = _("Проверки достоверности")

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "resource_type",
                    "object_id",
                ],
                name="unique_heritage_verification",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_resource_type_display()} — "
            f"{self.get_status_display()}"
        )