from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import time as dt_time
from django.contrib.auth.models import User

class AlgorithmModel(models.Model):
    ALGORITHM_TYPE_CHOICES = [
        (0, '基础算法'),
        (1, '行为算法'),
        (2, '业务算法'),
    ]
    # 基础算法来源类型
    BASIC_SOURCE_CHOICES = [
        ('model', '本地模型'),
        ('api', 'API接口'),
    ]
    # 模型精度选项
    MODEL_PRECISION_CHOICES = [
        ('FP32', 'FP32 (单精度浮点)'),
        ('FP16', 'FP16 (半精度浮点)'),
        ('INT8', 'INT8 (8位整数)'),
    ]
    BEHAVIOR_BUILTIN_CHOICES = [
        ('', '无'),
        ('super', 'SUPER'),
        ('intrusion', '入侵检测'),
        ('loitering', '徘徊检测'),
        ('crossing', '越线检测'),
        ('crosscount', '越线计数'),
        ('crowd', '人群聚集'),
        ('motion', '运动检测'),
        ('stranger', '陌生人报警'),
        ('occlusion', '视频遮挡'),
        ('grayscreen', '灰屏检测'),
        ('corruptscreen', '花屏检测'),
        ('absence', '离岗检测'),
        ('unattended', '无人值守'),
        ('fight', '打架检测'),
        ('fall', '跌倒检测'),
        ('smoke', '吸烟检测'),
        ('phone', '打电话检测'),
    ]
    ALGORITHM_SUBTYPE_CHOICES = [
        ('detection', '检测'),
        ('classification', '分类'),
        ('tracking', '追踪'),
        ('speech', '语音/ASR'),
        ('behavior', '行为'),
        ('ocr', 'OCR'),
    ]
    BEHAVIOR_API_VERSION_CHOICES = [
        (1, 'APIv1（API 完整输出 happen）'),
        (2, 'APIv2（API 输出 detects，本地内置行为后处理）'),
        (3, 'APIv3（API 输出 happen；请求同时携带 full+roi 图片）'),
    ]

    sort = models.IntegerField(verbose_name='排序')
    code = models.CharField(max_length=50, verbose_name='code')
    name = models.CharField(max_length=50, verbose_name='name')
    algorithm_type = models.IntegerField(default=0, choices=ALGORITHM_TYPE_CHOICES, verbose_name='算法类型')
    algorithm_subtype = models.CharField(
        max_length=20,
        default='detection',
        choices=ALGORITHM_SUBTYPE_CHOICES,
        verbose_name='算法子类型',
        help_text='detection=检测, classification=分类, tracking=追踪, speech=语音/ASR, behavior=行为'
    )
    support_direct_api = models.BooleanField(
        default=False,
        verbose_name='支持直接API调用',
        help_text='行为算法是否支持直接接收图片数据（模式5）'
    )
    behavior_api_version = models.IntegerField(
        default=1,
        choices=BEHAVIOR_API_VERSION_CHOICES,
        verbose_name='行为API版本',
        help_text='仅对行为/业务算法的自定义API生效：v1=API直接返回happen；v2=API返回detects，本地内置行为再判定；v3=API直接返回happen，且请求包含额外ROI图片字段'
    )
    basic_source = models.CharField(max_length=20, default='model', choices=BASIC_SOURCE_CHOICES, verbose_name='基础算法来源')
    api_url = models.TextField(verbose_name='api_url', blank=True, default='')
    model_path = models.CharField(max_length=500, verbose_name='模型文件路径', blank=True, default='')
    dll_path = models.CharField(max_length=500, verbose_name='动态库路径', blank=True, default='')
    builtin_behavior = models.CharField(max_length=50, verbose_name='内置行为算法', blank=True, default='')
    object_count = models.IntegerField(verbose_name='object_count')
    object_str = models.TextField(verbose_name='object_str')
    max_control_count = models.IntegerField(default=0, verbose_name='布控数量上限')  # 0表示不限制

    # License Manager: 算法所属授权包（SKU）。默认 core（基础能力）。
    license_package = models.CharField(
        max_length=50,
        default='core',
        verbose_name='授权算法包',
        help_text='License Manager 授权包 SKU（如 core/ppe/traffic_lpr）'
    )

    # ========== 新增算法配置参数 ==========
    # 模型精度配置
    model_precision = models.CharField(
        max_length=10,
        default='FP32',
        choices=MODEL_PRECISION_CHOICES,
        verbose_name='模型精度'
    )

    # 模型并发实例数（基础算法本地推理有效）
    model_concurrency = models.IntegerField(
        default=1,
        verbose_name='模型并发数'
    )

    # 预处理尺寸配置
    input_width = models.IntegerField(
        default=640,
        verbose_name='输入宽度'
    )
    input_height = models.IntegerField(
        default=640,
        verbose_name='输入高度'
    )

    # NMS 阈值配置
    nms_thresh = models.FloatField(
        default=0.45,
        verbose_name='NMS阈值',
        help_text='非极大值抑制阈值，范围 0.0-1.0，默认 0.45'
    )

    # 分类置信度阈值
    conf_thresh = models.FloatField(
        default=0.25,
        verbose_name='置信度阈值',
        help_text='分类置信度阈值，范围 0.0-1.0，默认 0.25'
    )
    # ========================================

    remark = models.TextField(verbose_name='remark', blank=True, default='')
    state = models.IntegerField(verbose_name='state')

    def __repr__(self):
        """处理`repr`。"""
        return self.code

    def __str__(self):
        """处理字符串。"""
        return self.code

    class Meta:
        db_table = 'av_algorithm'
        verbose_name = '算法'
        verbose_name_plural = '算法'


class AlgorithmModelVersion(models.Model):
    algorithm = models.ForeignKey(
        AlgorithmModel,
        on_delete=models.CASCADE,
        related_name="version_rows",
        db_column="algorithm_id",
        verbose_name="算法",
    )
    version_no = models.IntegerField(default=1, verbose_name="版本号")
    version_name = models.CharField(max_length=50, default="", verbose_name="版本名")
    note = models.CharField(max_length=200, blank=True, default="", verbose_name="版本备注")
    is_current = models.BooleanField(default=False, verbose_name="是否当前版本")
    is_gray = models.BooleanField(default=False, verbose_name="是否灰度版本")
    gray_control_codes = models.TextField(blank=True, default="", verbose_name="灰度布控白名单")
    activated_at = models.DateTimeField(null=True, blank=True, verbose_name="激活时间")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    algorithm_type = models.IntegerField(default=0, verbose_name="算法类型")
    algorithm_subtype = models.CharField(max_length=20, default="detection", verbose_name="算法子类型")
    basic_source = models.CharField(max_length=20, default="model", verbose_name="基础算法来源")
    api_url = models.TextField(verbose_name="api_url", blank=True, default="")
    model_path = models.CharField(max_length=500, verbose_name="模型文件路径", blank=True, default="")
    dll_path = models.CharField(max_length=500, verbose_name="动态库路径", blank=True, default="")
    builtin_behavior = models.CharField(max_length=50, verbose_name="内置行为算法", blank=True, default="")
    support_direct_api = models.BooleanField(default=False, verbose_name="支持直接API调用")
    behavior_api_version = models.IntegerField(default=1, verbose_name="行为API版本")
    object_count = models.IntegerField(default=0, verbose_name="目标数量")
    object_str = models.TextField(verbose_name="目标列表", blank=True, default="")
    max_control_count = models.IntegerField(default=0, verbose_name="布控数量上限")
    license_package = models.CharField(max_length=50, default="core", verbose_name="授权算法包")
    model_precision = models.CharField(max_length=10, default="FP32", verbose_name="模型精度")
    model_concurrency = models.IntegerField(default=1, verbose_name="模型并发数")
    input_width = models.IntegerField(default=640, verbose_name="输入宽度")
    input_height = models.IntegerField(default=640, verbose_name="输入高度")
    nms_thresh = models.FloatField(default=0.45, verbose_name="NMS阈值")
    conf_thresh = models.FloatField(default=0.25, verbose_name="置信度阈值")

    def __repr__(self):
        """处理`repr`。"""
        return f"{self.algorithm.code}:{self.version_name}"

    def __str__(self):
        """处理字符串。"""
        return f"{self.algorithm.code}:{self.version_name}"

    class Meta:
        db_table = "av_algorithm_version"
        verbose_name = "算法版本"
        verbose_name_plural = "算法版本"
        unique_together = (("algorithm", "version_no"),)


class UserTotpCredential(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="totp_credential", verbose_name="用户")
    secret_base32 = models.CharField(max_length=128, blank=True, default="", verbose_name="TOTP密钥")
    enabled = models.BooleanField(default=False, verbose_name="是否启用")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __repr__(self):
        """处理`repr`。"""
        return f"totp:{self.user_id}"

    def __str__(self):
        """处理字符串。"""
        return f"totp:{self.user_id}"

    class Meta:
        db_table = "av_user_totp_credential"
        verbose_name = "用户TOTP凭证"
        verbose_name_plural = "用户TOTP凭证"


class UserTotpRecoveryCode(models.Model):
    """
    One-time recovery codes for TOTP 2FA.

    Store only salted hashes (Django password hash format). Plaintext codes are
    shown once at generation time.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="totp_recovery_codes", verbose_name="用户")
    code_hash = models.TextField(verbose_name="恢复码哈希")
    used_at = models.DateTimeField(null=True, blank=True, verbose_name="使用时间")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __repr__(self):
        """处理`repr`。"""
        return f"totp_recovery:{self.user_id}"

    def __str__(self):
        """处理字符串。"""
        return f"totp_recovery:{self.user_id}"

    class Meta:
        db_table = "av_user_totp_recovery_code"
        verbose_name = "用户TOTP恢复码"
        verbose_name_plural = "用户TOTP恢复码"


class UserOidcIdentity(models.Model):
    """
    OIDC identity mapping (provider + sub -> local user).

    Industrial standard:
    - OIDC subject (`sub`) is the stable identifier; do not rely on username/email
      matching for account linking unless explicitly configured.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="oidc_identities", verbose_name="用户")
    provider_id = models.CharField(max_length=64, default="default", verbose_name="OIDC Provider ID")
    subject = models.CharField(max_length=255, verbose_name="OIDC subject(sub)")
    email = models.CharField(max_length=254, blank=True, default="", verbose_name="OIDC email")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __repr__(self):
        """处理`repr`。"""
        return f"oidc:{self.provider_id}:{self.subject}"

    def __str__(self):
        """处理字符串。"""
        return f"oidc:{self.provider_id}:{self.subject}"

    class Meta:
        db_table = "av_user_oidc_identity"
        verbose_name = "用户OIDC身份"
        verbose_name_plural = "用户OIDC身份"
        constraints = [
            models.UniqueConstraint(fields=["provider_id", "subject"], name="uniq_user_oidc_provider_sub"),
        ]
        indexes = [
            models.Index(fields=["provider_id", "subject"], name="idx_oidc_provider_sub"),
            models.Index(fields=["user"], name="idx_oidc_user"),
        ]

class Alarm(models.Model):
    sort = models.IntegerField(verbose_name='排序')
    control_code = models.CharField(max_length=50, verbose_name='布控编号')
    desc = models.CharField(max_length=500, verbose_name='描述', blank=True, default='')
    detail_desc = models.TextField(verbose_name='详细描述', blank=True, default='')

    # 报警分类/级别
    alarm_type = models.CharField(max_length=50, verbose_name='报警类型', default='detection')
    alarm_level = models.IntegerField(
        verbose_name='报警级别',
        default=1,
        help_text='1=低, 2=中, 3=高, 4=紧急',
    )

    # 算法/目标/区域（与 0011_alarm_enhancements.py 保持一致）
    algorithm_code = models.CharField(max_length=50, verbose_name='算法编号', blank=True, default='')
    object_code = models.CharField(max_length=50, verbose_name='目标编号', blank=True, default='')
    recognition_region = models.CharField(max_length=200, verbose_name='检测区域坐标', blank=True, default='')
    region_index = models.IntegerField(
        verbose_name='区域编号',
        default=-1,
        help_text='多区域触发的区域下标（0-based）；-1=未知/不适用',
    )
    class_thresh = models.FloatField(verbose_name='分类阈值', default=0.5)
    overlap_thresh = models.FloatField(verbose_name='重叠阈值', default=0.5)
    min_interval = models.BigIntegerField(verbose_name='最小间隔(毫秒)', default=0)

    # 视频流信息
    stream_code = models.CharField(max_length=50, verbose_name='视频流编号', blank=True, default='')
    stream_app = models.CharField(max_length=50, verbose_name='视频流app', blank=True, default='')
    stream_name = models.CharField(max_length=100, verbose_name='视频流name', blank=True, default='')
    stream_url = models.CharField(max_length=300, verbose_name='拉流地址', blank=True, default='')

    # 存储路径
    video_path = models.CharField(max_length=500, verbose_name='视频存储路径', blank=True, default='')
    image_path = models.CharField(max_length=500, verbose_name='主图存储路径', blank=True, default='')
    extra_images = models.TextField(
        verbose_name='附加图片路径',
        blank=True,
        default='',
        help_text='JSON数组格式，存储多张附加图片路径',
    )
    metadata = models.TextField(
        verbose_name='元数据',
        blank=True,
        default='',
        help_text='JSON格式，存储扩展信息',
    )
    draw_type = models.IntegerField(
        verbose_name='画框类型',
        default=1,
        help_text='1=画框, 0=不画框',
    )

    # 处理状态
    handled = models.BooleanField(verbose_name='是否已处理', default=False)
    handled_time = models.DateTimeField(verbose_name='处理时间', null=True, blank=True)
    handled_by = models.CharField(max_length=100, verbose_name='处理人', blank=True, default='')
    handled_remark = models.TextField(verbose_name='处理备注', blank=True, default='')
    workflow_status = models.CharField(max_length=32, default='new', verbose_name='workflow_status')
    workflow_updated_at = models.DateTimeField(null=True, blank=True, verbose_name='workflow_updated_at')
    workflow_updated_by = models.CharField(max_length=100, blank=True, default='', verbose_name='workflow_updated_by')
    assigned_to = models.CharField(max_length=100, blank=True, default='', verbose_name='assigned_to')
    note_entries = models.TextField(blank=True, default='[]', verbose_name='note_entries')
    create_time = models.DateTimeField(auto_now_add=True,verbose_name='创建时间')
    state = models.IntegerField(verbose_name='状态') # 0 未读

    def __repr__(self):
        """处理`repr`。"""
        return self.desc

    def __str__(self):
        """处理字符串。"""
        return self.desc

    class Meta:
        db_table = 'av_alarm'
        verbose_name = '报警视频'
        verbose_name_plural = '报警视频'
class AlarmFilterPreset(models.Model):
    owner_user_id = models.IntegerField(verbose_name="owner_user_id", db_index=True)
    owner_username = models.CharField(max_length=150, blank=True, default="", verbose_name="owner_username")
    name = models.CharField(max_length=100, verbose_name="name")
    target_mode = models.CharField(max_length=16, default="list", verbose_name="target_mode")
    visibility_scope = models.CharField(max_length=20, default="private", verbose_name="visibility_scope")
    share_permission_key = models.CharField(max_length=100, blank=True, default="", verbose_name="share_permission_key")
    filter_payload = models.TextField(blank=True, default="{}", verbose_name="filter_payload")
    review_tab = models.CharField(max_length=16, blank=True, default="", verbose_name="review_tab")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")
    update_time = models.DateTimeField(auto_now=True, verbose_name="update_time")

    def __repr__(self):
        """处理`repr`。"""
        return self.name

    def __str__(self):
        """处理字符串。"""
        return self.name

    class Meta:
        db_table = "av_alarm_filter_preset"
        verbose_name = "alarm_filter_preset"
        verbose_name_plural = "alarm_filter_preset"
        unique_together = (("owner_user_id", "target_mode", "name"),)
        indexes = [
            models.Index(fields=["owner_user_id", "target_mode", "name"], name="idx_alarm_preset_owner"),
        ]


class Stream(models.Model):
    user_id = models.IntegerField(verbose_name='用户')
    sort = models.IntegerField(verbose_name='排序')
    code = models.CharField(max_length=50, verbose_name='编号')
    app = models.CharField(max_length=50, verbose_name='分组')
    name = models.CharField(max_length=50, verbose_name='名称')
    pull_stream_url = models.CharField(max_length=300, verbose_name='视频流来源')
    pull_stream_type = models.IntegerField(verbose_name='视频流来源类型')
    nickname = models.CharField(max_length=200, verbose_name='视频流昵称')
    remark = models.CharField(max_length=200, verbose_name='备注')
    site_label = models.CharField(max_length=100, verbose_name='站点标签', blank=True, default='')
    floor_label = models.CharField(max_length=100, verbose_name='楼层标签', blank=True, default='')
    forward_state = models.IntegerField(verbose_name='转发状态')  # 默认0, 0:未转发 1:转发中
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    last_update_time = models.DateTimeField(auto_now_add=True, verbose_name='更新时间')
    state = models.IntegerField(verbose_name='状态')

    def __repr__(self):
        """处理`repr`。"""
        return self.name

    def __str__(self):
        """处理字符串。"""
        return self.name

    class Meta:
        db_table = 'av_stream'
        verbose_name = '视频流'
        verbose_name_plural = '视频流'


class StreamTalkbackConfig(models.Model):
    stream_code = models.CharField(max_length=50, unique=True, verbose_name="视频流编号")
    enabled = models.BooleanField(default=False, verbose_name="启用")
    transport_mode = models.CharField(max_length=50, default="webrtc_to_rtsp", verbose_name="传输模式")
    onvif_service_url = models.CharField(max_length=500, blank=True, default="", verbose_name="ONVIF服务地址")
    onvif_username = models.CharField(max_length=200, blank=True, default="", verbose_name="ONVIF用户名")
    onvif_password = models.CharField(max_length=500, blank=True, default="", verbose_name="ONVIF密码")
    profile_token = models.CharField(max_length=200, blank=True, default="", verbose_name="ProfileToken")
    backchannel_uri = models.CharField(max_length=1000, blank=True, default="", verbose_name="回讲地址")
    relay_app = models.CharField(max_length=50, default="talkback", verbose_name="中继应用")
    relay_stream_prefix = models.CharField(max_length=100, blank=True, default="", verbose_name="中继流前缀")
    sample_rate = models.IntegerField(default=16000, verbose_name="采样率")
    codec_hint = models.CharField(max_length=50, default="pcma", verbose_name="编码提示")
    remark = models.TextField(verbose_name="备注", blank=True, default="")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __repr__(self):
        """处理`repr`。"""
        return self.stream_code

    def __str__(self):
        """处理字符串。"""
        return self.stream_code

    class Meta:
        db_table = "av_stream_talkback_config"
        verbose_name = "视频流回讲配置"
        verbose_name_plural = "视频流回讲配置"


class RecordingPlan(models.Model):
    """
    录像计划（定时任务）：
    - 由后台线程周期性检查并触发 start/stop
    - 存储在 storageRootPath/recordings 下（或自定义存储根路径）
    """

    code = models.CharField(max_length=50, unique=True, verbose_name="计划编号")
    name = models.CharField(max_length=100, blank=True, default="", verbose_name="计划名称")
    enabled = models.BooleanField(default=True, verbose_name="启用")

    stream_code = models.CharField(max_length=50, verbose_name="视频流编号")
    stream_url = models.CharField(max_length=500, blank=True, default="", verbose_name="拉流地址(可选)")

    # 每天的起止时间（本地时区）
    start_time = models.TimeField(default=dt_time(0, 0), verbose_name="开始时间")
    end_time = models.TimeField(default=dt_time(23, 59), verbose_name="结束时间")

    # 星期掩码：bit0=周一 ... bit6=周日；默认 127=每天
    days_mask = models.IntegerField(
        default=127,
        verbose_name="星期掩码",
        help_text="bit0=Mon ... bit6=Sun，默认 127=每天",
    )

    record_audio = models.BooleanField(default=False, verbose_name="录音")
    format = models.CharField(
        max_length=10,
        default="mp4",
        verbose_name="录像格式",
        help_text="mp4/ts/flv",
    )

    remark = models.TextField(verbose_name="备注", blank=True, default="")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __repr__(self):
        """处理`repr`。"""
        return self.code

    def __str__(self):
        """处理字符串。"""
        return self.code

    class Meta:
        db_table = "av_recording_plan"
        verbose_name = "录像计划"
        verbose_name_plural = "录像计划"


class TaskPlan(models.Model):
    """
    通用任务计划（定时任务）：
    - 定时执行布控/转发
    - 定时重启软件/系统
    - 间隔扫描离线摄像头（best-effort）
    """

    code = models.CharField(max_length=50, unique=True, verbose_name="计划编号")
    name = models.CharField(max_length=100, blank=True, default="", verbose_name="计划名称")
    enabled = models.BooleanField(default=True, verbose_name="启用")

    # 任务类型：snake_case
    task_type = models.CharField(max_length=50, default="restart_software", verbose_name="任务类型")

    # 调度类型：每天固定时间或固定间隔
    schedule_type = models.CharField(max_length=20, default="daily", verbose_name="调度类型")
    run_time = models.TimeField(null=True, blank=True, verbose_name="执行时间（daily）")
    days_mask = models.IntegerField(
        default=127,
        verbose_name="星期掩码",
        help_text="bit0=Mon ... bit6=Sun，默认 127=每天",
    )
    interval_seconds = models.IntegerField(default=0, verbose_name="间隔秒（interval）")

    # 目标列表（csv 或 json array，best-effort 解析）
    target_codes = models.TextField(blank=True, default="", verbose_name="目标列表")
    # 扩展参数（json string）
    options_json = models.TextField(blank=True, default="", verbose_name="扩展参数JSON")

    last_run_at = models.DateTimeField(null=True, blank=True, verbose_name="上次执行时间")
    last_result_code = models.IntegerField(default=0, verbose_name="上次执行结果码")
    last_result_msg = models.TextField(blank=True, default="", verbose_name="上次执行结果信息")

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __repr__(self):
        """处理`repr`。"""
        return self.code

    def __str__(self):
        """处理字符串。"""
        return self.code

    class Meta:
        db_table = "av_task_plan"
        verbose_name = "任务计划"
        verbose_name_plural = "任务计划"


class Control(models.Model):
    user_id = models.IntegerField(verbose_name='用户')
    sort = models.IntegerField(verbose_name='排序')
    code = models.CharField(max_length=50, verbose_name='编号')

    stream_app = models.CharField(max_length=50, verbose_name='视频流应用')
    stream_name = models.CharField(max_length=100, verbose_name='视频流名称')
    stream_video = models.CharField(max_length=100, verbose_name='视频流视频')
    stream_audio = models.CharField(max_length=100, verbose_name='视频流音频')

    algorithm_code = models.CharField(max_length=50, verbose_name='算法编号')
    object_code = models.CharField(max_length=50, verbose_name='目标编号')
    polygon = models.TextField(
        verbose_name='绘制区域坐标点',
        help_text='多区域格式: region1;region2;... 每个region为归一化坐标 x,y 成对列表（0~1）',
        default='',
    )
    min_interval = models.IntegerField(verbose_name='检测间隔(秒)')
    class_thresh = models.FloatField(verbose_name='分类阈值')
    overlap_thresh = models.FloatField(verbose_name='iou阈值')
    remark = models.CharField(max_length=200, verbose_name='备注')
    patrol_enabled = models.BooleanField(default=False, verbose_name='轮巡启用')

    push_stream = models.BooleanField(verbose_name='是否推流')
    push_stream_app = models.CharField(max_length=50, blank=True, default='', verbose_name='推流应用')
    push_stream_name = models.CharField(max_length=100, blank=True, default='', verbose_name='推流名称')

    # ========== 布控级硬件编解码配额开关（v4.20.1） ==========
    enable_hw_decode = models.BooleanField(
        default=False,
        verbose_name="启用硬解码配额",
        help_text="仅用于硬件解码路数配额/调度；不启用时不占用 maxHardwareDecodeChannels",
    )
    enable_hw_encode = models.BooleanField(
        default=False,
        verbose_name="启用硬编码配额",
        help_text="仅用于硬件编码路数配额/调度；不启用时不占用 maxHardwareEncodeChannels",
    )
    # ================================================

    # ========== 推流视频质量配置 ==========
    # 推流视频编码器
    push_video_codec = models.CharField(
        max_length=20,
        default='h264',
        verbose_name='推流视频编码器',
        help_text='视频编码器: h264, h265, vp8, vp9'
    )

    # 推流码率 (kbps)
    push_video_bitrate = models.IntegerField(
        default=2000,
        verbose_name='推流码率(kbps)',
        help_text='视频码率，单位kbps，默认2000 (2Mbps)'
    )

    # 推流帧率 (fps)
    push_video_fps = models.IntegerField(
        default=25,
        verbose_name='推流帧率(fps)',
        help_text='视频帧率，建议10-30fps，默认25'
    )

    # 推流分辨率宽度
    push_video_width = models.IntegerField(
        default=1280,
        verbose_name='推流宽度',
        help_text='推流视频宽度，默认1280'
    )

    # 推流分辨率高度
    push_video_height = models.IntegerField(
        default=720,
        verbose_name='推流高度',
        help_text='推流视频高度，默认720'
    )

    # 关键帧间隔 (GOP)
    push_video_gop = models.IntegerField(
        default=50,
        verbose_name='关键帧间隔(GOP)',
        help_text='关键帧间隔，默认50帧'
    )
    # ========================================

    # ========== 基础算法检测模式配置 ==========
    basic_algo_detect_mode = models.IntegerField(
        default=0,
        verbose_name='基础算法检测模式',
        help_text='0=自由竞争（默认）, 1=固定间隔帧, 2=固定间隔秒'
    )
    basic_algo_detect_interval = models.IntegerField(
        default=1,
        verbose_name='检测间隔值',
        help_text='间隔值（帧数或毫秒数，根据检测模式决定）'
    )
    # ========================================

    # ========== 布控级跳帧解码（v4.623） ==========
    decode_stride = models.IntegerField(
        default=1,
        verbose_name="跳帧解码间隔",
        help_text="1=全帧解码；N=每N帧解码一次（降低CPU消耗，但可能降低推流/报警帧率）",
    )
    # ========================================

    # ========== 布控扩展参数：拉流/推流性能调优（v4.644） ==========
    pull_frequency = models.IntegerField(
        default=0,
        verbose_name="拉流频率(帧/秒)",
        help_text="0=不启用；>0 表示最多每秒解码/处理 N 帧（可降低 CPU 消耗）",
    )
    ps_effect_min_fps = models.IntegerField(
        default=0,
        verbose_name="推流最低FPS",
        help_text="仅推流布控生效：推流效果/画面刷新最低 FPS（0=不限制）；与 pull_frequency 取 max",
    )
    # ========================================

    # ========== OSD 配置 ==========
    osd_enabled = models.BooleanField(
        default=False,
        verbose_name='启用OSD',
        help_text='是否在推流视频上叠加文字信息'
    )
    osd_text = models.CharField(
        max_length=200,
        default='',
        blank=True,
        verbose_name='OSD文字内容',
        help_text='支持中文，可使用变量：{time}, {stream_name}, {algorithm_name}'
    )
    osd_position = models.CharField(
        max_length=20,
        default='top-left',
        verbose_name='OSD位置',
        help_text='top-left, top-right, bottom-left, bottom-right, custom'
    )
    osd_x = models.IntegerField(
        default=10,
        verbose_name='OSD X坐标',
        help_text='自定义位置时使用，像素值'
    )
    osd_y = models.IntegerField(
        default=30,
        verbose_name='OSD Y坐标',
        help_text='自定义位置时使用，像素值'
    )
    osd_font_size = models.IntegerField(
        default=24,
        verbose_name='OSD字体大小',
        help_text='字体大小，默认24'
    )
    osd_font_color = models.CharField(
        max_length=20,
        default='255,255,255',
        verbose_name='OSD字体颜色',
        help_text='RGB格式，如：255,255,255（白色）'
    )
    osd_bg_enabled = models.BooleanField(
        default=True,
        verbose_name='启用OSD背景',
        help_text='是否显示半透明黑色背景'
    )

    # ========== OSD 贴图配置（PNG alpha，稳定支持中文/Logo） ==========
    osd_image_path = models.CharField(
        max_length=500,
        default='',
        blank=True,
        verbose_name='OSD贴图路径',
        help_text='贴图路径（建议 png，支持 alpha）；为空表示不贴图'
    )
    osd_image_x = models.IntegerField(
        default=10,
        verbose_name='OSD贴图X坐标',
        help_text='贴图左上角 X 坐标（像素）'
    )
    osd_image_y = models.IntegerField(
        default=10,
        verbose_name='OSD贴图Y坐标',
        help_text='贴图左上角 Y 坐标（像素）'
    )
    osd_image_scale = models.FloatField(
        default=1.0,
        verbose_name='OSD贴图缩放',
        help_text='缩放倍数（>0），默认 1.0'
    )
    osd_image_alpha = models.FloatField(
        default=1.0,
        verbose_name='OSD贴图透明度',
        help_text='全局透明度（0~1），默认 1.0'
    )

    # ========== Algo/FPS overlay 坐标（画面左侧算法名与FPS） ==========
    osd_algo_x = models.IntegerField(
        default=20,
        verbose_name="算法名起点X",
        help_text="画面叠加：算法名文字起点 X 坐标（像素），默认 20",
    )
    osd_algo_y = models.IntegerField(
        default=80,
        verbose_name="算法名起点Y",
        help_text="画面叠加：算法名文字起点 Y 坐标（像素），默认 80",
    )
    osd_fps_x = models.IntegerField(
        default=20,
        verbose_name="FPS起点X",
        help_text="画面叠加：FPS文字起点 X 坐标（像素），默认 20",
    )
    osd_fps_y = models.IntegerField(
        default=140,
        verbose_name="FPS起点Y",
        help_text="画面叠加：FPS文字起点 Y 坐标（像素），默认 140",
    )
    # ==============================================================
    # ========================================

    # ========== OSD 字体厚度（v4.627） ==========
    osd_font_thickness = models.IntegerField(
        default=2,
        verbose_name="OSD字体厚度",
        help_text="OpenCV putText 的 thickness 参数（默认 2）",
    )
    # ========================================

    # ========== 算法流绘制样式（v4.627） ==========
    OVERLAY_COLOR_DEFAULT = "255,0,0"
    OVERLAY_COLOR_HELP_TEXT = "RGB 格式，如：255,0,0（红色）"
    overlay_region_color = models.CharField(
        max_length=20,
        default=OVERLAY_COLOR_DEFAULT,
        verbose_name="区域框颜色",
        help_text=OVERLAY_COLOR_HELP_TEXT,
    )
    overlay_region_thickness = models.IntegerField(
        default=4,
        verbose_name="区域框厚度",
        help_text="区域多边形/矩形线宽（像素），默认 4",
    )
    overlay_line_color = models.CharField(
        max_length=20,
        default=OVERLAY_COLOR_DEFAULT,
        verbose_name="线段颜色",
        help_text=OVERLAY_COLOR_HELP_TEXT,
    )
    overlay_line_thickness = models.IntegerField(
        default=4,
        verbose_name="线段厚度",
        help_text="线段线宽（像素），默认 4",
    )
    overlay_detect_color = models.CharField(
        max_length=20,
        default=OVERLAY_COLOR_DEFAULT,
        verbose_name="检测目标颜色",
        help_text=OVERLAY_COLOR_HELP_TEXT,
    )
    overlay_detect_thickness = models.IntegerField(
        default=2,
        verbose_name="检测目标厚度",
        help_text="目标框/文字线宽（像素），默认 2",
    )
    overlay_detect_font_size = models.IntegerField(
        default=48,
        verbose_name="检测目标字体大小",
        help_text="OpenCV putText 字体大小（基准 24，默认 48 ≈ 2.0 倍）",
    )
    # ========================================

    # ========== 层级算法配置 ==========
    enable_hierarchical_algorithm = models.BooleanField(
        default=False,
        verbose_name='启用层级算法',
        help_text='是否启用层级算法（检测后进行二级处理）'
    )
    secondary_algorithm_code = models.CharField(
        max_length=50,
        default='',
        blank=True,
        verbose_name='二级算法编号',
        help_text='二级算法编号（可选）'
    )
    secondary_api_url = models.CharField(
        max_length=200,
        default='',
        blank=True,
        verbose_name='二级算法API地址',
        help_text='二级算法API地址（可选）'
    )
    secondary_conf_thresh = models.FloatField(
        default=0.25,
        verbose_name='二级算法置信度阈值',
        help_text='二级算法置信度阈值，默认0.25'
    )
    # ========================================

    # ========== 区域绘制类型配置 ==========
    draw_type = models.CharField(
        max_length=20,
        default='polygon',
        verbose_name='绘制类型',
        help_text='polygon=多边形区域, line=越线检测'
    )
    # ========================================

    # ========== 越线检测配置 ==========
    line_coordinates = models.CharField(
        max_length=100,
        default='',
        blank=True,
        verbose_name='越线检测线段坐标',
        help_text='格式：x1,y1,x2,y2（归一化坐标0-1）'
    )
    line_violation_direction = models.CharField(
        max_length=20,
        default='both',
        verbose_name='违规方向',
        help_text='both=双向, forward=正向, backward=反向'
    )
    enable_tracking = models.BooleanField(
        default=False,
        verbose_name='启用目标追踪',
        help_text='越线检测需要启用追踪功能'
    )
    # ========================================

    # ========== 算法流程模式配置 ==========
    use_pipeline_mode = models.BooleanField(
        default=False,
        verbose_name='使用流程模式',
        help_text='是否启用新的算法流程模式（兼容旧配置）'
    )
    algorithm_pipeline_mode = models.IntegerField(
        default=1,
        verbose_name='算法流程模式',
        help_text='1=检测>>行为, 2=检测>>追踪>>行为, 3=检测>>分类>>行为, 4=分类>>行为, 5=行为'
    )
    tracking_algorithm_code = models.CharField(
        max_length=50,
        default='',
        blank=True,
        verbose_name='追踪算法编号',
        help_text='算法流程模式2使用的追踪算法'
    )
    classification_algorithm_code = models.CharField(
        max_length=50,
        default='',
        blank=True,
        verbose_name='分类算法编号',
        help_text='算法流程模式3、4使用的分类算法'
    )
    feature_algorithm_code = models.CharField(
        max_length=50,
        default='',
        blank=True,
        verbose_name='特征算法编号',
        help_text='算法流程模式7/9使用的特征算法（可选：FaceNet/ReID等）'
    )
    behavior_algorithm_code = models.CharField(
        max_length=50,
        default='',
        blank=True,
        verbose_name='行为算法编号',
        help_text='行为算法编号（模式1-5都使用，模式5时必填）'
    )
    behavior_api_url = models.CharField(
        max_length=300,
        default='',
        blank=True,
        verbose_name='行为算法API地址',
        help_text='模式5时直接调用的行为算法API地址'
    )

    # ========== 布控扩展参数：大模型分析提示词（v4.644） ==========
    analysis_prompt = models.TextField(
        default="",
        blank=True,
        verbose_name="大模型提示词(中文)",
        help_text="流程模式5/大模型分析：每个布控可设置独立提示词（启动时注入 behaviorConfig 下发给行为 API）",
    )
    # ========================================

    tracking_config = models.TextField(
        default='{}',
        blank=True,
        verbose_name='追踪算法配置',
        help_text='JSON格式的追踪算法参数配置'
    )
    classification_config = models.TextField(
        default='{}',
        blank=True,
        verbose_name='分类算法配置',
        help_text='JSON格式的分类算法参数配置'
    )
    feature_config = models.TextField(
        default='{}',
        blank=True,
        verbose_name='特征算法配置',
        help_text='JSON格式的特征算法参数配置'
    )
    behavior_config = models.TextField(
        default='{}',
        blank=True,
        verbose_name='行为算法配置',
        help_text='JSON格式的行为算法参数配置'
    )
    # ========================================

    # 报警配置
    alarm_sound_id = models.IntegerField(default=0, verbose_name='报警声音ID')
    alarm_video_type = models.CharField(max_length=20, default='mp4', verbose_name='报警视频类型')
    alarm_image_count = models.IntegerField(default=3, verbose_name='报警图片数量')
    alarm_cover_position = models.CharField(
        max_length=20,
        default='front',
        verbose_name='报警封面位置',
        help_text='front=触发帧, middle=中间帧, back=最后帧, custom=自定义帧序号'
    )
    alarm_cover_custom_index = models.IntegerField(
        default=0,
        verbose_name='报警封面自定义帧序号',
        help_text='alarm_cover_position=custom 时生效；0 表示使用默认策略'
    )
    alarm_image_draw_mode = models.CharField(
        max_length=20,
        default='boxed',
        verbose_name='报警图片画框模式',
        help_text='boxed=画框, clean=不画框, both=同时保存画框和不画框图片'
    )
    force_frame_alarm = models.BooleanField(
        default=False,
        verbose_name="强制逐帧报警",
        help_text="开启后：每个触发帧都会生成报警记录（会显著增加存储/网络压力，仅建议用于调试/采样场景）",
    )

    state = models.IntegerField(default=0,verbose_name="布控状态") # 0：未布控  1：布控中  5：布控中断

    create_time = models.DateTimeField(auto_now_add=True,verbose_name='创建时间')
    last_update_time = models.DateTimeField(auto_now_add=True,verbose_name='更新时间')

    def _normalize_push_stream_fields(self):
        """执行归一化`push`流字段。"""
        if self.push_stream_app is None:
            self.push_stream_app = ''
        if self.push_stream_name is None:
            self.push_stream_name = ''

    def save(self, *args, **kwargs):
        """保存相关数据。"""
        self._normalize_push_stream_fields()
        return super().save(*args, **kwargs)

    def __repr__(self):
        """处理`repr`。"""
        return self.code

    def __str__(self):
        """处理字符串。"""
        return self.code

    class Meta:
        db_table = 'av_control'
        verbose_name = '布控'
        verbose_name_plural = '布控'


class SystemConfig(models.Model):
    key = models.CharField(max_length=100, unique=True, verbose_name='配置键')
    value = models.TextField(verbose_name='配置值')
    remark = models.CharField(max_length=200, verbose_name='备注', blank=True, default='')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    def __repr__(self):
        """处理`repr`。"""
        return self.key

    def __str__(self):
        """处理字符串。"""
        return self.key

    class Meta:
        db_table = 'av_system_config'
        verbose_name = '系统配置'
        verbose_name_plural = '系统配置'


class AlarmSound(models.Model):
    name = models.CharField(max_length=100, verbose_name='名称')
    file_path = models.CharField(max_length=500, verbose_name='文件路径')
    duration = models.FloatField(default=0, verbose_name='时长(秒)')
    is_default = models.BooleanField(default=False, verbose_name='是否默认')
    remark = models.CharField(max_length=200, verbose_name='备注', blank=True, default='')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    state = models.IntegerField(default=1, verbose_name='状态')  # 1:正常 0:禁用

    def __repr__(self):
        """处理`repr`。"""
        return self.name

    def __str__(self):
        """处理字符串。"""
        return self.name

    class Meta:
        db_table = 'av_alarm_sound'
        verbose_name = '报警声音'
        verbose_name_plural = '报警声音'


class ControlLog(models.Model):
    control_code = models.CharField(max_length=50, verbose_name='布控编号', blank=True, default='')
    action = models.CharField(max_length=50, verbose_name='动作')
    result_code = models.IntegerField(default=0, verbose_name='结果码')
    result_msg = models.TextField(verbose_name='结果信息', blank=True, default='')
    operator = models.CharField(max_length=100, verbose_name='操作人', blank=True, default='')
    detail = models.TextField(verbose_name='详情', blank=True, default='')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    def __repr__(self):
        """处理`repr`。"""
        return self.control_code

    def __str__(self):
        """处理字符串。"""
        return self.control_code

    class Meta:
        db_table = 'av_control_log'
        verbose_name = '布控日志'
        verbose_name_plural = '布控日志'


class AlgorithmPipeline(models.Model):
    """自定义算法流程"""
    code = models.CharField(max_length=50, unique=True, verbose_name='流程编号')
    name = models.CharField(max_length=100, verbose_name='流程名称')
    description = models.TextField(blank=True, default='', verbose_name='描述')

    # 流程图数据 (JSON 格式)
    nodes = models.TextField(verbose_name='节点数据 JSON', blank=True, default='[]')
    edges = models.TextField(verbose_name='连线数据 JSON', blank=True, default='[]')

    # 元数据
    user_id = models.IntegerField(default=0, verbose_name='创建用户')
    is_template = models.BooleanField(default=False, verbose_name='是否模板')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')

    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    def __repr__(self):
        """处理`repr`。"""
        return self.name

    def __str__(self):
        """处理字符串。"""
        return self.name

    class Meta:
        db_table = 'av_algorithm_pipeline'
        verbose_name = '算法流程'
        verbose_name_plural = '算法流程'


class LicenseState(models.Model):
    """
    当前启用的授权状态（License Manager v1）

    - 存储 license 原文（JSON 文本）
    - 存储解析后的关键字段，便于快速展示与校验
    """

    license_json = models.TextField(verbose_name='license原文(JSON)', blank=True, default='')

    license_id = models.CharField(max_length=100, verbose_name='license_id', blank=True, default='')
    customer = models.CharField(max_length=200, verbose_name='customer', blank=True, default='')
    cluster_id = models.CharField(max_length=128, verbose_name='cluster_id', blank=True, default='')

    not_before = models.DateTimeField(verbose_name='not_before', null=True, blank=True)
    not_after = models.DateTimeField(verbose_name='not_after', null=True, blank=True)

    max_active_controls = models.IntegerField(default=0, verbose_name='最大活跃路数')
    max_nodes = models.IntegerField(default=0, verbose_name='最大节点数')
    packages_json = models.TextField(verbose_name='算法包列表(JSON)', blank=True, default='[]')
    package_limits_json = models.TextField(verbose_name='算法包限额(JSON)', blank=True, default='{}')

    valid = models.BooleanField(default=False, verbose_name='是否有效')
    last_error_code = models.CharField(max_length=50, verbose_name='最后错误码', blank=True, default='')
    last_error_message = models.TextField(verbose_name='最后错误信息', blank=True, default='')

    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'av_license_state'
        verbose_name = '授权状态'
        verbose_name_plural = '授权状态'


class LicenseLease(models.Model):
    """
    授权租约（浮动池路数占用凭证）

    一个 lease 对应：
    - 某个 node_id
    - 某个 stream_code（摄像头/视频流槽位；为空时回退到 control_code 兼容旧版本）
    - 某个 control_code（Analyzer 运行中的布控）
    - 某个 algorithm_code（用于校验算法包）
    """

    lease_id = models.CharField(max_length=64, verbose_name='lease_id', unique=True)
    node_id = models.CharField(max_length=100, verbose_name='node_id')
    stream_code = models.CharField(max_length=50, verbose_name='视频流编号', blank=True, default='')
    control_code = models.CharField(max_length=50, verbose_name='布控编号')
    algorithm_code = models.CharField(max_length=50, verbose_name='算法编号')
    package = models.CharField(max_length=50, verbose_name='算法包', blank=True, default='core')

    expires_at = models.DateTimeField(verbose_name='过期时间')
    released_at = models.DateTimeField(verbose_name='释放时间', null=True, blank=True)

    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'av_license_lease'
        verbose_name = '授权租约'
        verbose_name_plural = '授权租约'


class ApiKey(models.Model):
    """
    DB-managed API keys (industrial delivery).

    Use-case:
    - Replace the single global BEACON_OPEN_API_TOKEN with multiple keys that
      can be created/rotated/revoked and scoped.
    - Only store hash (never store plaintext token).
    """

    name = models.CharField(max_length=100, verbose_name="名称")

    # A short identifier derived from plaintext token for UI/ops troubleshooting.
    token_prefix = models.CharField(max_length=16, verbose_name="token前缀", blank=True, default="")

    # sha256 hex digest of (pepper + token)
    token_hash = models.CharField(max_length=64, verbose_name="token_hash", unique=True)

    # JSON array of scopes, e.g. ["ops", "openapi"]
    scopes_json = models.TextField(verbose_name="scopes(JSON)", blank=True, default="[]")

    # Optional built-in gateway quotas. 0 means "use global settings".
    rate_limit_per_minute = models.IntegerField(default=0, verbose_name="每分钟限流额度")
    burst_limit = models.IntegerField(default=0, verbose_name="突发额度")

    enabled = models.BooleanField(default=True, verbose_name="是否启用")
    expires_at = models.DateTimeField(verbose_name="过期时间", null=True, blank=True)
    revoked_at = models.DateTimeField(verbose_name="吊销时间", null=True, blank=True)

    last_used_at = models.DateTimeField(verbose_name="最后使用时间", null=True, blank=True)

    created_by = models.CharField(max_length=100, verbose_name="创建人", blank=True, default="")
    remark = models.TextField(verbose_name="备注", blank=True, default="")

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "av_api_key"
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"
        indexes = [
            models.Index(fields=["token_hash"], name="idx_api_key_hash"),
            models.Index(fields=["enabled", "expires_at"], name="idx_api_key_enabled_exp"),
        ]


class LoginLockout(models.Model):
    """
    Login lockout state (industrial security).

    Keyed by (username, source_ip) to reduce brute-force attempts while keeping
    behavior explainable for admins.
    """

    username = models.CharField(max_length=150, verbose_name="用户名")
    source_ip = models.CharField(max_length=64, verbose_name="来源IP", blank=True, default="")

    failures = models.IntegerField(default=0, verbose_name="失败次数")
    first_failure_at = models.DateTimeField(verbose_name="首次失败时间", null=True, blank=True)
    last_failure_at = models.DateTimeField(verbose_name="最后失败时间", null=True, blank=True)
    locked_until = models.DateTimeField(verbose_name="锁定至", null=True, blank=True)

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "av_login_lockout"
        verbose_name = "登录锁定"
        verbose_name_plural = "登录锁定"
        constraints = [
            models.UniqueConstraint(fields=["username", "source_ip"], name="uniq_login_lockout_user_ip"),
        ]
        indexes = [
            models.Index(fields=["locked_until"], name="idx_login_lockout_until"),
            models.Index(fields=["username", "source_ip"], name="idx_login_lockout_user_ip"),
        ]


class OpsAuditLog(models.Model):
    """
    运维审计日志（工业交付：可追责、可导出）

    v1 范围：
    - license.import
    - license.lease.acquire / renew / release
    """

    event_type = models.CharField(max_length=50, verbose_name="事件类型")
    ok = models.BooleanField(default=False, verbose_name="是否成功")

    operator = models.CharField(max_length=100, verbose_name="操作人", blank=True, default="")
    source_ip = models.CharField(max_length=64, verbose_name="来源IP", blank=True, default="")

    node_id = models.CharField(max_length=100, verbose_name="node_id", blank=True, default="")
    control_code = models.CharField(max_length=50, verbose_name="布控编号", blank=True, default="")
    algorithm_code = models.CharField(max_length=50, verbose_name="算法编号", blank=True, default="")
    lease_id = models.CharField(max_length=64, verbose_name="lease_id", blank=True, default="")

    error_code = models.CharField(max_length=50, verbose_name="错误码", blank=True, default="")
    error_message = models.TextField(verbose_name="错误信息", blank=True, default="")
    detail_json = models.TextField(verbose_name="详情(JSON)", blank=True, default="")

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "av_ops_audit_log"
        verbose_name = "运维审计日志"
        verbose_name_plural = "运维审计日志"
        indexes = [
            models.Index(fields=["event_type", "create_time"], name="idx_ops_audit_evt_time"),
            models.Index(fields=["ok", "create_time"], name="idx_ops_audit_ok_time"),
        ]


class AlarmEventOutbox(models.Model):
    """
    报警事件 Outbox（工业交付：保证事件不丢）

    设计原则：
    - 一个 alarm.created 事件会为每个启用的 sink 生成 1 条 outbox 记录（webhook/cloud）
    - 通过 status/attempts/next_retry_at 实现至少一次投递（at-least-once）
    - 接收方用 event_id 幂等去重
    """

    STATUS_CHOICES = [
        ("pending", "pending"),
        ("sending", "sending"),
        ("sent", "sent"),
        ("failed", "failed"),
    ]

    event_id = models.CharField(max_length=64, verbose_name="event_id")
    sink_type = models.CharField(max_length=20, verbose_name="sink_type")  # webhook/cloud

    schema = models.CharField(max_length=50, verbose_name="schema", default="beacon.event.v1")
    event_type = models.CharField(max_length=50, verbose_name="event_type", default="alarm.created")
    event_source = models.CharField(max_length=50, verbose_name="event_source", blank=True, default="")

    alarm_id = models.IntegerField(default=0, verbose_name="alarm_id")
    control_code = models.CharField(max_length=50, verbose_name="control_code", blank=True, default="")

    payload_json = models.TextField(verbose_name="payload_json", blank=True, default="")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name="status", default="pending")
    attempts = models.IntegerField(default=0, verbose_name="attempts")
    next_retry_at = models.DateTimeField(null=True, blank=True, verbose_name="next_retry_at")
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="sent_at")

    last_error = models.TextField(verbose_name="last_error", blank=True, default="")
    last_http_status = models.IntegerField(default=0, verbose_name="last_http_status")

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "av_alarm_event_outbox"
        verbose_name = "报警事件Outbox"
        verbose_name_plural = "报警事件Outbox"
        constraints = [
            models.UniqueConstraint(fields=["event_id", "sink_type"], name="uniq_alarm_event_outbox_event_sink"),
        ]
        indexes = [
            models.Index(fields=["status", "next_retry_at"], name="idx_alarm_outbox_status_retry"),
            models.Index(fields=["alarm_id"], name="idx_alarm_outbox_alarm_id"),
        ]


class CloudTenant(models.Model):
    name = models.CharField(max_length=100, verbose_name="租户名称")
    slug = models.CharField(max_length=100, verbose_name="租户标识", unique=True)
    enabled = models.BooleanField(default=True, verbose_name="是否启用")
    branding_json = models.TextField(verbose_name="branding_json", blank=True, default="")

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "av_cloud_tenant"
        verbose_name = "云租户"
        verbose_name_plural = "云租户"


class CloudProject(models.Model):
    tenant = models.ForeignKey(CloudTenant, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=100, verbose_name="项目名称")
    enabled = models.BooleanField(default=True, verbose_name="是否启用")

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "av_cloud_project"
        verbose_name = "云项目"
        verbose_name_plural = "云项目"


class CloudEdgeCluster(models.Model):
    project = models.ForeignKey(CloudProject, on_delete=models.CASCADE, related_name="edge_clusters")
    name = models.CharField(max_length=100, verbose_name="集群名称")
    edge_token_hash = models.CharField(max_length=128, verbose_name="edge_token_hash", blank=True, default="")
    edge_admin_base_url = models.CharField(max_length=500, verbose_name="edge_admin_base_url", blank=True, default="")
    edge_openapi_token = models.TextField(verbose_name="edge_openapi_token", blank=True, default="")
    node_code = models.CharField(max_length=100, verbose_name="node_code", blank=True, default="")
    rollout_channel = models.CharField(max_length=50, verbose_name="rollout_channel", blank=True, default="")
    rollout_status = models.CharField(max_length=50, verbose_name="rollout_status", blank=True, default="")
    rollout_target_version = models.CharField(max_length=100, verbose_name="rollout_target_version", blank=True, default="")
    rollout_error = models.TextField(verbose_name="rollout_error", blank=True, default="")
    rollout_node_versions_json = models.TextField(verbose_name="rollout_node_versions_json", blank=True, default="")
    remark = models.TextField(verbose_name="remark", blank=True, default="")
    enabled = models.BooleanField(default=True, verbose_name="是否启用")
    last_seen_at = models.DateTimeField(verbose_name="最后上报时间", null=True, blank=True)

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "av_cloud_edge_cluster"
        verbose_name = "云边缘集群"
        verbose_name_plural = "云边缘集群"


class CloudAlarmEvent(models.Model):
    edge_cluster = models.ForeignKey(CloudEdgeCluster, on_delete=models.CASCADE, related_name="alarm_events")
    event_id = models.CharField(max_length=64, verbose_name="event_id")

    event_type = models.CharField(max_length=50, verbose_name="event_type", blank=True, default="alarm.created")
    event_source = models.CharField(max_length=50, verbose_name="event_source", blank=True, default="")

    timestamp = models.DateTimeField(verbose_name="事件时间", null=True, blank=True)
    node_code = models.CharField(max_length=100, verbose_name="node_code", blank=True, default="")
    control_code = models.CharField(max_length=50, verbose_name="control_code", blank=True, default="")
    desc = models.TextField(verbose_name="desc", blank=True, default="")

    payload_json = models.TextField(verbose_name="payload_json", blank=True, default="")

    image_bucket = models.CharField(max_length=200, verbose_name="image_bucket", blank=True, default="")
    image_key = models.CharField(max_length=500, verbose_name="image_key", blank=True, default="")
    image_content_type = models.CharField(max_length=100, verbose_name="image_content_type", blank=True, default="")

    received_at = models.DateTimeField(verbose_name="接收时间", default=timezone.now)

    class Meta:
        db_table = "av_cloud_alarm_event"
        verbose_name = "云端告警事件"
        verbose_name_plural = "云端告警事件"
        constraints = [
            models.UniqueConstraint(fields=["edge_cluster", "event_id"], name="uniq_cloud_alarm_edge_event"),
        ]
        indexes = [
            models.Index(fields=["received_at"], name="idx_cloud_alarm_received"),
            models.Index(fields=["edge_cluster"], name="idx_cloud_alarm_edge"),
        ]


class CloudRole(models.Model):
    """
    Cloud tenant-scoped role definition (RBAC).

    permissions_json:
      JSON object mapping permission keys to boolean.
      e.g. {"cloud.alarms.view": true, "cloud.edge_clusters.manage": false}
    """

    tenant = models.ForeignKey(CloudTenant, on_delete=models.CASCADE, related_name="roles")
    key = models.CharField(max_length=50, verbose_name="key")
    name = models.CharField(max_length=100, verbose_name="name")
    enabled = models.BooleanField(default=True, verbose_name="是否启用")
    permissions_json = models.TextField(verbose_name="permissions_json", blank=True, default="")

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "av_cloud_role"
        verbose_name = "云角色"
        verbose_name_plural = "云角色"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="uniq_cloud_role_tenant_key"),
        ]
        indexes = [
            models.Index(fields=["tenant", "key"], name="idx_cloud_role_tenant_key"),
        ]


class CloudUserMembership(models.Model):
    """
    Cloud tenant membership for a Django User.

    resource_scope_json:
      Optional resource-level scope for the membership.
      Example: {"edge_cluster_ids": [1,2,3]}
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cloud_memberships")
    tenant = models.ForeignKey(CloudTenant, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(CloudRole, on_delete=models.SET_NULL, null=True, blank=True, related_name="memberships")

    enabled = models.BooleanField(default=True, verbose_name="是否启用")
    is_default = models.BooleanField(default=False, verbose_name="是否默认租户")
    resource_scope_json = models.TextField(verbose_name="resource_scope_json", blank=True, default="")

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "av_cloud_user_membership"
        verbose_name = "云成员"
        verbose_name_plural = "云成员"
        constraints = [
            models.UniqueConstraint(fields=["user", "tenant"], name="uniq_cloud_membership_user_tenant"),
        ]
        indexes = [
            models.Index(fields=["user", "tenant"], name="idx_cudmem_user_tenant"),
            models.Index(fields=["tenant", "enabled"], name="idx_cudmem_tenant_enabled"),
        ]


class UserPermission(models.Model):
    """
    用户权限配置（工业交付：可配置、可审计）

    - 仅用于 Beacon Admin Web 侧的“功能模块访问控制”（best-effort）
    - is_staff/is_superuser 仍然视为全权限
    - permissions_json 格式：JSON object，key=permission_key，value=true/false
      例如：{"streams": true, "system": false}
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="beacon_permission")
    permissions_json = models.TextField(verbose_name="permissions_json", blank=True, default="")

    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "av_user_permission"
        verbose_name = "用户权限"
        verbose_name_plural = "用户权限"


class ConfigHistorySnapshot(models.Model):
    scope = models.CharField(max_length=50, default="system", verbose_name="scope")
    change_type = models.CharField(max_length=100, default="system.save", verbose_name="change_type")
    actor = models.CharField(max_length=150, blank=True, default="", verbose_name="actor")
    summary = models.CharField(max_length=200, blank=True, default="", verbose_name="summary")
    snapshot_json = models.TextField(verbose_name="snapshot_json", blank=True, default="")
    diff_json = models.TextField(verbose_name="diff_json", blank=True, default="")
    rollback_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rollback_children",
        verbose_name="rollback_of",
    )
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "av_config_history_snapshot"
        verbose_name = "配置历史快照"
        verbose_name_plural = "配置历史快照"
        indexes = [
            models.Index(fields=["scope", "create_time"], name="idx_cfg_hist_scope_time"),
        ]


class DigitalHumanJwtAccount(models.Model):
    account_uuid = models.CharField(max_length=64, unique=True, verbose_name="account_uuid")
    project_name = models.CharField(max_length=120, blank=True, default="", verbose_name="project_name")
    tenant_name = models.CharField(max_length=120, unique=True, verbose_name="tenant_name")
    secret_hash = models.CharField(max_length=64, verbose_name="secret_hash")
    secret_mask = models.CharField(max_length=64, blank=True, default="", verbose_name="secret_mask")
    token_ttl_minutes = models.IntegerField(default=30, verbose_name="token_ttl_minutes")
    credential_version = models.IntegerField(default=1, verbose_name="credential_version")
    enabled = models.BooleanField(default=True, verbose_name="enabled")
    last_token_issued_at = models.DateTimeField(null=True, blank=True, verbose_name="last_token_issued_at")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")
    update_time = models.DateTimeField(auto_now=True, verbose_name="update_time")

    class Meta:
        db_table = "dh_jwt_account"
        verbose_name = "Digital Human JWT Account"
        verbose_name_plural = "Digital Human JWT Accounts"
        indexes = [
            models.Index(fields=["tenant_name"], name="idx_dhjwt_tenant"),
            models.Index(fields=["enabled"], name="idx_dhjwt_enabled"),
        ]


class DigitalHumanDevice(models.Model):
    device_code = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        default=None,
        unique=True,
        verbose_name="device_code",
    )
    agent_device_id = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        default=None,
        unique=True,
        verbose_name="agent_device_id",
    )
    machine_code = models.CharField(max_length=64, unique=True, verbose_name="machine_code")
    machine_mac = models.CharField(max_length=128, blank=True, default="", verbose_name="machine_mac")
    tenant_name = models.CharField(max_length=120, blank=True, default="", verbose_name="tenant_name")
    registered_by_jwt_account_uuid = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name="registered_by_jwt_account_uuid",
    )
    registered_by_jwt_tenant_name = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="registered_by_jwt_tenant_name",
    )
    authorization_enabled = models.BooleanField(default=False, verbose_name="authorization_enabled")
    authorization_status = models.CharField(max_length=20, default="PENDING", verbose_name="authorization_status")
    authorization_valid_from = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="authorization_valid_from",
    )
    authorization_valid_until = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="authorization_valid_until",
    )
    display_name = models.CharField(max_length=120, blank=True, default="", verbose_name="display_name")
    region = models.CharField(max_length=120, blank=True, default="", verbose_name="region")
    rustdesk_id = models.CharField(max_length=120, blank=True, default="", verbose_name="rustdesk_id")
    rustdesk_password = models.CharField(max_length=120, blank=True, default="", verbose_name="rustdesk_password")
    agent_token = models.CharField(max_length=128, blank=True, default="", verbose_name="agent_token")
    computer_name = models.CharField(max_length=120, blank=True, default="", verbose_name="computer_name")
    mac_address = models.CharField(max_length=128, blank=True, default="", verbose_name="mac_address")
    os_name = models.CharField(max_length=120, blank=True, default="", verbose_name="os_name")
    os_version = models.CharField(max_length=120, blank=True, default="", verbose_name="os_version")
    os_user = models.CharField(max_length=120, blank=True, default="", verbose_name="os_user")
    processor = models.CharField(max_length=200, blank=True, default="", verbose_name="processor")
    processor_architecture = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="processor_architecture",
    )
    local_ip = models.CharField(max_length=120, blank=True, default="", verbose_name="local_ip")
    system_uptime = models.CharField(max_length=120, blank=True, default="", verbose_name="system_uptime")
    cpu_usage = models.FloatField(default=0.0, verbose_name="cpu_usage")
    gpu_usage = models.FloatField(default=0.0, verbose_name="gpu_usage")
    memory_usage = models.FloatField(default=0.0, verbose_name="memory_usage")
    disk_usage = models.FloatField(default=0.0, verbose_name="disk_usage")
    net_latency_ms = models.IntegerField(default=0, verbose_name="net_latency_ms")
    bandwidth_text = models.CharField(max_length=120, blank=True, default="", verbose_name="bandwidth_text")
    network_status_json = models.TextField(blank=True, default="", verbose_name="network_status_json")
    service_status_json = models.TextField(blank=True, default="", verbose_name="service_status_json")
    hardware_devices_json = models.TextField(blank=True, default="", verbose_name="hardware_devices_json")
    remote_monitor_json = models.TextField(blank=True, default="", verbose_name="remote_monitor_json")
    active_window_title = models.CharField(max_length=255, blank=True, default="", verbose_name="active_window_title")
    active_window_process = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="active_window_process",
    )
    screenshot_base64 = models.TextField(blank=True, default="", verbose_name="screenshot_base64")
    screenshot_object_bucket = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="screenshot_object_bucket",
    )
    screenshot_object_key = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="screenshot_object_key",
    )
    screenshot_storage_path = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="screenshot_storage_path",
    )
    screenshot_storage_url = models.TextField(blank=True, default="", verbose_name="screenshot_storage_url")
    screenshot_content_type = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="screenshot_content_type",
    )
    screenshot_byte_size = models.IntegerField(default=0, verbose_name="screenshot_byte_size")
    peripheral_cam = models.BooleanField(default=False, verbose_name="peripheral_cam")
    peripheral_mic = models.BooleanField(default=False, verbose_name="peripheral_mic")
    service_stream = models.BooleanField(null=True, blank=True, verbose_name="service_stream")
    service_llm = models.BooleanField(null=True, blank=True, verbose_name="service_llm")
    alert_window_enabled = models.BooleanField(default=False, verbose_name="alert_window_enabled")
    alert_window_weekdays_json = models.TextField(blank=True, default="[]", verbose_name="alert_window_weekdays_json")
    alert_window_start_time = models.CharField(
        max_length=8,
        blank=True,
        default="",
        verbose_name="alert_window_start_time",
    )
    alert_window_end_time = models.CharField(
        max_length=8,
        blank=True,
        default="",
        verbose_name="alert_window_end_time",
    )
    last_report_time = models.DateTimeField(null=True, blank=True, verbose_name="last_report_time")
    last_online_time = models.DateTimeField(null=True, blank=True, verbose_name="last_online_time")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")
    update_time = models.DateTimeField(auto_now=True, verbose_name="update_time")

    class Meta:
        db_table = "dh_device"
        verbose_name = "Digital Human Device"
        verbose_name_plural = "Digital Human Devices"
        indexes = [
            models.Index(fields=["authorization_status"], name="idx_dhdev_auth_status"),
            models.Index(fields=["tenant_name"], name="idx_dhdev_tenant"),
            models.Index(fields=["region"], name="idx_dhdev_region"),
            models.Index(fields=["last_report_time"], name="idx_dhdev_last_report"),
        ]


class DigitalHumanDeviceMetricHistory(models.Model):
    device = models.ForeignKey(
        DigitalHumanDevice,
        on_delete=models.CASCADE,
        related_name="metric_rows",
        verbose_name="device",
    )
    reported_at = models.DateTimeField(verbose_name="reported_at")
    status = models.CharField(max_length=20, blank=True, default="", verbose_name="status")
    cpu_usage = models.FloatField(default=0.0, verbose_name="cpu_usage")
    gpu_usage = models.FloatField(default=0.0, verbose_name="gpu_usage")
    memory_usage = models.FloatField(default=0.0, verbose_name="memory_usage")
    disk_usage = models.FloatField(default=0.0, verbose_name="disk_usage")
    net_latency_ms = models.IntegerField(default=0, verbose_name="net_latency_ms")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")

    class Meta:
        db_table = "dh_device_metric_history"
        verbose_name = "Digital Human Device Metric History"
        verbose_name_plural = "Digital Human Device Metric Histories"
        indexes = [
            models.Index(fields=["device", "reported_at"], name="idx_dhmet_device_time"),
            models.Index(fields=["reported_at"], name="idx_dhmet_reported"),
        ]


class DigitalHumanAlertRouteConfig(models.Model):
    enabled = models.BooleanField(default=False, verbose_name="enabled")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")
    update_time = models.DateTimeField(auto_now=True, verbose_name="update_time")

    class Meta:
        db_table = "dh_alert_dingtalk_config"
        verbose_name = "Digital Human Alert Route Config"
        verbose_name_plural = "Digital Human Alert Route Config"


class DigitalHumanAlertRoute(models.Model):
    region = models.CharField(max_length=120, blank=True, default="", verbose_name="region")
    webhook = models.TextField(blank=True, default="", verbose_name="webhook")
    secret = models.TextField(blank=True, default="", verbose_name="secret")
    owner_name = models.CharField(max_length=120, blank=True, default="", verbose_name="owner_name")
    owner_phone = models.CharField(max_length=64, blank=True, default="", verbose_name="owner_phone")
    active = models.BooleanField(default=True, verbose_name="active")
    is_default_route = models.BooleanField(default=False, verbose_name="is_default_route")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")
    update_time = models.DateTimeField(auto_now=True, verbose_name="update_time")

    class Meta:
        db_table = "dh_alert_dingtalk_route"
        verbose_name = "Digital Human Alert Route"
        verbose_name_plural = "Digital Human Alert Routes"
        indexes = [
            models.Index(fields=["region"], name="idx_dhroute_region"),
            models.Index(fields=["active", "is_default_route"], name="idx_dhroute_active_default"),
        ]


class DigitalHumanAlert(models.Model):
    device = models.ForeignKey(
        DigitalHumanDevice,
        on_delete=models.CASCADE,
        related_name="alert_rows",
        null=True,
        blank=True,
        verbose_name="device",
    )
    alert_type = models.CharField(max_length=100, blank=True, default="", verbose_name="alert_type")
    title = models.CharField(max_length=200, blank=True, default="", verbose_name="title")
    description = models.TextField(blank=True, default="", verbose_name="description")
    alert_module_text = models.CharField(max_length=120, blank=True, default="", verbose_name="alert_module_text")
    level = models.CharField(max_length=20, blank=True, default="warning", verbose_name="level")
    status = models.CharField(max_length=20, blank=True, default="pending", verbose_name="status")
    diagnosis_status = models.CharField(max_length=20, blank=True, default="skipped", verbose_name="diagnosis_status")
    diagnosis_text = models.TextField(blank=True, default="", verbose_name="diagnosis_text")
    diagnosis_error = models.TextField(blank=True, default="", verbose_name="diagnosis_error")
    first_occurred_at = models.DateTimeField(null=True, blank=True, verbose_name="first_occurred_at")
    last_occurred_at = models.DateTimeField(null=True, blank=True, verbose_name="last_occurred_at")
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="resolved_at")
    dingtalk_push_status = models.CharField(max_length=20, blank=True, default="", verbose_name="dingtalk_push_status")
    dingtalk_route_region = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="dingtalk_route_region",
    )
    dingtalk_owner_name = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="dingtalk_owner_name",
    )
    dingtalk_owner_phone = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name="dingtalk_owner_phone",
    )
    dingtalk_message_preview = models.TextField(blank=True, default="", verbose_name="dingtalk_message_preview")
    dingtalk_error = models.TextField(blank=True, default="", verbose_name="dingtalk_error")
    dingtalk_push_time = models.DateTimeField(null=True, blank=True, verbose_name="dingtalk_push_time")
    timeline_json = models.TextField(blank=True, default="[]", verbose_name="timeline_json")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")
    update_time = models.DateTimeField(auto_now=True, verbose_name="update_time")

    class Meta:
        db_table = "dh_alert_record"
        verbose_name = "Digital Human Alert"
        verbose_name_plural = "Digital Human Alerts"
        indexes = [
            models.Index(fields=["status", "level"], name="idx_dhalert_status_level"),
            models.Index(fields=["device", "status"], name="idx_dhalert_device_status"),
            models.Index(fields=["last_occurred_at"], name="idx_dhalert_last_time"),
        ]


class DigitalHumanHumanLog(models.Model):
    device = models.ForeignKey(
        DigitalHumanDevice,
        on_delete=models.CASCADE,
        related_name="human_log_rows",
        verbose_name="device",
    )
    time = models.DateTimeField(verbose_name="time")
    level = models.CharField(max_length=16, blank=True, default="INFO", verbose_name="level")
    module = models.CharField(max_length=64, blank=True, default="", verbose_name="module")
    message = models.TextField(blank=True, default="", verbose_name="message")
    diagnosis_status = models.CharField(max_length=20, blank=True, default="skipped", verbose_name="diagnosis_status")
    diagnosis_text = models.TextField(blank=True, default="", verbose_name="diagnosis_text")
    diagnosis_error = models.TextField(blank=True, default="", verbose_name="diagnosis_error")
    structured_json = models.TextField(blank=True, default="", verbose_name="structured_json")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")

    class Meta:
        db_table = "dh_human_log"
        verbose_name = "Digital Human Human Log"
        verbose_name_plural = "Digital Human Human Logs"
        indexes = [
            models.Index(fields=["time"], name="idx_dhlog_time"),
            models.Index(fields=["device", "time"], name="idx_dhlog_device_time"),
            models.Index(fields=["level", "module"], name="idx_dhlog_level_module"),
        ]


class DigitalHumanCommandTask(models.Model):
    device = models.ForeignKey(
        DigitalHumanDevice,
        on_delete=models.CASCADE,
        related_name="command_task_rows",
        verbose_name="device",
    )
    command_type = models.CharField(max_length=64, blank=True, default="", verbose_name="command_type")
    command_payload = models.TextField(blank=True, default="", verbose_name="command_payload")
    status = models.CharField(max_length=20, blank=True, default="PENDING", verbose_name="status")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")
    update_time = models.DateTimeField(auto_now=True, verbose_name="update_time")

    class Meta:
        db_table = "dh_command_task"
        verbose_name = "Digital Human Command Task"
        verbose_name_plural = "Digital Human Command Tasks"
        indexes = [
            models.Index(fields=["device", "status"], name="idx_dhcmd_device_status"),
            models.Index(fields=["status", "create_time"], name="idx_dhcmd_status_time"),
        ]


class DigitalHumanCommandResult(models.Model):
    command_task = models.ForeignKey(
        DigitalHumanCommandTask,
        on_delete=models.CASCADE,
        related_name="result_rows",
        verbose_name="command_task",
    )
    success = models.BooleanField(default=False, verbose_name="success")
    result_message = models.CharField(max_length=1000, blank=True, default="", verbose_name="result_message")
    result_payload = models.TextField(blank=True, default="", verbose_name="result_payload")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")

    class Meta:
        db_table = "dh_command_result"
        verbose_name = "Digital Human Command Result"
        verbose_name_plural = "Digital Human Command Results"
        indexes = [
            models.Index(fields=["command_task", "create_time"], name="idx_dhcmdres_task_time"),
        ]


class DigitalHumanAiDiagnosisConfig(models.Model):
    enabled = models.BooleanField(default=False, verbose_name="enabled")
    base_url = models.CharField(max_length=255, blank=True, default="", verbose_name="base_url")
    api_key = models.TextField(blank=True, default="", verbose_name="api_key")
    model = models.CharField(max_length=120, blank=True, default="", verbose_name="model")
    temperature = models.FloatField(default=0.2, verbose_name="temperature")
    alert_system_prompt = models.TextField(blank=True, default="", verbose_name="alert_system_prompt")
    log_system_prompt = models.TextField(blank=True, default="", verbose_name="log_system_prompt")
    connect_timeout_ms = models.IntegerField(default=10000, verbose_name="connect_timeout_ms")
    read_timeout_ms = models.IntegerField(default=60000, verbose_name="read_timeout_ms")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="create_time")
    update_time = models.DateTimeField(auto_now=True, verbose_name="update_time")

    class Meta:
        db_table = "dh_system_ai_config"
        verbose_name = "Digital Human AI Diagnosis Config"
        verbose_name_plural = "Digital Human AI Diagnosis Config"
