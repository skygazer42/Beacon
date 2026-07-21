from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0043_license_lease_stream_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="apikey",
            name="burst_limit",
            field=models.IntegerField(default=0, verbose_name="突发额度"),
        ),
        migrations.AddField(
            model_name="apikey",
            name="rate_limit_per_minute",
            field=models.IntegerField(default=0, verbose_name="每分钟限流额度"),
        ),
    ]
