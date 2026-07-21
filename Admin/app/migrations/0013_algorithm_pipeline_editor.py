# Generated migration for AlgorithmPipeline editor

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0012_algorithm_pipeline_modes'),
    ]

    operations = [
        migrations.CreateModel(
            name='AlgorithmPipeline',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=50, unique=True, verbose_name='流程编号')),
                ('name', models.CharField(max_length=100, verbose_name='流程名称')),
                ('description', models.TextField(blank=True, default='', verbose_name='描述')),
                ('nodes', models.TextField(blank=True, default='[]', verbose_name='节点数据 JSON')),
                ('edges', models.TextField(blank=True, default='[]', verbose_name='连线数据 JSON')),
                ('user_id', models.IntegerField(default=0, verbose_name='创建用户')),
                ('is_template', models.BooleanField(default=False, verbose_name='是否模板')),
                ('is_active', models.BooleanField(default=True, verbose_name='是否启用')),
                ('create_time', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('update_time', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '算法流程',
                'verbose_name_plural': '算法流程',
                'db_table': 'av_algorithm_pipeline',
            },
        ),
    ]
