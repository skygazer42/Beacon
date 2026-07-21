from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0035_user_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="control",
            name="pull_frequency",
            field=models.IntegerField(
                default=0,
                verbose_name="拉流频率(帧/秒)",
                help_text="0=不启用；>0 表示最多每秒解码/处理 N 帧（可降低 CPU 消耗）",
            ),
        ),
        migrations.AddField(
            model_name="control",
            name="ps_effect_min_fps",
            field=models.IntegerField(
                default=0,
                verbose_name="推流最低FPS",
                help_text="仅推流布控生效：推流效果/画面刷新最低 FPS（0=不限制）；与 pull_frequency 取 max",
            ),
        ),
        migrations.AddField(
            model_name="control",
            name="analysis_prompt",
            field=models.TextField(
                default="",
                blank=True,
                verbose_name="大模型提示词(中文)",
                help_text="流程模式5/大模型分析：每个布控可设置独立提示词（启动时注入 behaviorConfig 下发给行为 API）",
            ),
        ),
    ]

