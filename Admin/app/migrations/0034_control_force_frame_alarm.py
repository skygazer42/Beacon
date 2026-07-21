from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0033_control_decode_stride"),
    ]

    operations = [
        migrations.AddField(
            model_name="control",
            name="force_frame_alarm",
            field=models.BooleanField(
                default=False,
                verbose_name="强制逐帧报警",
                help_text="开启后：每个触发帧都会生成报警记录（会显著增加存储/网络压力，仅建议用于调试/采样场景）",
            ),
        ),
    ]

