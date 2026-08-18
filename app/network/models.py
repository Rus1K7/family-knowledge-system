import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from family.models import Person


class HelpOffer(models.Model):
    class Category(models.TextChoices):
        PROFESSIONAL = "PROFESSIONAL", _("Профессиональная помощь")
        EDUCATION = "EDUCATION", _("Обучение")
        ADVICE = "ADVICE", _("Совет / консультация")
        PRACTICAL = "PRACTICAL", _("Практическая помощь")
        OTHER = "OTHER", _("Другое")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="help_offers",
        verbose_name=_("Человек"),
    )

    title = models.CharField(
        _("Чем могу помочь"),
        max_length=200,
    )

    category = models.CharField(
        _("Категория"),
        max_length=30,
        choices=Category.choices,
        default=Category.OTHER,
    )

    description = models.TextField(
        _("Описание"),
        blank=True,
    )

    is_active = models.BooleanField(
        _("Актуально"),
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Предложение помощи")
        verbose_name_plural = _("Предложения помощи")
        ordering = ["title"]

    def __str__(self):
        return f"{self.person}: {self.title}"