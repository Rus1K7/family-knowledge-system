import accounts.models
from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def normalize_user_emails(apps, schema_editor):
    user_model = apps.get_model("accounts", "User")

    duplicate_groups = (
        user_model.objects
        .annotate(normalized_email=Lower("email"))
        .values("normalized_email")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )

    if duplicate_groups.exists():
        raise RuntimeError(
            "Найдены email, различающиеся только регистром. "
            "Устраните дубликаты перед применением миграции."
        )

    for user in user_model.objects.only("id", "email").iterator():
        normalized_email = user.email.lower()

        if user.email != normalized_email:
            user_model.objects.filter(id=user.id).update(
                email=normalized_email
            )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_alter_user_status_alter_user_system_role_invitation"),
    ]

    operations = [
        migrations.RunPython(
            normalize_user_emails,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(max_length=254),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                Lower("email"),
                name="accounts_user_email_ci_unique",
            ),
        ),
        migrations.AlterModelManagers(
            name="user",
            managers=[
                ("objects", accounts.models.UserManager()),
            ],
        ),
    ]
