from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0027_recording_plan"),
    ]

    operations = [
        migrations.AddField(
            model_name="algorithmmodel",
            name="behavior_api_version",
            field=models.IntegerField(
                choices=[
                    (1, "APIv1（API 完整输出 happen）"),
                    (2, "APIv2（API 输出 detects，本地内置行为后处理）"),
                ],
                default=1,
                help_text="仅对行为/业务算法的自定义API生效：v1=API直接返回happen；v2=API返回detects，本地内置行为再判定",
                verbose_name="行为API版本",
            ),
        ),
    ]

