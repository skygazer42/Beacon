# Generated migration for AlgorithmModel enhancements

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='algorithmmodel',
            name='algorithm_type',
            field=models.IntegerField(choices=[(0, '基础算法'), (1, '行为算法')], default=0, verbose_name='算法类型'),
        ),
        migrations.AddField(
            model_name='algorithmmodel',
            name='model_path',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='模型文件路径'),
        ),
        migrations.AddField(
            model_name='algorithmmodel',
            name='dll_path',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='动态库路径'),
        ),
        migrations.AddField(
            model_name='algorithmmodel',
            name='builtin_behavior',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='内置行为算法'),
        ),
        migrations.AlterField(
            model_name='algorithmmodel',
            name='api_url',
            field=models.TextField(blank=True, default='', verbose_name='api_url'),
        ),
        migrations.AlterField(
            model_name='algorithmmodel',
            name='remark',
            field=models.TextField(blank=True, default='', verbose_name='remark'),
        ),
    ]
