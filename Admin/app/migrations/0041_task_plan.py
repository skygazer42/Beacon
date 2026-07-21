from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0040_login_lockout"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=50, unique=True, verbose_name="计划编号")),
                ("name", models.CharField(blank=True, default="", max_length=100, verbose_name="计划名称")),
                ("enabled", models.BooleanField(default=True, verbose_name="启用")),
                ("task_type", models.CharField(default="restart_software", max_length=50, verbose_name="任务类型")),
                ("schedule_type", models.CharField(default="daily", max_length=20, verbose_name="调度类型")),
                ("run_time", models.TimeField(blank=True, null=True, verbose_name="执行时间（daily）")),
                (
                    "days_mask",
                    models.IntegerField(default=127, help_text="bit0=Mon ... bit6=Sun，默认 127=每天", verbose_name="星期掩码"),
                ),
                ("interval_seconds", models.IntegerField(default=0, verbose_name="间隔秒（interval）")),
                ("target_codes", models.TextField(blank=True, default="", verbose_name="目标列表")),
                ("options_json", models.TextField(blank=True, default="", verbose_name="扩展参数JSON")),
                ("last_run_at", models.DateTimeField(blank=True, null=True, verbose_name="上次执行时间")),
                ("last_result_code", models.IntegerField(default=0, verbose_name="上次执行结果码")),
                ("last_result_msg", models.TextField(blank=True, default="", verbose_name="上次执行结果信息")),
                ("create_time", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("update_time", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "db_table": "av_task_plan",
                "verbose_name": "任务计划",
                "verbose_name_plural": "任务计划",
            },
        ),
    ]

