from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_email_case_insensitive"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoginAttemptWindow",
            fields=[
                ("key", models.CharField(editable=False, max_length=64, primary_key=True, serialize=False)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("expires_at", models.DateTimeField(db_index=True)),
            ],
        ),
    ]
