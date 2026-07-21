from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0051_alarm_workflow_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="alarm",
            name="assigned_to",
            field=models.CharField(blank=True, default="", max_length=100, verbose_name="assigned_to"),
        ),
        migrations.AddField(
            model_name="alarm",
            name="note_entries",
            field=models.TextField(blank=True, default="[]", verbose_name="note_entries"),
        ),
    ]
