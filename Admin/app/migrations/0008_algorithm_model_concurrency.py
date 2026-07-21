from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0007_control_patrol_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='algorithmmodel',
            name='model_concurrency',
            field=models.IntegerField(default=1, verbose_name='模型并发数'),
        ),
    ]

