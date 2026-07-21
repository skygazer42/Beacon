# ========== 算法流程模式扩展迁移 ==========
# 新增算法流程模式配置，支持5种流程模式

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0011_alarm_enhancements'),
    ]

    operations = [
        # ========== AlgorithmModel 扩展 ==========
        # 添加算法子类型（用于区分检测、分类、追踪）
        migrations.AddField(
            model_name='algorithmmodel',
            name='algorithm_subtype',
            field=models.CharField(
                max_length=20,
                default='detection',
                verbose_name='算法子类型',
                help_text='detection=检测, classification=分类, tracking=追踪, behavior=行为'
            ),
        ),

        # 添加是否支持直接API调用（用于模式5）
        migrations.AddField(
            model_name='algorithmmodel',
            name='support_direct_api',
            field=models.BooleanField(
                default=False,
                verbose_name='支持直接API调用',
                help_text='行为算法是否支持直接接收图片数据（模式5）'
            ),
        ),

        # ========== Control 扩展 ==========
        # 添加算法流程模式字段
        migrations.AddField(
            model_name='control',
            name='algorithm_pipeline_mode',
            field=models.IntegerField(
                default=1,
                verbose_name='算法流程模式',
                help_text='1=检测>>行为, 2=检测>>追踪>>行为, 3=检测>>分类>>行为, 4=分类>>行为, 5=行为'
            ),
        ),

        # 添加追踪算法编号（模式2使用）
        migrations.AddField(
            model_name='control',
            name='tracking_algorithm_code',
            field=models.CharField(
                max_length=50,
                default='',
                blank=True,
                verbose_name='追踪算法编号',
                help_text='算法流程模式2使用的追踪算法'
            ),
        ),

        # 添加分类算法编号（模式3、4使用）
        migrations.AddField(
            model_name='control',
            name='classification_algorithm_code',
            field=models.CharField(
                max_length=50,
                default='',
                blank=True,
                verbose_name='分类算法编号',
                help_text='算法流程模式3、4使用的分类算法'
            ),
        ),

        # 添加检测算法编号（模式1、2、3使用）
        # 原有的 algorithm_code 作为主算法编号，现在语义更明确为检测算法或行为算法
        # 为了向后兼容，保持 algorithm_code 字段不变
        # 新增一个字段明确指定行为算法（所有模式都使用）
        migrations.AddField(
            model_name='control',
            name='behavior_algorithm_code',
            field=models.CharField(
                max_length=50,
                default='',
                blank=True,
                verbose_name='行为算法编号',
                help_text='行为算法编号（模式1-5都使用，模式5时必填）'
            ),
        ),

        # 添加行为算法 API 地址（模式5使用）
        migrations.AddField(
            model_name='control',
            name='behavior_api_url',
            field=models.CharField(
                max_length=300,
                default='',
                blank=True,
                verbose_name='行为算法API地址',
                help_text='模式5时直接调用的行为算法API地址'
            ),
        ),

        # 添加追踪算法配置（模式2使用）
        migrations.AddField(
            model_name='control',
            name='tracking_config',
            field=models.TextField(
                default='{}',
                blank=True,
                verbose_name='追踪算法配置',
                help_text='JSON格式的追踪算法参数配置'
            ),
        ),

        # 添加分类算法配置（模式3、4使用）
        migrations.AddField(
            model_name='control',
            name='classification_config',
            field=models.TextField(
                default='{}',
                blank=True,
                verbose_name='分类算法配置',
                help_text='JSON格式的分类算法参数配置'
            ),
        ),

        # 添加行为算法配置
        migrations.AddField(
            model_name='control',
            name='behavior_config',
            field=models.TextField(
                default='{}',
                blank=True,
                verbose_name='行为算法配置',
                help_text='JSON格式的行为算法参数配置'
            ),
        ),

        # 添加流程模式启用标志（用于平滑迁移）
        migrations.AddField(
            model_name='control',
            name='use_pipeline_mode',
            field=models.BooleanField(
                default=False,
                verbose_name='使用流程模式',
                help_text='是否启用新的算法流程模式（兼容旧配置）'
            ),
        ),
    ]
