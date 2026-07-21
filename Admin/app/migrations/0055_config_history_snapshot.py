from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0054_cloud_edge_rollout_visibility"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConfigHistorySnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(default="system", max_length=50, verbose_name="scope")),
                ("change_type", models.CharField(default="system.save", max_length=100, verbose_name="change_type")),
                ("actor", models.CharField(blank=True, default="", max_length=150, verbose_name="actor")),
                ("summary", models.CharField(blank=True, default="", max_length=200, verbose_name="summary")),
                ("snapshot_json", models.TextField(blank=True, default="", verbose_name="snapshot_json")),
                ("diff_json", models.TextField(blank=True, default="", verbose_name="diff_json")),
                ("create_time", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                (
                    "rollback_of",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="rollback_children",
                        to="app.confighistorysnapshot",
                        verbose_name="rollback_of",
                    ),
                ),
            ],
            options={
                "db_table": "av_config_history_snapshot",
                "verbose_name": "配置历史快照",
                "verbose_name_plural": "配置历史快照",
            },
        ),
        migrations.AddIndex(
            model_name="confighistorysnapshot",
            index=models.Index(fields=["scope", "create_time"], name="idx_cfg_hist_scope_time"),
        ),
    ]
