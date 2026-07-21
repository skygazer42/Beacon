from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0050_cloud_edge_cluster_remote_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="alarm",
            name="workflow_status",
            field=models.CharField(default="new", max_length=32, verbose_name="workflow_status"),
        ),
        migrations.AddField(
            model_name="alarm",
            name="workflow_updated_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="workflow_updated_at"),
        ),
        migrations.AddField(
            model_name="alarm",
            name="workflow_updated_by",
            field=models.CharField(blank=True, default="", max_length=100, verbose_name="workflow_updated_by"),
        ),
    ]
