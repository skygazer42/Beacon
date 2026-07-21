from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0044_api_key_gateway_limits"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlgorithmModelVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version_no", models.IntegerField(default=1, verbose_name="版本号")),
                ("version_name", models.CharField(default="", max_length=50, verbose_name="版本名")),
                ("note", models.CharField(blank=True, default="", max_length=200, verbose_name="版本备注")),
                ("is_current", models.BooleanField(default=False, verbose_name="是否当前版本")),
                ("is_gray", models.BooleanField(default=False, verbose_name="是否灰度版本")),
                ("gray_control_codes", models.TextField(blank=True, default="", verbose_name="灰度布控白名单")),
                ("activated_at", models.DateTimeField(blank=True, null=True, verbose_name="激活时间")),
                ("create_time", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("algorithm_type", models.IntegerField(default=0, verbose_name="算法类型")),
                ("algorithm_subtype", models.CharField(default="detection", max_length=20, verbose_name="算法子类型")),
                ("basic_source", models.CharField(default="model", max_length=20, verbose_name="基础算法来源")),
                ("api_url", models.TextField(blank=True, default="", verbose_name="api_url")),
                ("model_path", models.CharField(blank=True, default="", max_length=500, verbose_name="模型文件路径")),
                ("dll_path", models.CharField(blank=True, default="", max_length=500, verbose_name="动态库路径")),
                ("builtin_behavior", models.CharField(blank=True, default="", max_length=50, verbose_name="内置行为算法")),
                ("support_direct_api", models.BooleanField(default=False, verbose_name="支持直接API调用")),
                ("behavior_api_version", models.IntegerField(default=1, verbose_name="行为API版本")),
                ("object_count", models.IntegerField(default=0, verbose_name="目标数量")),
                ("object_str", models.TextField(blank=True, default="", verbose_name="目标列表")),
                ("max_control_count", models.IntegerField(default=0, verbose_name="布控数量上限")),
                ("license_package", models.CharField(default="core", max_length=50, verbose_name="授权算法包")),
                ("model_precision", models.CharField(default="FP32", max_length=10, verbose_name="模型精度")),
                ("model_concurrency", models.IntegerField(default=1, verbose_name="模型并发数")),
                ("input_width", models.IntegerField(default=640, verbose_name="输入宽度")),
                ("input_height", models.IntegerField(default=640, verbose_name="输入高度")),
                ("nms_thresh", models.FloatField(default=0.45, verbose_name="NMS阈值")),
                ("conf_thresh", models.FloatField(default=0.25, verbose_name="置信度阈值")),
                (
                    "algorithm",
                    models.ForeignKey(
                        db_column="algorithm_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="version_rows",
                        to="app.algorithmmodel",
                        verbose_name="算法",
                    ),
                ),
            ],
            options={
                "verbose_name": "算法版本",
                "verbose_name_plural": "算法版本",
                "db_table": "av_algorithm_version",
                "unique_together": {("algorithm", "version_no")},
            },
        ),
    ]
