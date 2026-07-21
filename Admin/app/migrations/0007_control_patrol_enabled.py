from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0006_algorithm_and_control_enhancements'),
    ]

    operations = [
        migrations.AddField(
            model_name='control',
            name='patrol_enabled',
            field=models.BooleanField(default=False, verbose_name='轮巡启用'),
        ),
    ]

