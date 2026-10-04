import uuid

from django.contrib.auth.models import (
    AbstractUser,
    UserManager as DjangoUserManager,
)
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


class UserManager(DjangoUserManager):
    @classmethod
    def normalize_email(cls, email):
        normalized = super().normalize_email(email)
        return normalized.lower() if normalized else normalized


class User(AbstractUser):
    class Status(models.TextChoices):
        INVITED = "INVITED", _("Приглашён")
        ACTIVE = "ACTIVE", _("Активен")
        SUSPENDED = "SUSPENDED", _("Приостановлен")
        DISABLED = "DISABLED", _("Отключён")

    class SystemRole(models.TextChoices):
        FRIEND = "FRIEND", _("Друг")
        FAMILY_MEMBER = "FAMILY_MEMBER", _("Член семьи")
        FAMILY_HISTORIAN = "FAMILY_HISTORIAN", _("Семейный историк")
        SYSTEM_ADMIN = "SYSTEM_ADMIN", _("Системный администратор")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    email = models.EmailField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    system_role = models.CharField(
        max_length=30,
        choices=SystemRole.choices,
        default=SystemRole.FAMILY_MEMBER,
    )

    # Legacy schema field, not an authentication control. No editable UI:
    # the owner explicitly chose to retain password-only sign-in (2026-09-28).
    mfa_enabled = models.BooleanField(
        default=False,
    )

    can_invite_friends = models.BooleanField(
        "Может приглашать друзей", default=False,
    )

    disabled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="accounts_user_email_ci_unique",
            ),
        ]

    def __str__(self):
        return self.email or self.username


class LoginAttemptWindow(models.Model):
    """Shared, short-lived login counters; keys never contain raw identifiers."""

    key = models.CharField(max_length=64, primary_key=True, editable=False)
    attempts = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class AccountAccessRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Ожидает администратора'
        NEEDS_INFO = 'NEEDS_INFO', 'Нужны уточнения'
        CREATED = 'CREATED', 'Аккаунт создан'
        REJECTED = 'REJECTED', 'Отклонено'
        CANCELLED = 'CANCELLED', 'Отменено вами'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='account_requests')
    person = models.ForeignKey('family.Person', on_delete=models.SET_NULL, null=True, blank=True)
    requested_name = models.CharField('Имя родственника, если карточки нет в списке', max_length=300, blank=True)
    relation_note = models.TextField('Кем приходится и как передать данные для входа', max_length=1000, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(max_length=1000, blank=True)
    created_user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    handed_off_at = models.DateTimeField(null=True, blank=True)
    handed_off_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['requester', 'person'],
            condition=models.Q(status__in=['PENDING', 'NEEDS_INFO'], person__isnull=False), name='one_pending_account_request')]
        indexes = [models.Index(fields=['status', 'created_at'], name='account_request_queue')]
        verbose_name = 'Запрос аккаунта без почты'
        verbose_name_plural = 'Запросы аккаунтов без почты'


class AssistedAccount(models.Model):
    # Authentication uses User.password. Only admin-issued passwords are also
    # recoverable here, authenticated-encrypted with a separate-purpose key.
    user = models.OneToOneField('accounts.User', primary_key=True, on_delete=models.CASCADE, related_name='assisted_account')
    issued_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    issued_at = models.DateTimeField()
    encrypted_password = models.TextField(blank=True, editable=False)

    class Meta:
        ordering = ['-issued_at']
        verbose_name = 'Аккаунт, выданный администратором'
        verbose_name_plural = 'Аккаунты без почты'


from django.conf import settings
from django.utils import timezone

from family.models import Person


class Invitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Ожидает")
        ACCEPTED = "ACCEPTED", _("Принято")
        CANCELLED = "CANCELLED", _("Отменено")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="invitations",
        verbose_name=_("Человек"),
    )

    email = models.EmailField(
        _("Email"),
    )

    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invitations",
        verbose_name=_("Создал"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    expires_at = models.DateTimeField(
        _("Действует до"),
    )

    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    verification_digest = models.CharField(max_length=64, blank=True)
    verification_sent_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self):
        from family.permissions import can_invite_relatives
        return (
            self.status == self.Status.PENDING
            and self.expires_at > timezone.now()
            and self.person.is_living
            and self.person.profile_status != Person.ProfileStatus.ARCHIVED
            and can_invite_relatives(self.created_by)
        )

    def __str__(self):
        return f"{self.person} → {self.email}"


class InvitationEmailAttempt(models.Model):
    """Delivery evidence, not proof of inbox delivery. No message body or token."""

    class Status(models.TextChoices):
        SENDING = 'SENDING', 'Отправляется / результат ещё не записан'
        SUBMITTED = 'SUBMITTED', 'Принято почтовым сервером'
        FAILED = 'FAILED', 'Не отправлено'
        UNKNOWN = 'UNKNOWN', 'Результат не подтверждён'

    invitation = models.ForeignKey(Invitation, null=True, blank=True, on_delete=models.CASCADE, related_name='email_attempts')
    friend_invitation = models.ForeignKey('circles.FriendInvitation', null=True, blank=True, on_delete=models.CASCADE, related_name='email_attempts')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SENDING)
    error_code = models.CharField(max_length=24, blank=True)
    repeated = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.CheckConstraint(
            condition=(models.Q(invitation__isnull=False, friend_invitation__isnull=True)
                       | models.Q(invitation__isnull=True, friend_invitation__isnull=False)),
            name='email_attempt_one_invitation',
        )]


class InvitationHelpRequest(models.Model):
    """Manual enrolment assistance; never a job queue for automatic email."""

    class Kind(models.TextChoices):
        RETRY = 'RETRY', 'Повторная отправка'
        REPLACE = 'REPLACE', 'Исправление приглашения'
        LINK = 'LINK', 'Привязка существующего аккаунта'
        FIND_PERSON = 'FIND_PERSON', 'Помощь с карточкой родственника'
        NEW_PERSON = 'NEW_PERSON', 'Новая карточка и приглашение'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Ожидает администратора'
        NEEDS_INFO = 'NEEDS_INFO', 'Нужны уточнения'
        WAITING_RECIPIENT = 'WAITING_RECIPIENT', 'Ожидает согласия получателя'
        READY = 'READY', 'Можно продолжить приглашение'
        RESOLVED = 'RESOLVED', 'Обработано'
        REJECTED = 'REJECTED', 'Отклонено'
        CANCELLED = 'CANCELLED', 'Отменено'

    class Channel(models.TextChoices):
        EMAIL = 'EMAIL', 'По почте'
        ASSISTED = 'ASSISTED', 'Без почты'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='invitation_help_requests')
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    channel = models.CharField(max_length=12, choices=Channel.choices, default=Channel.EMAIL)
    invitation = models.ForeignKey('accounts.Invitation', on_delete=models.SET_NULL, null=True, blank=True, related_name='help_requests')
    friend_invitation = models.ForeignKey('circles.FriendInvitation', on_delete=models.SET_NULL, null=True, blank=True, related_name='help_requests')
    replacement_invitation = models.ForeignKey('accounts.Invitation', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    replacement_friend_invitation = models.ForeignKey('circles.FriendInvitation', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    access_request = models.ForeignKey('accounts.AccountAccessRequest', on_delete=models.SET_NULL, null=True, blank=True, related_name='invitation_help_requests')
    person = models.ForeignKey('family.Person', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    anchor = models.ForeignKey('family.Person', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    proposal = models.ForeignKey('family.RelativeProposal', on_delete=models.SET_NULL, null=True, blank=True, related_name='invitation_help_requests')
    recipient_user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    email = models.EmailField(blank=True)
    name = models.CharField(max_length=300, blank=True)
    note = models.TextField(max_length=2000, blank=True)
    recipient_consented_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(max_length=2000, blank=True)
    dedup_key = models.CharField(max_length=64, editable=False)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['status', 'created_at'], name='invite_help_queue')]
        constraints = [
            models.CheckConstraint(condition=~models.Q(invitation__isnull=False, friend_invitation__isnull=False), name='invite_help_one_source'),
            models.UniqueConstraint(fields=['requester', 'dedup_key'], condition=models.Q(status__in=[
                'PENDING', 'NEEDS_INFO', 'WAITING_RECIPIENT', 'READY']), name='invite_help_active_unique'),
        ]
        verbose_name = 'Обращение по приглашению'
        verbose_name_plural = 'Обращения по приглашениям'
