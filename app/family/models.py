import uuid

from django.conf import settings
from django.db import models

from django.utils.translation import gettext_lazy as _

class Person(models.Model):
    class DatePrecision(models.TextChoices):
        EXACT = "EXACT", _("Точная дата")
        MONTH_ONLY = "MONTH_ONLY", _("Известны месяц и год")
        YEAR_ONLY = "YEAR_ONLY", _("Известен только год")
        APPROXIMATE = "APPROXIMATE", _("Приблизительно")
        UNKNOWN = "UNKNOWN", _("Неизвестно")

    class ProfileStatus(models.TextChoices):
        UNCLAIMED = "UNCLAIMED", _("Не подтверждён владельцем")
        CLAIMED = "CLAIMED", _("Подтверждён владельцем")
        HERITAGE = "HERITAGE", _("Исторический профиль")
        ARCHIVED = "ARCHIVED", _("Архив")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    first_name = models.CharField(max_length=150)

    middle_name = models.CharField(
        max_length=150,
        blank=True,
    )

    last_name = models.CharField(
        max_length=150,
        blank=True,
    )

    birth_date = models.DateField(
        null=True,
        blank=True,
    )

    birth_date_precision = models.CharField(
        max_length=20,
        choices=DatePrecision.choices,
        default=DatePrecision.UNKNOWN,
    )

    death_date = models.DateField(
        null=True,
        blank=True,
    )

    is_living = models.BooleanField(
        default=True,
    )

    profile_status = models.CharField(
        max_length=20,
        choices=ProfileStatus.choices,
        default=ProfileStatus.UNCLAIMED,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Человек")
        verbose_name_plural = _("Люди")

    def __str__(self):
        parts = [
            self.first_name,
            self.middle_name,
            self.last_name,
        ]

        return " ".join(
            part for part in parts if part
        )


class ProfileOwnership(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        REVOKED = "REVOKED", "Revoked"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile_ownerships",
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="ownerships",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    claimed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _("Владелец профиля")
        verbose_name_plural = _("Владельцы профилей")

        constraints = [
            models.UniqueConstraint(
                fields=["person"],
                condition=models.Q(status="CONFIRMED"),
                name="one_confirmed_owner_per_person",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="CONFIRMED"),
                name="one_confirmed_person_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user} → {self.person}"


class Relationship(models.Model):
    class Type(models.TextChoices):
        PARENT_CHILD = "PARENT_CHILD", _("Родитель → ребёнок")
        SPOUSE = "SPOUSE", _("Супруг / супруга")
        PARTNER = "PARTNER", _("Партнёр")
        SIBLING = "SIBLING", _("Брат / сестра")
        ADOPTIVE_PARENT = "ADOPTIVE_PARENT", _("Приёмный родитель → ребёнок")
        GUARDIAN = "GUARDIAN", _("Опекун → человек")

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Ожидает проверки")
        VERIFIED = "VERIFIED", _("Подтверждено")
        DISPUTED = "DISPUTED", _("Есть разногласия")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    person_a = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="relationships_from",
    )

    person_b = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="relationships_to",
    )

    relationship_type = models.CharField(
        max_length=30,
        choices=Type.choices,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_relationships",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _("Родственная связь")
        verbose_name_plural = _("Родственные связи")

        constraints = [
            models.CheckConstraint(
                condition=~models.Q(
                    person_a=models.F("person_b")
                ),
                name="relationship_not_self",
            ),
        ]

    def __str__(self):
        return (
            f"{self.person_a} "
            f"{self.relationship_type} "
            f"{self.person_b}"
        )