# Generated migration for OSD configuration fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0009_control_basic_algo_detect'),
    ]

    operations = [
        migrations.AddField(
            model_name='control',
            name='osd_enabled',
            field=models.BooleanField(default=False, help_text='是否在推流视频上叠加文字信息', verbose_name='启用OSD'),
        ),
        migrations.AddField(
            model_name='control',
            name='osd_text',
            field=models.CharField(blank=True, default='', help_text='支持中文，可使用变量：{time}, {stream_name}, {algorithm_name}', max_length=200, verbose_name='OSD文字内容'),
        ),
        migrations.AddField(
            model_name='control',
            name='osd_position',
            field=models.CharField(default='top-left', help_text='top-left, top-right, bottom-left, bottom-right, custom', max_length=20, verbose_name='OSD位置'),
        ),
        migrations.AddField(
            model_name='control',
            name='osd_x',
            field=models.IntegerField(default=10, help_text='自定义位置时使用，像素值', verbose_name='OSD X坐标'),
        ),
        migrations.AddField(
            model_name='control',
            name='osd_y',
            field=models.IntegerField(default=30, help_text='自定义位置时使用，像素值', verbose_name='OSD Y坐标'),
        ),
        migrations.AddField(
            model_name='control',
            name='osd_font_size',
            field=models.IntegerField(default=24, help_text='字体大小，默认24', verbose_name='OSD字体大小'),
        ),
        migrations.AddField(
            model_name='control',
            name='osd_font_color',
            field=models.CharField(default='255,255,255', help_text='RGB格式，如：255,255,255（白色）', max_length=20, verbose_name='OSD字体颜色'),
        ),
        migrations.AddField(
            model_name='control',
            name='osd_bg_enabled',
            field=models.BooleanField(default=True, help_text='是否显示半透明黑色背景', verbose_name='启用OSD背景'),
        ),
    ]
