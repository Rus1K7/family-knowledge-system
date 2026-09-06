from django.db import migrations


RESOURCE_MODELS = [
    ("profiles", "Employment", "EMPLOYMENT"),
    ("profiles", "Education", "EDUCATION"),
    ("profiles", "Skill", "SKILL"),
    ("network", "HelpOffer", "HELP_OFFER"),
    ("heritage", "Biography", "BIOGRAPHY"),
    ("heritage", "LifeEvent", "LIFE_EVENT"),
    ("heritage", "MediaAsset", "MEDIA_ASSET"),
]


def backfill_default_privacy_policies(apps, schema_editor):
    privacy_policy = apps.get_model(
        "privacy",
        "PrivacyPolicy",
    )

    for app_label, model_name, resource_type in RESOURCE_MODELS:
        resource_model = apps.get_model(
            app_label,
            model_name,
        )
        policies = []

        for object_id, person_id in (
            resource_model.objects
            .values_list("id", "person_id")
            .iterator(chunk_size=500)
        ):
            policies.append(
                privacy_policy(
                    person_id=person_id,
                    resource_type=resource_type,
                    object_id=object_id,
                    visibility="FAMILY",
                    show_existence=True,
                )
            )

            if len(policies) == 500:
                privacy_policy.objects.bulk_create(
                    policies,
                    ignore_conflicts=True,
                )
                policies = []

        if policies:
            privacy_policy.objects.bulk_create(
                policies,
                ignore_conflicts=True,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("heritage", "0005_alter_mediaasset_file"),
        ("network", "0001_initial"),
        ("privacy", "0003_alter_privacypolicy_resource_type"),
        ("profiles", "0005_alter_profilechangerequest_resource_type"),
    ]

    operations = [
        migrations.RunPython(
            backfill_default_privacy_policies,
            migrations.RunPython.noop,
        ),
    ]
