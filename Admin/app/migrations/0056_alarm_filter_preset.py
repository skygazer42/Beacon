from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0055_config_history_snapshot"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlarmFilterPreset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("owner_user_id", models.IntegerField(db_index=True, verbose_name="owner_user_id")),
                ("owner_username", models.CharField(blank=True, default="", max_length=150, verbose_name="owner_username")),
                ("name", models.CharField(max_length=100, verbose_name="name")),
                ("target_mode", models.CharField(default="list", max_length=16, verbose_name="target_mode")),
                ("filter_payload", models.TextField(blank=True, default="{}", verbose_name="filter_payload")),
                ("review_tab", models.CharField(blank=True, default="", max_length=16, verbose_name="review_tab")),
                ("create_time", models.DateTimeField(auto_now_add=True, verbose_name="create_time")),
                ("update_time", models.DateTimeField(auto_now=True, verbose_name="update_time")),
            ],
            options={
                "db_table": "av_alarm_filter_preset",
                "verbose_name": "alarm_filter_preset",
                "verbose_name_plural": "alarm_filter_preset",
                "indexes": [
                    models.Index(fields=["owner_user_id", "target_mode", "name"], name="idx_alarm_preset_owner"),
                ],
                "unique_together": {("owner_user_id", "target_mode", "name")},
            },
        ),
    ]
