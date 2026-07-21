# Generated migration for Control enhancements and AlarmSound

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0002_algorithmmodel_enhancements'),
    ]

    operations = [
        # Control模型增强
        migrations.AddField(
            model_name='control',
            name='alarm_sound_id',
            field=models.IntegerField(default=0, verbose_name='报警声音ID'),
        ),
        migrations.AddField(
            model_name='control',
            name='alarm_video_type',
            field=models.CharField(default='mp4', max_length=20, verbose_name='报警视频类型'),
        ),
        migrations.AddField(
            model_name='control',
            name='alarm_image_count',
            field=models.IntegerField(default=3, verbose_name='报警图片数量'),
        ),
        # AlarmSound模型
        migrations.CreateModel(
            name='AlarmSound',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='名称')),
                ('file_path', models.CharField(max_length=500, verbose_name='文件路径')),
                ('duration', models.FloatField(default=0, verbose_name='时长(秒)')),
                ('is_default', models.BooleanField(default=False, verbose_name='是否默认')),
                ('remark', models.CharField(blank=True, default='', max_length=200, verbose_name='备注')),
                ('create_time', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('state', models.IntegerField(default=1, verbose_name='状态')),
            ],
            options={
                'verbose_name': '报警声音',
                'verbose_name_plural': '报警声音',
                'db_table': 'av_alarm_sound',
            },
        ),
    ]
