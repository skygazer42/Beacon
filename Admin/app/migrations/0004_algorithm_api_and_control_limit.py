from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0003_control_alarm_enhancements'),
    ]

    operations = [
        migrations.AddField(
            model_name='algorithmmodel',
            name='basic_source',
            field=models.CharField(
                max_length=20,
                default='model',
                choices=[('model', '本地模型'), ('api', 'API接口')],
                verbose_name='基础算法来源'
            ),
        ),
        migrations.AddField(
            model_name='algorithmmodel',
            name='max_control_count',
            field=models.IntegerField(default=0, verbose_name='布控数量上限'),
        ),
    ]
