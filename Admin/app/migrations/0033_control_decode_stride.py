from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0032_control_overlay_style"),
    ]

    operations = [
        migrations.AddField(
            model_name="control",
            name="decode_stride",
            field=models.IntegerField(
                default=1,
                verbose_name="跳帧解码间隔",
                help_text="1=全帧解码；N=每N帧解码一次（降低CPU消耗，但可能降低推流/报警帧率）",
            ),
        ),
    ]

