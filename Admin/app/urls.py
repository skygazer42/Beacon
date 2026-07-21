from django.urls import path
from .views import web
from .views import api
from .views import Algorithm
from .views import ControlView
from .views import AlarmView
from .views import StreamView
from .views import AlarmSoundView
from .views import DeveloperView
from .views import ControlLogView
from .views import ONVIFView
from .views import StreamRecordingView
from .views import UserManageView
from .views import ConfigExportView
from .views import LicenseView
from .views import CloudOpenApi
from .views import CloudConsoleView
from .views import CloudRemoteStreamsView
from .views import CloudRemoteStreamDetailView
from .views import CloudRemoteRecordingsView
from .views import CloudRemotePlatformView
from .views import DigitalHumanApiView
from .views import DigitalHumanOpenView
from .views import DigitalHumanView
from .views import OpsView
from .views import OpsAuditLogView
from .views import OpsApiKeyView
from .views import OpsDiagnosticsView
from .views import OpsPlatformView
from .views import OpsUpgradeView
from .views import SystemConfigView
from .views import FileServiceView
from .views import FaceView
from .views import ScreenView
from .views import AppShellView



app_name = 'app'

urlpatterns = [
    path('', web.web_index),
    path('profile', web.web_profile),
    path('login', web.web_login),
    path('login/oidc/start', web.web_oidc_start),
    path('login/oidc/callback', web.web_oidc_callback),
    path('logout', web.web_logout),
    path('logout/', web.web_logout),
    path('getVerifyCode', web.web_getVerifyCode),
    # Ops endpoints (health/ready/metrics)
    path('healthz', OpsView.healthz),
    path('readyz', OpsView.readyz),
    path('metrics', OpsView.metrics),
    # Ops Audit (web UI)
    path('ops/audit', OpsAuditLogView.index),
    path('ops/diagnostics', OpsDiagnosticsView.index),
    path('ops/platform', OpsPlatformView.index),
    path('ops/upgrade', OpsUpgradeView.index),
    # Ops API Keys (web UI)
    path('ops/apikeys', OpsApiKeyView.index),
    # Ops endpoints aliases (OpenAPI auth)
    path('open/ops/health', OpsView.healthz),
    path('open/ops/ready', OpsView.readyz),
    path('open/ops/metrics', OpsView.metrics),
    path('open/ops/audit/export', OpsView.audit_export),
    path('open/ops/cleanup', OpsView.cleanup),
    path('open/ops/outbox/replay', OpsView.outbox_replay),
    path('open/ops/logging/level', OpsView.logging_set_level),
    path('open/ops/diagnostics/export', OpsDiagnosticsView.export),
    path('open/ops/upgrade/upload', OpsUpgradeView.upload),
    path('open/ops/upgrade/list', OpsUpgradeView.list_packages),
    path('open/ops/upgrade/validate', OpsUpgradeView.validate),
    path('open/ops/upgrade/apply', OpsUpgradeView.apply),
    path('open/ops/upgrade/rollback', OpsUpgradeView.rollback),
    # Cloud Console (BEACON_DEPLOYMENT_MODE=cloud)
    path('cloud/edge-clusters', CloudConsoleView.edge_clusters),
    path('cloud/remote/streams', CloudRemoteStreamsView.streams),
    path('cloud/remote/stream/detail', CloudRemoteStreamDetailView.stream_detail),
    path('cloud/remote/recordings', CloudRemoteRecordingsView.index),
    path('cloud/remote/recordings/file/<int:cluster_id>/<path:rel_path>', CloudRemoteRecordingsView.recording_file),
    path('cloud/remote/platform', CloudRemotePlatformView.platform),
    path('cloud/alarms', CloudConsoleView.alarms),
    path('cloud/alarm/detail', CloudConsoleView.alarm_detail),
    path('cloud/alarm/image', CloudConsoleView.alarm_image),
    path('cloud/iam', CloudConsoleView.iam),
    path('digital-human/dashboard', DigitalHumanView.dashboard),
    path('digital-human/device-monitor', DigitalHumanView.device_monitor),
    path('digital-human/alert-center', DigitalHumanView.alert_center),
    path('digital-human/monitor-logs', DigitalHumanView.monitor_logs),
    path('digital-human/ops-report', DigitalHumanView.ops_report),
    path('digital-human/system-settings', DigitalHumanView.system_settings),
    path('digital-human/device-screenshot', DigitalHumanView.device_screenshot),
    # 视频流功能
    path('stream/openIndex', StreamView.api_openIndex), #3.52新增，适配集群管理平台
    path('stream/index', StreamView.index),
    path('stream/add', StreamView.add),
    path('stream/edit', StreamView.edit),
    path('stream/openAdd', StreamView.api_openAdd),
    path('stream/openDel', StreamView.api_openDel),#3.52新增，适配集群管理平台
    path('stream/openGet', StreamView.api_openGet),
    path('stream/openEdit', StreamView.api_openEdit),
    path('stream/openAddStreamProxy', StreamView.api_openAddStreamProxy),#3.52新增，适配集群管理平台
    path('stream/openGb28181Ptz', StreamView.api_openGb28181Ptz),
    path('stream/openDelStreamProxy', StreamView.api_openDelStreamProxy),#3.52新增，适配集群管理平台
    path('stream/openBatchAddStreamProxy', StreamView.api_openBatchAddStreamProxy),
    path('stream/openBatchDelStreamProxy', StreamView.api_openBatchDelStreamProxy),
    path('stream/openAddStreamPusherProxy', StreamView.api_openAddStreamPusherProxy),#3.52新增，适配集群管理平台
    path('stream/talkback/config/get', StreamView.api_talkback_config_get),
    path('stream/talkback/config/save', StreamView.api_talkback_config_save),
    path('stream/talkback/start', StreamView.api_talkback_start),
    path('stream/talkback/stop', StreamView.api_talkback_stop),
    path('stream/talkback/status', StreamView.api_talkback_status),
    path('stream/player', StreamView.player),
    path('stream/webrtcSelfCheck', StreamView.api_webrtcSelfCheck),
    path('stream/multi', StreamView.player_multi),
    path('stream/getOnline', StreamView.api_getOnline),
    path('stream/getPlayUrl', StreamView.api_getPlayUrl),
    path('stream/getAllStartForward', StreamView.api_getAllStartForward),
    path('stream/getAllUpdateForwardState', StreamView.api_getAllUpdateForwardState),
    # 大屏页面（多分屏播放 + 播放记忆 + 报警提醒）
    path('screen/index', ScreenView.index),

    path('alarms', AlarmView.index),
    path('alarm/review', AlarmView.review_center),
    path('alarm/preset/save', AlarmView.preset_save),
    path('alarm/preset/delete', AlarmView.preset_delete),
    path('alarm/api/semanticSearch', AlarmView.api_semanticSearch),
    path('alarm/api/vlmSearch', AlarmView.api_vlmSearch),
    path('alarm/api/vectorIndex/rebuild', AlarmView.api_vectorIndexRebuild),
    path('alarm/api/vectorSearch', AlarmView.api_vectorSearch),
    path('openapi/search/alarm', AlarmView.api_vlmSearch),
    path('alarm/api/crossCameraSearch', api.api_crossCameraSearch),
    path('alarm/detail', AlarmView.detail),
    path('alarm/workflow', AlarmView.api_workflow_transition),
    path('alarm/assignment', AlarmView.api_assignment_update),
    path('alarm/exportEvidence', AlarmView.api_exportEvidence),
    path('alarm/exportLabelme', AlarmView.api_exportLabelme),
    path('alarm/exportCoco', AlarmView.api_exportCoco),
    path('alarm/openAdd', AlarmView.api_openAdd),
    # 算法
    path('algorithm/index', Algorithm.index),
    path('algorithm/add', Algorithm.add),
    path('algorithm/edit', Algorithm.edit),
    path('algorithm/versions', Algorithm.versions),
    path('algorithm/marketplace', Algorithm.api_marketplace),
    path('algorithm/openDel', Algorithm.api_openDel),
    path('algorithm/openVersionActivate', Algorithm.api_openVersionActivate),
    path('algorithm/openVersionRollback', Algorithm.api_openVersionRollback),
    path('algorithm/openVersionGray', Algorithm.api_openVersionGray),
    path('algorithm/openAnalyzerLoad', Algorithm.api_openAnalyzerLoad),
    path('algorithm/openAnalyzerUnload', Algorithm.api_openAnalyzerUnload),
    path('algorithm/openTestInfer', Algorithm.api_openTestInfer),
    # 布控
    path('controls', ControlView.index),
    path('control/openIndex', ControlView.api_openIndex),#3.52新增，适配集群管理平台
    path('control/add', ControlView.add),
    path('control/edit', ControlView.edit),
    path('control/openStartControl', ControlView.api_openStartControl),#3.52新增，适配集群管理平台
    path('control/openStopControl', ControlView.api_openStopControl),#3.52新增，适配集群管理平台
    path('control/openQuickSet', ControlView.api_openQuickSet),# v4.643: 布控快捷设置（轻量 patch）
    path('control/openDel', ControlView.api_openDel),#3.52新增，适配集群管理平台
    path('control/openBatchStart', ControlView.api_openBatchStart),
    path('control/openBatchStop', ControlView.api_openBatchStop),
    path('control/openCopy', ControlView.api_openCopy),
    path('control/openBatchCopyToStreams', ControlView.api_openBatchCopyToStreams),
    path('control/logs', ControlLogView.index),
    path('open/discover', api.api_discover),#3.52新增，适配集群管理平台
    path('open/getAllStreamData', api.api_getAllStreamData),#3.52新增，适配集群管理平台
    path('open/getAllAlgroithmFlowData', api.api_getAllAlgroithmFlowData),#3.52新增，适配集群管理平台
    path('open/getAllCoreProcessData', api.api_getAllCoreProcessData),#3.52新增，适配集群管理平台
    path('open/getAllCoreProcessData2', api.api_getAllCoreProcessData2),#3.52新增，适配集群管理平台
    path('open/checkVersion', api.api_checkVersion),
    path('open/license/info', api.api_licenseInfo),
    path('open/license/lease/acquire', api.api_licenseLeaseAcquire),
    path('open/license/lease/renew', api.api_licenseLeaseRenew),
    path('open/license/lease/release', api.api_licenseLeaseRelease),
    path('open/license/usage', api.api_licenseUsage),
    path('open/alarm/upload', api.api_uploadAlarm),
    path('open/algorithm/imageDetect', api.api_openImageDetect),
    path('open/algorithm/audioDetect', api.api_openAudioDetect),
    path('open/getControlData', api.api_getControlData),
    path('open/getStreamData', api.api_getStreamData),
    # Platform open APIs (industrial integration)
    path('open/platform/basicInfo', api.api_openBasicInfo),
    path('open/platform/storageInfo', api.api_openStorageInfo),
    path('open/platform/restartSoftware', api.api_openRestartSoftware),
    path('open/platform/restartSystem', api.api_openRestartSystem),
    # File service (industrial delivery): serve arbitrary disk folder over HTTP (OpenAPI token protected)
    path('open/fileService/<path:rel_path>', FileServiceView.open_serve),
    path('recording/file/<path:rel_path>', FileServiceView.recording_session_serve),
    path('open/recordingPlan/add', api.api_openAddRecordingPlan),
    path('open/recordingPlan/edit', api.api_openEditRecordingPlan),
    path('open/recordingPlan/delete', api.api_openDeleteRecordingPlan),
    path('open/recordingPlan/list', api.api_openListRecordingPlans),
    path('open/taskPlan/add', api.api_openAddTaskPlan),
    path('open/taskPlan/edit', api.api_openEditTaskPlan),
    path('open/taskPlan/delete', api.api_openDeleteTaskPlan),
    path('open/taskPlan/list', api.api_openListTaskPlans),
    path('open/recording/file/list', api.api_openListRecordingFiles),
    path('open/recording/file/playUrl', api.api_openRecordingFilePlayUrl),
    path('open/recording/startRecording', api.api_openStartRecording),
    path('open/recording/stopRecording', api.api_openStopRecording),
    path('open/recording/captureSnapshot', api.api_openCaptureSnapshot),
    # Face library open APIs
    path('open/face/add', api.api_openFaceAdd),
    path('open/face/delete', api.api_openFaceDelete),
    path('open/face/list', api.api_openFaceList),
    path('open/face/search', api.api_openFaceSearch),
    path('open/face/enable', api.api_openFaceEnable),
    path('open/face/disable', api.api_openFaceDisable),
    # Cloud SaaS v1 (Edge -> Cloud)
    path('open/cloud/v1/presign/image', CloudOpenApi.api_cloud_presign_image),
    path('open/cloud/v1/events/alarm-created', CloudOpenApi.api_cloud_ingest_alarm_created),
    path('open/agent/token', DigitalHumanOpenView.open_agent_token),
    path('open/agent/register', DigitalHumanOpenView.open_agent_register),
    path('open/agent/report', DigitalHumanOpenView.open_agent_report),
    path('open/agent/config/latest', DigitalHumanOpenView.open_agent_config_latest),
    path('open/agent/commands/pull', DigitalHumanOpenView.open_agent_commands_pull),
    path('open/agent/commands/result', DigitalHumanOpenView.open_agent_commands_result),
    path('open/human/report', DigitalHumanOpenView.open_human_report),

    path('api/postHandleAlarm', api.api_postHandleAlarm),
    path('api/alarm/poll', api.api_alarmPoll),

    path('api/postAddControl', api.api_postAddControl),
    path('api/postEditControl', api.api_postEditControl),

    # 人脸管理
    path('face/index', FaceView.index),

    path('api/app-shell/dashboard', AppShellView.api_dashboard),
    path('api/app-shell/alarm/action/<path:action>', AppShellView.api_alarm_action),
    path('api/app-shell/alarm-sound/action/<path:action>', AppShellView.api_alarm_sound_action),
    path('api/app-shell/streams', AppShellView.api_streams),
    path('api/app-shell/stream-online', AppShellView.api_stream_online),
    path('api/app-shell/stream-player', AppShellView.api_stream_player),
    path('api/app-shell/stream/action/<path:action>', AppShellView.api_stream_action),
    path('api/app-shell/control/action/<path:action>', AppShellView.api_control_action),
    path('api/app-shell/alarm/detail', AppShellView.api_alarm_detail),
    path('api/app-shell/alarm-sounds', AppShellView.api_alarm_sounds),
    path('api/app-shell/alarms', AppShellView.api_alarms),
    path('api/app-shell/alarm-presets/save', AppShellView.api_alarm_presets_save),
    path('api/app-shell/alarm-presets/delete', AppShellView.api_alarm_presets_delete),
    path('api/app-shell/algorithms', AppShellView.api_algorithms),
    path('api/app-shell/algorithm/action/<path:action>', AppShellView.api_algorithm_action),
    path('api/app-shell/algorithm/versions', AppShellView.api_algorithm_versions),
    path('api/app-shell/screen', AppShellView.api_screen),
    path('api/app-shell/diagnostics', AppShellView.api_diagnostics),
    path('api/app-shell/notifications', AppShellView.api_notifications),
    path('api/app-shell/platform', AppShellView.api_platform),
    path('api/app-shell/platform/action/<path:action>', AppShellView.api_platform_action),
    path('api/app-shell/upgrade', AppShellView.api_upgrade),
    path('api/app-shell/ops/action/<path:action>', AppShellView.api_ops_action),
    path('api/app-shell/users', AppShellView.api_users),
    path('api/app-shell/audit', AppShellView.api_audit),
    path('api/app-shell/apikeys', AppShellView.api_apikeys),
    path('api/app-shell/license', AppShellView.api_license),
    path('api/app-shell/license/upload', AppShellView.api_license_upload),
    path('api/app-shell/recording', AppShellView.api_recording),
    path('api/app-shell/recording/action/<path:action>', AppShellView.api_recording_action),
    path('api/app-shell/control/editor', AppShellView.api_control_editor),
    path('api/app-shell/control/osd-assets', AppShellView.api_control_osd_assets),
    path('api/app-shell/control/osd-assets/upload', AppShellView.api_control_osd_assets_upload),
    path('api/app-shell/control/logs', AppShellView.api_control_logs),
    path('api/app-shell/faces', AppShellView.api_faces),
    path('api/app-shell/faces/action/<path:action>', AppShellView.api_faces_action),
    path('api/app-shell/developer', AppShellView.api_developer),
    path('api/app-shell/developer/action/<path:action>', AppShellView.api_developer_action),
    path('api/app-shell/config', AppShellView.api_config),
    path('api/app-shell/config/action/<path:action>', AppShellView.api_config_action),
    path('api/app-shell/onvif', AppShellView.api_onvif),
    path('api/app-shell/onvif/action/<path:action>', AppShellView.api_onvif_action),
    path('api/app-shell/cloud/edge-clusters', AppShellView.api_cloud_edge_clusters),
    path('api/app-shell/cloud/edge-clusters/action', AppShellView.api_cloud_edge_clusters_action),
    path('api/app-shell/cloud/action/<path:action>', AppShellView.api_cloud_action),
    path('api/app-shell/cloud/alarms', AppShellView.api_cloud_alarms),
    path('api/app-shell/cloud/alarm/detail', AppShellView.api_cloud_alarm_detail),
    path('api/app-shell/cloud/remote/streams', AppShellView.api_cloud_remote_streams),
    path('api/app-shell/cloud/remote/stream/detail', AppShellView.api_cloud_remote_stream_detail),
    path('api/app-shell/cloud/remote/recordings', AppShellView.api_cloud_remote_recordings),
    path('api/app-shell/cloud/remote/platform', AppShellView.api_cloud_remote_platform),
    path('api/app-shell/cloud/iam', AppShellView.api_cloud_iam),
    path('api/app-shell/cloud/iam/action', AppShellView.api_cloud_iam_action),
    path('api/app-shell/users/action/<path:action>', AppShellView.api_users_action),
    path('api/app-shell/digital-human/dashboard', DigitalHumanApiView.api_dashboard),
    path('api/app-shell/digital-human/devices', DigitalHumanApiView.api_devices),
    path('api/app-shell/digital-human/device/action/update-window', DigitalHumanApiView.api_device_update_window),
    path('api/app-shell/digital-human/alerts', DigitalHumanApiView.api_alerts),
    path('api/app-shell/digital-human/alert-detail', DigitalHumanApiView.api_alert_detail),
    path('api/app-shell/digital-human/alert/action/resolve', DigitalHumanApiView.api_alert_resolve),
    path('api/app-shell/digital-human/alert-routing', DigitalHumanApiView.api_alert_routing),
    path('api/app-shell/digital-human/alert-routing/action/enabled', DigitalHumanApiView.api_alert_routing_enabled),
    path('api/app-shell/digital-human/alert-routing/action/create', DigitalHumanApiView.api_alert_routing_create),
    path('api/app-shell/digital-human/alert-routing/action/update', DigitalHumanApiView.api_alert_routing_update),
    path('api/app-shell/digital-human/alert-routing/action/delete', DigitalHumanApiView.api_alert_routing_delete),
    path('api/app-shell/digital-human/monitor-logs', DigitalHumanApiView.api_monitor_logs),
    path('api/app-shell/digital-human/monitor-logs/node-status', DigitalHumanApiView.api_monitor_log_node_status),
    path('api/app-shell/digital-human/monitor-logs/action/reanalyze', DigitalHumanApiView.api_monitor_log_reanalyze),
    path('api/app-shell/digital-human/ops-report', DigitalHumanApiView.api_ops_report),
    path('api/app-shell/digital-human/ops-report/ai-insight', DigitalHumanApiView.api_ops_ai_insight),
    path('api/app-shell/digital-human/system-settings/jwt-accounts', DigitalHumanApiView.api_system_settings_jwt_accounts),
    path('api/app-shell/digital-human/system-settings/jwt-accounts/action/create', DigitalHumanApiView.api_system_settings_jwt_account_create),
    path('api/app-shell/digital-human/system-settings/jwt-accounts/action/rotate-secret', DigitalHumanApiView.api_system_settings_jwt_account_rotate_secret),
    path('api/app-shell/digital-human/system-settings/jwt-accounts/action/status', DigitalHumanApiView.api_system_settings_jwt_account_status),
    path('api/app-shell/digital-human/system-settings/jwt-accounts/action/delete', DigitalHumanApiView.api_system_settings_jwt_account_delete),
    path('api/app-shell/digital-human/system-settings/device-authorizations', DigitalHumanApiView.api_system_settings_device_authorizations),
    path('api/app-shell/digital-human/system-settings/device-authorizations/detail', DigitalHumanApiView.api_system_settings_device_authorization_detail),
    path('api/app-shell/digital-human/system-settings/device-authorizations/action/update', DigitalHumanApiView.api_system_settings_device_authorization_update),
    path('api/app-shell/digital-human/system-settings/device-authorizations/action/delete', DigitalHumanApiView.api_system_settings_device_authorization_delete),
    path('api/app-shell/digital-human/system-settings/ai-diagnosis', DigitalHumanApiView.api_system_settings_ai_diagnosis),
    path('api/app-shell/digital-human/system-settings/ai-diagnosis/action/save', DigitalHumanApiView.api_system_settings_ai_diagnosis_save),
    path('api/app-shell/digital-human/system-settings/ai-diagnosis/action/test', DigitalHumanApiView.api_system_settings_ai_diagnosis_test),
    # Webhook/Cloud 告警出口测试发送
    path('api/alarm/sinks/testSend', api.api_alarmSinksTestSend),
    # 摄像头批量导入和自启动配置
    path('stream/batchImport', StreamView.api_batchImport),
    path('stream/getAutoStartConfig', StreamView.api_getAutoStartConfig),
    path('stream/setAutoStartConfig', StreamView.api_setAutoStartConfig),
    # 报警声音管理
    path('alarm_sound/index', AlarmSoundView.index),
    # 开发者文档
    path('developer/index', DeveloperView.index),
    path('developer/algorithmCallback', DeveloperView.api_algorithmCallback),
    path('developer/getStreamInfo', DeveloperView.api_getStreamInfo),
    path('developer/getAlgorithmInfo', DeveloperView.api_getAlgorithmInfo),
    # ONVIF 设备管理
    path('onvif/discover', ONVIFView.onvif_discover),
    path('onvif/api/discover', ONVIFView.api_onvif_discover),
    path('onvif/api/getDeviceInfo', ONVIFView.api_onvif_get_device_info),
    path('onvif/api/getRtspUrls', ONVIFView.api_onvif_get_rtsp_urls),
    path('onvif/api/captureSnapshot', ONVIFView.api_onvif_capture_snapshot),
    path('onvif/api/importStreams', ONVIFView.api_onvif_import_streams),
    # 手动录像和截图
    path('recording/manager', StreamRecordingView.recording_manager),
    # 用户管理
    path('user/manage', UserManageView.user_manage_index),
    # 配置导出/导入
    path('config/export', ConfigExportView.export_page),
    path('config/import', ConfigExportView.import_page),
    path('config/history', ConfigExportView.history_page),
    path('config/system', SystemConfigView.system_page),
    # 授权管理（License Manager）
    path('license/manager', LicenseView.manager),
]
