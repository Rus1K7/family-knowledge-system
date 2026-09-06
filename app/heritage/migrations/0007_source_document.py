import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("heritage", "0006_source_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="source",
            name="document",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sources",
                to="heritage.mediaasset",
                verbose_name="Документ в семейном архиве",
            ),
        ),
    ]
