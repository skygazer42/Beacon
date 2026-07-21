from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0052_alarm_assignment_notes"),
    ]

    operations = [
        migrations.AddField(
            model_name="stream",
            name="floor_label",
            field=models.CharField(blank=True, default="", max_length=100, verbose_name="楼层标签"),
        ),
        migrations.AddField(
            model_name="stream",
            name="site_label",
            field=models.CharField(blank=True, default="", max_length=100, verbose_name="站点标签"),
        ),
    ]
