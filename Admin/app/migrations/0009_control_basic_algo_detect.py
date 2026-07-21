# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0008_algorithm_model_concurrency'),
    ]

    operations = [
        migrations.AddField(
            model_name='control',
            name='basic_algo_detect_mode',
            field=models.IntegerField(default=0, help_text='0=自由竞争（默认）, 1=固定间隔帧, 2=固定间隔秒', verbose_name='基础算法检测模式'),
        ),
        migrations.AddField(
            model_name='control',
            name='basic_algo_detect_interval',
            field=models.IntegerField(default=1, help_text='间隔值（帧数或毫秒数，根据检测模式决定）', verbose_name='检测间隔值'),
        ),
    ]
