from django.db import migrations, models
import datetime


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0026_control_osd_algo_fps_coords"),
    ]

    operations = [
        migrations.CreateModel(
            name="RecordingPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=50, unique=True, verbose_name="计划编号")),
                ("name", models.CharField(blank=True, default="", max_length=100, verbose_name="计划名称")),
                ("enabled", models.BooleanField(default=True, verbose_name="启用")),
                ("stream_code", models.CharField(max_length=50, verbose_name="视频流编号")),
                ("stream_url", models.CharField(blank=True, default="", max_length=500, verbose_name="拉流地址(可选)")),
                ("start_time", models.TimeField(default=datetime.time(0, 0), verbose_name="开始时间")),
                ("end_time", models.TimeField(default=datetime.time(23, 59), verbose_name="结束时间")),
                (
                    "days_mask",
                    models.IntegerField(default=127, help_text="bit0=Mon ... bit6=Sun，默认 127=每天", verbose_name="星期掩码"),
                ),
                ("record_audio", models.BooleanField(default=False, verbose_name="录音")),
                ("format", models.CharField(default="mp4", help_text="mp4/ts/flv", max_length=10, verbose_name="录像格式")),
                ("remark", models.TextField(blank=True, default="", verbose_name="备注")),
                ("create_time", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("update_time", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "db_table": "av_recording_plan",
                "verbose_name": "录像计划",
                "verbose_name_plural": "录像计划",
            },
        ),
    ]

