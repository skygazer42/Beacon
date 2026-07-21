from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0041_task_plan"),
    ]

    operations = [
        migrations.AddField(
            model_name="control",
            name="alarm_image_draw_mode",
            field=models.CharField(
                default="boxed",
                help_text="boxed=画框, clean=不画框, both=同时保存画框和不画框图片",
                max_length=20,
                verbose_name="报警图片画框模式",
            ),
        ),
    ]

