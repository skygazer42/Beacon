from django.db import migrations, models


def _backfill_control_push_stream_fields(apps, schema_editor):
    control_model = apps.get_model("app", "Control")
    control_model.objects.filter(push_stream_app__isnull=True).update(push_stream_app="")
    control_model.objects.filter(push_stream_name__isnull=True).update(push_stream_name="")


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0058_alter_algorithmmodel_algorithm_subtype"),
    ]

    operations = [
        migrations.RunPython(
            _backfill_control_push_stream_fields,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="control",
            name="push_stream_app",
            field=models.CharField(blank=True, default="", max_length=50, verbose_name="推流应用"),
        ),
        migrations.AlterField(
            model_name="control",
            name="push_stream_name",
            field=models.CharField(blank=True, default="", max_length=100, verbose_name="推流名称"),
        ),
    ]
