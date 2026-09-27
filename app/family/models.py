import uuid
from django.core.exceptions import ValidationError
from django.utils import timezone

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
        PARTNER = "PARTNER", "Партнёр"
        SIBLING = "SIBLING", "Брат / сестра"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    anchor = models.ForeignKey("Person", on_delete=models.PROTECT, related_name="relative_proposals")
    existing_person = models.ForeignKey("Person", on_delete=models.PROTECT, null=True, blank=True,
                                       related_name="relationship_proposals", verbose_name="Человек из семьи")
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
    family_details = models.JSONField(default=dict, blank=True)
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
    portrait = models.ForeignKey(
        "heritage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="portrait_for_people", verbose_name="Фотография профиля",
    )

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
        permissions = [("manage_family_relationships", "Может управлять связями и одобрять родственников")]

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


class PartnershipPeriod(models.Model):
    """One period of a couple's history, independent of parenthood."""
    class Kind(models.TextChoices):
        MARRIAGE = "MARRIAGE", "Брак"
        PARTNERSHIP = "PARTNERSHIP", "Партнёрство"

    class State(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Статус не указан"
        CURRENT = "CURRENT", "Отношения продолжаются"
        DIVORCED = "DIVORCED", "Развелись"
        SEPARATED = "SEPARATED", "Расстались"
        ENDED = "ENDED", "Союз завершён"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    relationship = models.ForeignKey(Relationship, on_delete=models.CASCADE, related_name="periods")
    kind = models.CharField("Тип союза", max_length=20, choices=Kind.choices)
    state = models.CharField("Состояние отношений", max_length=20, choices=State.choices, default=State.UNKNOWN)
    start_year = models.PositiveSmallIntegerField("Год начала", null=True, blank=True)
    end_year = models.PositiveSmallIntegerField("Год завершения", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_year", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["relationship"], condition=models.Q(state="CURRENT"), name="one_current_period_per_relationship"),
            models.CheckConstraint(condition=models.Q(end_year__isnull=True) | models.Q(start_year__isnull=True) | models.Q(end_year__gte=models.F("start_year")), name="partnership_year_order"),
            models.CheckConstraint(condition=~models.Q(state="CURRENT") | models.Q(end_year__isnull=True), name="current_partnership_no_end"),
        ]

    def clean(self):
        super().clean()
        if self.relationship_id and self.relationship.relationship_type not in {Relationship.Type.SPOUSE, Relationship.Type.PARTNER}:
            raise ValidationError("История отношений доступна только для супругов и партнёров.")
        for field in ("start_year", "end_year"):
            year = getattr(self, field)
            if year is not None and not 1 <= year <= timezone.localdate().year:
                raise ValidationError({field: "Укажите прошедший или текущий год либо оставьте поле пустым."})
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValidationError({"end_year": "Год завершения не может быть раньше начала."})
        if self.state == self.State.CURRENT and self.end_year is not None:
            raise ValidationError({"end_year": "У продолжающихся отношений нет года завершения."})
        if self.state == self.State.DIVORCED and self.kind != self.Kind.MARRIAGE:
            raise ValidationError({"state": "Для партнёрства выберите «Расстались» или «Союз завершён»."})
        if self.state == self.State.CURRENT and self.relationship_id and type(self).objects.filter(
            relationship_id=self.relationship_id, state=self.State.CURRENT,
        ).exclude(pk=self.pk).exists():
            raise ValidationError({"state": "У этой связи уже есть продолжающийся период. Сначала уточните его состояние."})

    @property
    def summary(self):
        label = self.get_state_display()
        if self.state == self.State.CURRENT:
            label = "В браке" if self.kind == self.Kind.MARRIAGE else "В партнёрстве"
        if self.start_year and self.end_year:
            return f"{self.get_kind_display()} · {self.start_year}–{self.end_year} · {label}"
        if self.end_year:
            return f"{label} · {self.end_year}"
        if self.start_year:
            return f"{self.get_kind_display()} · с {self.start_year} · {label}"
        return f"{self.get_kind_display()} · {label}"
