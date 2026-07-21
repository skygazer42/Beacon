from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0048_useroidcidentity"),
    ]

    operations = [
        migrations.CreateModel(
            name="StreamTalkbackConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stream_code", models.CharField(max_length=50, unique=True, verbose_name="视频流编号")),
                ("enabled", models.BooleanField(default=False, verbose_name="启用")),
                ("transport_mode", models.CharField(default="webrtc_to_rtsp", max_length=50, verbose_name="传输模式")),
                ("onvif_service_url", models.CharField(blank=True, default="", max_length=500, verbose_name="ONVIF服务地址")),
                ("onvif_username", models.CharField(blank=True, default="", max_length=200, verbose_name="ONVIF用户名")),
                ("onvif_password", models.CharField(blank=True, default="", max_length=500, verbose_name="ONVIF密码")),
                ("profile_token", models.CharField(blank=True, default="", max_length=200, verbose_name="ProfileToken")),
                ("backchannel_uri", models.CharField(blank=True, default="", max_length=1000, verbose_name="回讲地址")),
                ("relay_app", models.CharField(default="talkback", max_length=50, verbose_name="中继应用")),
                ("relay_stream_prefix", models.CharField(blank=True, default="", max_length=100, verbose_name="中继流前缀")),
                ("sample_rate", models.IntegerField(default=16000, verbose_name="采样率")),
                ("codec_hint", models.CharField(default="pcma", max_length=50, verbose_name="编码提示")),
                ("remark", models.TextField(blank=True, default="", verbose_name="备注")),
                ("create_time", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("update_time", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "verbose_name": "视频流回讲配置",
                "verbose_name_plural": "视频流回讲配置",
                "db_table": "av_stream_talkback_config",
            },
        ),
    ]
