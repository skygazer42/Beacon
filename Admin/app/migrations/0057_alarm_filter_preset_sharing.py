from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0056_alarm_filter_preset"),
    ]

    operations = [
        migrations.AddField(
            model_name="alarmfilterpreset",
            name="share_permission_key",
            field=models.CharField(blank=True, default="", max_length=100, verbose_name="share_permission_key"),
        ),
        migrations.AddField(
            model_name="alarmfilterpreset",
            name="visibility_scope",
            field=models.CharField(default="private", max_length=20, verbose_name="visibility_scope"),
        ),
    ]
