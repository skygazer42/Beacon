# ========== 报警数据扩展迁移 ==========
# 扩展报警描述文本信息，优化存储结构

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0010_control_osd_config'),
    ]

    operations = [
        # 扩展报警描述字段
        migrations.AddField(
            model_name='alarm',
            name='detail_desc',
            field=models.TextField(verbose_name='详细描述', blank=True, default=''),
        ),

        # 添加报警类型分类
        migrations.AddField(
            model_name='alarm',
            name='alarm_type',
            field=models.CharField(max_length=50, verbose_name='报警类型', default='detection'),
        ),

        # 添加报警级别
        migrations.AddField(
            model_name='alarm',
            name='alarm_level',
            field=models.IntegerField(verbose_name='报警级别', default=1,
                                     help_text='1=低, 2=中, 3=高, 4=紧急'),
        ),

        # 添加算法编号
        migrations.AddField(
            model_name='alarm',
            name='algorithm_code',
            field=models.CharField(max_length=50, verbose_name='算法编号', blank=True, default=''),
        ),

        # 添加目标编号
        migrations.AddField(
            model_name='alarm',
            name='object_code',
            field=models.CharField(max_length=50, verbose_name='目标编号', blank=True, default=''),
        ),

        # 添加检测区域
        migrations.AddField(
            model_name='alarm',
            name='recognition_region',
            field=models.CharField(max_length=200, verbose_name='检测区域坐标', blank=True, default=''),
        ),

        # 添加分类阈值
        migrations.AddField(
            model_name='alarm',
            name='class_thresh',
            field=models.FloatField(verbose_name='分类阈值', default=0.5),
        ),

        # 添加重叠阈值
        migrations.AddField(
            model_name='alarm',
            name='overlap_thresh',
            field=models.FloatField(verbose_name='重叠阈值', default=0.5),
        ),

        # 添加最小间隔
        migrations.AddField(
            model_name='alarm',
            name='min_interval',
            field=models.BigIntegerField(verbose_name='最小间隔(毫秒)', default=0),
        ),

        # 添加视频流编号
        migrations.AddField(
            model_name='alarm',
            name='stream_code',
            field=models.CharField(max_length=50, verbose_name='视频流编号', blank=True, default=''),
        ),

        # 添加视频流 app
        migrations.AddField(
            model_name='alarm',
            name='stream_app',
            field=models.CharField(max_length=50, verbose_name='视频流app', blank=True, default=''),
        ),

        # 添加视频流 name
        migrations.AddField(
            model_name='alarm',
            name='stream_name',
            field=models.CharField(max_length=100, verbose_name='视频流name', blank=True, default=''),
        ),

        # 添加拉流地址
        migrations.AddField(
            model_name='alarm',
            name='stream_url',
            field=models.CharField(max_length=300, verbose_name='拉流地址', blank=True, default=''),
        ),

        # 添加附加图片路径（JSON数组）
        migrations.AddField(
            model_name='alarm',
            name='extra_images',
            field=models.TextField(verbose_name='附加图片路径', blank=True, default='',
                                  help_text='JSON数组格式，存储多张附加图片路径'),
        ),

        # 添加元数据（JSON格式）
        migrations.AddField(
            model_name='alarm',
            name='metadata',
            field=models.TextField(verbose_name='元数据', blank=True, default='',
                                  help_text='JSON格式，存储扩展信息'),
        ),

        # 添加处理状态
        migrations.AddField(
            model_name='alarm',
            name='handled',
            field=models.BooleanField(verbose_name='是否已处理', default=False),
        ),

        # 添加处理时间
        migrations.AddField(
            model_name='alarm',
            name='handled_time',
            field=models.DateTimeField(verbose_name='处理时间', null=True, blank=True),
        ),

        # 添加处理人
        migrations.AddField(
            model_name='alarm',
            name='handled_by',
            field=models.CharField(max_length=100, verbose_name='处理人', blank=True, default=''),
        ),

        # 添加处理备注
        migrations.AddField(
            model_name='alarm',
            name='handled_remark',
            field=models.TextField(verbose_name='处理备注', blank=True, default=''),
        ),

        # 修改 desc 字段长度
        migrations.AlterField(
            model_name='alarm',
            name='desc',
            field=models.CharField(max_length=500, verbose_name='描述', blank=True, default=''),
        ),

        # 修改 video_path 字段长度
        migrations.AlterField(
            model_name='alarm',
            name='video_path',
            field=models.CharField(max_length=500, verbose_name='视频存储路径', blank=True, default=''),
        ),

        # 修改 image_path 字段长度
        migrations.AlterField(
            model_name='alarm',
            name='image_path',
            field=models.CharField(max_length=500, verbose_name='主图存储路径', blank=True, default=''),
        ),
    ]
