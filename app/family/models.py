import uuid

from django.conf import settings
from django.db import models

from django.utils.translation import gettext_lazy as _


class RelativeProposal(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Ожидает решения"
        APPROVED = "APPROVED", "Одобрено"
        REJECTED = "REJECTED", "Отклонено"

    class RelationType(models.TextChoices):
        PARENT = "PARENT", "Родитель"
        CHILD = "CHILD", "Ребёнок"
        SPOUSE = "SPOUSE", "Супруг / супруга"
        SIBLING = "SIBLING", "Брат / сестра"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    anchor = models.ForeignKey("Person", on_delete=models.PROTECT, related_name="relative_proposals")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                     related_name="relative_proposals")
    relation_type = models.CharField("Кем приходится", max_length=20, choices=RelationType.choices)
    first_name = models.CharField("Имя", max_length=150)
    middle_name = models.CharField("Отчество", max_length=150, blank=True)
    last_name = models.CharField("Фамилия", max_length=150, blank=True)
    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    is_living = models.BooleanField("Жив", default=True)
    death_date = models.DateField("Дата смерти", null=True, blank=True)
    biography = models.TextField("Что известно о человеке", max_length=10000, blank=True)
    invitation_email = models.EmailField("Email для приглашения (необязательно)", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name="reviewed_relative_proposals", null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True, max_length=2000)
    created_person = models.ForeignKey("Person", on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="creation_proposals")
    invitation = models.ForeignKey("accounts.Invitation", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="relative_proposals")

    class Meta:
        ordering = ["-requested_at", "-id"]
        indexes = [models.Index(fields=["status", "requested_at"]),
                   models.Index(fields=["requested_by", "requested_at"])]

    def __str__(self):
        return " ".join(part for part in (self.first_name, self.middle_name, self.last_name) if part)

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
