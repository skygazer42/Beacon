# Generated migration for AlgorithmModel license package (License Manager SKU)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0014_license_manager'),
    ]

    operations = [
        migrations.AddField(
            model_name='algorithmmodel',
            name='license_package',
            field=models.CharField(default='core', help_text='License Manager 授权包 SKU（如 core/ppe/traffic_lpr）', max_length=50, verbose_name='授权算法包'),
        ),
    ]

