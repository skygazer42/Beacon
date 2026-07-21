from django.db import migrations, models


DEFAULT_OVERLAY_COLOR = "255,0,0"
OVERLAY_COLOR_HELP_TEXT = "RGB 格式，如：255,0,0（红色）"


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0031_control_feature_algorithm"),
    ]

    operations = [
        migrations.AddField(
            model_name="control",
            name="osd_font_thickness",
            field=models.IntegerField(
                default=2,
                help_text="OpenCV putText 的 thickness 参数（默认 2）",
                verbose_name="OSD字体厚度",
            ),
        ),
        migrations.AddField(
            model_name="control",
            name="overlay_region_color",
            field=models.CharField(
                default=DEFAULT_OVERLAY_COLOR,
                help_text=OVERLAY_COLOR_HELP_TEXT,
                max_length=20,
                verbose_name="区域框颜色",
            ),
        ),
        migrations.AddField(
            model_name="control",
            name="overlay_region_thickness",
            field=models.IntegerField(
                default=4,
                help_text="区域多边形/矩形线宽（像素），默认 4",
                verbose_name="区域框厚度",
            ),
        ),
        migrations.AddField(
            model_name="control",
            name="overlay_line_color",
            field=models.CharField(
                default=DEFAULT_OVERLAY_COLOR,
                help_text=OVERLAY_COLOR_HELP_TEXT,
                max_length=20,
                verbose_name="线段颜色",
            ),
        ),
        migrations.AddField(
            model_name="control",
            name="overlay_line_thickness",
            field=models.IntegerField(
                default=4,
                help_text="线段线宽（像素），默认 4",
                verbose_name="线段厚度",
            ),
        ),
        migrations.AddField(
            model_name="control",
            name="overlay_detect_color",
            field=models.CharField(
                default=DEFAULT_OVERLAY_COLOR,
                help_text=OVERLAY_COLOR_HELP_TEXT,
                max_length=20,
                verbose_name="检测目标颜色",
            ),
        ),
        migrations.AddField(
            model_name="control",
            name="overlay_detect_thickness",
            field=models.IntegerField(
                default=2,
                help_text="目标框/文字线宽（像素），默认 2",
                verbose_name="检测目标厚度",
            ),
        ),
        migrations.AddField(
            model_name="control",
            name="overlay_detect_font_size",
            field=models.IntegerField(
                default=48,
                help_text="OpenCV putText 字体大小（基准 24，默认 48 ≈ 2.0 倍）",
                verbose_name="检测目标字体大小",
            ),
        ),
    ]
