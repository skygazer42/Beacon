from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0047_usertotprecoverycode"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserOidcIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider_id", models.CharField(default="default", max_length=64, verbose_name="OIDC Provider ID")),
                ("subject", models.CharField(max_length=255, verbose_name="OIDC subject(sub)")),
                ("email", models.CharField(blank=True, default="", max_length=254, verbose_name="OIDC email")),
                ("create_time", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("update_time", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="oidc_identities",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="用户",
                    ),
                ),
            ],
            options={
                "verbose_name": "用户OIDC身份",
                "verbose_name_plural": "用户OIDC身份",
                "db_table": "av_user_oidc_identity",
            },
        ),
        migrations.AddConstraint(
            model_name="useroidcidentity",
            constraint=models.UniqueConstraint(fields=("provider_id", "subject"), name="uniq_user_oidc_provider_sub"),
        ),
        migrations.AddIndex(
            model_name="useroidcidentity",
            index=models.Index(fields=["provider_id", "subject"], name="idx_oidc_provider_sub"),
        ),
        migrations.AddIndex(
            model_name="useroidcidentity",
            index=models.Index(fields=["user"], name="idx_oidc_user"),
        ),
    ]

