from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0053_stream_location_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="cloudedgecluster",
            name="rollout_channel",
            field=models.CharField(blank=True, default="", max_length=50, verbose_name="rollout_channel"),
        ),
        migrations.AddField(
            model_name="cloudedgecluster",
            name="rollout_error",
            field=models.TextField(blank=True, default="", verbose_name="rollout_error"),
        ),
        migrations.AddField(
            model_name="cloudedgecluster",
            name="rollout_node_versions_json",
            field=models.TextField(blank=True, default="", verbose_name="rollout_node_versions_json"),
        ),
        migrations.AddField(
            model_name="cloudedgecluster",
            name="rollout_status",
            field=models.CharField(blank=True, default="", max_length=50, verbose_name="rollout_status"),
        ),
        migrations.AddField(
            model_name="cloudedgecluster",
            name="rollout_target_version",
            field=models.CharField(blank=True, default="", max_length=100, verbose_name="rollout_target_version"),
        ),
    ]
