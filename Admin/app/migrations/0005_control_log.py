from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0004_algorithm_api_and_control_limit'),
    ]

    operations = [
        migrations.CreateModel(
            name='ControlLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('control_code', models.CharField(max_length=50, verbose_name='布控编号', blank=True, default='')),
                ('action', models.CharField(max_length=50, verbose_name='动作')),
                ('result_code', models.IntegerField(default=0, verbose_name='结果码')),
                ('result_msg', models.TextField(blank=True, default='', verbose_name='结果信息')),
                ('operator', models.CharField(max_length=100, blank=True, default='', verbose_name='操作人')),
                ('detail', models.TextField(blank=True, default='', verbose_name='详情')),
                ('create_time', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
            ],
            options={
                'verbose_name': '布控日志',
                'verbose_name_plural': '布控日志',
                'db_table': 'av_control_log',
            },
        ),
    ]
