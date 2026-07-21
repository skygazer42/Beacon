export const API = {
  // ═══════════════════════════════════════════
  // App-Shell JSON APIs
  // ═══════════════════════════════════════════
  dashboard: '/api/app-shell/dashboard',
  alarms: '/api/app-shell/alarms',
  alarmDetail: '/api/app-shell/alarm/detail',
  alarmPresetsSave: '/api/app-shell/alarm-presets/save',
  alarmPresetsDelete: '/api/app-shell/alarm-presets/delete',
  alarmSounds: '/api/app-shell/alarm-sounds',

  streams: '/api/app-shell/streams',
  streamOnline: '/api/app-shell/stream-online',
  streamPlayer: '/api/app-shell/stream-player',

  algorithms: '/api/app-shell/algorithms',
  algorithmVersions: '/api/app-shell/algorithm/versions',

  controlEditor: '/api/app-shell/control/editor',
  controlLogs: '/api/app-shell/control/logs',
  controlOsdAssets: '/api/app-shell/control/osd-assets',
  controlOsdAssetsUpload: '/api/app-shell/control/osd-assets/upload',

  screen: '/api/app-shell/screen',
  diagnostics: '/api/app-shell/diagnostics',
  notifications: '/api/app-shell/notifications',
  platform: '/api/app-shell/platform',
  upgrade: '/api/app-shell/upgrade',
  users: '/api/app-shell/users',
  audit: '/api/app-shell/audit',
  apikeys: '/api/app-shell/apikeys',
  license: '/api/app-shell/license',
  licenseUpload: '/api/app-shell/license/upload',
  recording: '/api/app-shell/recording',
  faces: '/api/app-shell/faces',
  developer: '/api/app-shell/developer',
  config: '/api/app-shell/config',
  onvif: '/api/app-shell/onvif',

  cloudEdgeClusters: '/api/app-shell/cloud/edge-clusters',
  cloudEdgeClustersAction: '/api/app-shell/cloud/edge-clusters/action',
  cloudAlarms: '/api/app-shell/cloud/alarms',
  cloudAlarmDetail: '/api/app-shell/cloud/alarm/detail',
  cloudRemoteStreams: '/api/app-shell/cloud/remote/streams',
  cloudRemoteStreamDetail: '/api/app-shell/cloud/remote/stream/detail',
  cloudRemoteRecordings: '/api/app-shell/cloud/remote/recordings',
  cloudRemotePlatform: '/api/app-shell/cloud/remote/platform',
  cloudIam: '/api/app-shell/cloud/iam',
  cloudIamAction: '/api/app-shell/cloud/iam/action',
  digitalHumanDashboard: '/api/app-shell/digital-human/dashboard',
  digitalHumanDevices: '/api/app-shell/digital-human/devices',
  digitalHumanAlerts: '/api/app-shell/digital-human/alerts',
  digitalHumanAlertDetail: '/api/app-shell/digital-human/alert-detail',
  digitalHumanAlertRouting: '/api/app-shell/digital-human/alert-routing',
  digitalHumanMonitorLogs: '/api/app-shell/digital-human/monitor-logs',
  digitalHumanMonitorLogNodeStatus: '/api/app-shell/digital-human/monitor-logs/node-status',
  digitalHumanOpsReport: '/api/app-shell/digital-human/ops-report',
  digitalHumanOpsAiInsight: '/api/app-shell/digital-human/ops-report/ai-insight',
  digitalHumanSystemSettingsJwtAccounts: '/api/app-shell/digital-human/system-settings/jwt-accounts',
  digitalHumanSystemSettingsDeviceAuthorizations: '/api/app-shell/digital-human/system-settings/device-authorizations',
  digitalHumanSystemSettingsDeviceAuthorizationDetail: '/api/app-shell/digital-human/system-settings/device-authorizations/detail',
  digitalHumanSystemSettingsAiDiagnosis: '/api/app-shell/digital-human/system-settings/ai-diagnosis',

  // ═══════════════════════════════════════════
  // Alarm action APIs
  // ═══════════════════════════════════════════
  alarmWorkflow: '/api/app-shell/alarm/action/workflow',
  alarmAssignment: '/api/app-shell/alarm/action/assignment',
  alarmOpenAdd: '/api/app-shell/alarm/action/openAdd',
  alarmExportEvidence: '/api/app-shell/alarm/action/exportEvidence',
  alarmExportLabelme: '/api/app-shell/alarm/action/exportLabelme',
  alarmExportCoco: '/api/app-shell/alarm/action/exportCoco',
  alarmPoll: '/api/app-shell/alarm/action/poll',
  alarmSemanticSearch: '/api/app-shell/alarm/action/semantic-search',
  alarmCrossCameraSearch: '/api/app-shell/alarm/action/cross-camera-search',

  // ═══════════════════════════════════════════
  // Alarm sound APIs
  // ═══════════════════════════════════════════
  alarmSoundUpload: '/api/app-shell/alarm-sound/action/upload',
  alarmSoundDelete: '/api/app-shell/alarm-sound/action/delete',
  alarmSoundSetDefault: '/api/app-shell/alarm-sound/action/setDefault',
  alarmSoundList: '/api/app-shell/alarm-sound/action/list',

  // ═══════════════════════════════════════════
  // Stream CRUD & action APIs
  // ═══════════════════════════════════════════
  streamAdd: '/api/app-shell/stream/action/openAdd',
  streamEdit: '/api/app-shell/stream/action/openEdit',
  streamDel: '/api/app-shell/stream/action/openDel',
  streamGet: '/api/app-shell/stream/action/openGet',
  streamGetPlayUrl: '/api/app-shell/stream/action/getPlayUrl',
  streamBatchImport: '/api/app-shell/stream/action/batchImport',
  streamBatchAddProxy: '/api/app-shell/stream/action/openBatchAddStreamProxy',
  streamBatchDelProxy: '/api/app-shell/stream/action/openBatchDelStreamProxy',
  streamAddProxy: '/api/app-shell/stream/action/openAddStreamProxy',
  streamDelProxy: '/api/app-shell/stream/action/openDelStreamProxy',
  streamAddPusherProxy: '/api/app-shell/stream/action/openAddStreamPusherProxy',
  streamSetState: '/api/app-shell/stream/action/openSetState',
  streamGetAllStartForward: '/api/app-shell/stream/action/getAllStartForward',
  streamGetAllUpdateForwardState: '/api/app-shell/stream/action/getAllUpdateForwardState',
  streamGetAutoStartConfig: '/api/app-shell/stream/action/getAutoStartConfig',
  streamSetAutoStartConfig: '/api/app-shell/stream/action/setAutoStartConfig',
  streamWebrtcSelfCheck: '/api/app-shell/stream/action/webrtcSelfCheck',
  streamGb28181Ptz: '/api/app-shell/stream/action/openGb28181Ptz',

  // ═══════════════════════════════════════════
  // Stream talkback APIs
  // ═══════════════════════════════════════════
  talkbackConfigGet: '/api/app-shell/stream/action/talkback/config/get',
  talkbackConfigSave: '/api/app-shell/stream/action/talkback/config/save',
  talkbackStart: '/api/app-shell/stream/action/talkback/start',
  talkbackStop: '/api/app-shell/stream/action/talkback/stop',
  talkbackStatus: '/api/app-shell/stream/action/talkback/status',

  // ═══════════════════════════════════════════
  // Control action APIs
  // ═══════════════════════════════════════════
  controlStart: '/api/app-shell/control/action/openStartControl',
  controlStop: '/api/app-shell/control/action/openStopControl',
  controlBatchStart: '/api/app-shell/control/action/openBatchStart',
  controlBatchStop: '/api/app-shell/control/action/openBatchStop',
  controlDel: '/api/app-shell/control/action/openDel',
  controlCopy: '/api/app-shell/control/action/openCopy',
  controlBatchCopy: '/api/app-shell/control/action/openBatchCopyToStreams',
  controlQuickSet: '/api/app-shell/control/action/openQuickSet',
  controlAdd: '/api/app-shell/control/action/postAddControl',
  controlEditPost: '/api/app-shell/control/action/postEditControl',
  controlIndex: '/api/app-shell/control/action/openIndex',
  controlLogsExport: '/api/app-shell/control/action/logs/export',

  // ═══════════════════════════════════════════
  // Algorithm action APIs
  // ═══════════════════════════════════════════
  algorithmDel: '/api/app-shell/algorithm/action/openDel',
  algorithmVersionActivate: '/api/app-shell/algorithm/action/openVersionActivate',
  algorithmVersionRollback: '/api/app-shell/algorithm/action/openVersionRollback',
  algorithmVersionGray: '/api/app-shell/algorithm/action/openVersionGray',
  algorithmAnalyzerLoad: '/api/app-shell/algorithm/action/openAnalyzerLoad',
  algorithmAnalyzerUnload: '/api/app-shell/algorithm/action/openAnalyzerUnload',
  algorithmTestInfer: '/api/app-shell/algorithm/action/openTestInfer',

  // ═══════════════════════════════════════════
  // User management APIs
  // ═══════════════════════════════════════════
  userCreate: '/api/app-shell/users/action/addUser',
  userEdit: '/api/app-shell/users/action/editUser',
  userDelete: '/api/app-shell/users/action/deleteUser',
  userBatchDelete: '/api/app-shell/users/action/batchDeleteUsers',
  userToggleStatus: '/api/app-shell/users/action/toggleUserStatus',
  userPermissions: '/api/app-shell/users/action/permissions/get',
  userSetPermissions: '/api/app-shell/users/action/permissions/set',

  // ═══════════════════════════════════════════
  // Ops APIs
  // ═══════════════════════════════════════════
  opsAuditList: '/api/app-shell/ops/action/audit/list',
  opsAuditExport: '/api/app-shell/ops/action/audit/export',
  opsApiKeyList: '/api/app-shell/ops/action/apikeys/list',
  opsApiKeyCreate: '/api/app-shell/ops/action/apikeys/create',
  opsApiKeyRevoke: '/api/app-shell/ops/action/apikeys/revoke',
  opsApiKeyRotate: '/api/app-shell/ops/action/apikeys/rotate',

  // ═══════════════════════════════════════════
  // Config import/export APIs
  // ═══════════════════════════════════════════
  configExport: '/api/app-shell/config/action/export',
  configImport: '/api/app-shell/config/action/import',
  configImportPreview: '/api/app-shell/config/action/preview',
  configRollback: '/api/app-shell/config/action/history/rollback',
  configSystemSave: '/api/app-shell/config/action/system/save',
  configLogExport: '/api/app-shell/config/action/logs/export',

  // ═══════════════════════════════════════════
  // Recording APIs
  // ═══════════════════════════════════════════
  recordingStart: '/api/app-shell/recording/action/startRecording',
  recordingStop: '/api/app-shell/recording/action/stopRecording',
  recordingStatus: '/api/app-shell/recording/action/getRecordingStatus',
  recordingListActive: '/api/app-shell/recording/action/listActiveRecordings',
  recordingSnapshot: '/api/app-shell/recording/action/captureSnapshot',
  recordingBatchSnapshot: '/api/app-shell/recording/action/batchCaptureSnapshots',
  recordingFileList: '/api/app-shell/recording/action/file/list',
  recordingFilePlayUrl: '/api/app-shell/recording/action/file/playUrl',
  recordingPlanAdd: '/api/app-shell/recording/action/plan/add',
  recordingPlanEdit: '/api/app-shell/recording/action/plan/edit',
  recordingPlanDelete: '/api/app-shell/recording/action/plan/delete',
  taskPlanList: '/api/app-shell/recording/action/task-plan/list',
  taskPlanAdd: '/api/app-shell/recording/action/task-plan/add',
  taskPlanEdit: '/api/app-shell/recording/action/task-plan/edit',
  taskPlanDelete: '/api/app-shell/recording/action/task-plan/delete',

  // ═══════════════════════════════════════════
  // ONVIF APIs
  // ═══════════════════════════════════════════
  onvifDiscover: '/api/app-shell/onvif/action/discover',
  onvifDeviceInfo: '/api/app-shell/onvif/action/getDeviceInfo',
  onvifGetRtsp: '/api/app-shell/onvif/action/getRtspUrls',
  onvifSnapshot: '/api/app-shell/onvif/action/captureSnapshot',
  onvifImport: '/api/app-shell/onvif/action/importStreams',

  // ═══════════════════════════════════════════
  // Face library APIs
  // ═══════════════════════════════════════════
  faceAdd: '/api/app-shell/faces/action/add',
  faceDelete: '/api/app-shell/faces/action/delete',
  faceList: '/api/app-shell/faces/action/list',
  faceSearch: '/api/app-shell/faces/action/search',
  faceEnable: '/api/app-shell/faces/action/enable',
  faceDisable: '/api/app-shell/faces/action/disable',

  // ═══════════════════════════════════════════
  // Developer APIs
  // ═══════════════════════════════════════════
  developerAlgorithmCallback: '/api/app-shell/developer/action/algorithmCallback',
  developerGetStreamInfo: '/api/app-shell/developer/action/getStreamInfo',
  developerGetAlgorithmInfo: '/api/app-shell/developer/action/getAlgorithmInfo',

  // ═══════════════════════════════════════════
  // Alarm sink test
  // ═══════════════════════════════════════════
  alarmSinksTestSend: '/api/app-shell/alarm/action/sinks/testSend',

  // ═══════════════════════════════════════════
  // Misc APIs
  // ═══════════════════════════════════════════
  postHandleAlarm: '/api/app-shell/alarm/action/postHandleAlarm',
  cloudAlarmImage: '/api/app-shell/cloud/action/alarm-image',
  digitalHumanDeviceUpdateWindow: '/api/app-shell/digital-human/device/action/update-window',
  digitalHumanAlertResolve: '/api/app-shell/digital-human/alert/action/resolve',
  digitalHumanAlertRoutingToggle: '/api/app-shell/digital-human/alert-routing/action/enabled',
  digitalHumanAlertRoutingCreate: '/api/app-shell/digital-human/alert-routing/action/create',
  digitalHumanAlertRoutingUpdate: '/api/app-shell/digital-human/alert-routing/action/update',
  digitalHumanAlertRoutingDelete: '/api/app-shell/digital-human/alert-routing/action/delete',
  digitalHumanMonitorLogReanalyze: '/api/app-shell/digital-human/monitor-logs/action/reanalyze',
  digitalHumanSystemSettingsJwtAccountCreate: '/api/app-shell/digital-human/system-settings/jwt-accounts/action/create',
  digitalHumanSystemSettingsJwtAccountRotateSecret: '/api/app-shell/digital-human/system-settings/jwt-accounts/action/rotate-secret',
  digitalHumanSystemSettingsJwtAccountStatus: '/api/app-shell/digital-human/system-settings/jwt-accounts/action/status',
  digitalHumanSystemSettingsJwtAccountDelete: '/api/app-shell/digital-human/system-settings/jwt-accounts/action/delete',
  digitalHumanSystemSettingsDeviceAuthorizationUpdate: '/api/app-shell/digital-human/system-settings/device-authorizations/action/update',
  digitalHumanSystemSettingsDeviceAuthorizationDelete: '/api/app-shell/digital-human/system-settings/device-authorizations/action/delete',
  digitalHumanSystemSettingsAiDiagnosisSave: '/api/app-shell/digital-human/system-settings/ai-diagnosis/action/save',
  digitalHumanSystemSettingsAiDiagnosisTest: '/api/app-shell/digital-human/system-settings/ai-diagnosis/action/test',

  // ═══════════════════════════════════════════
  // Open/upgrade APIs (ops tooling)
  // ═══════════════════════════════════════════
  opsUpgradeCheckVersion: '/api/app-shell/ops/action/upgrade/checkVersion',
  opsUpgradeUpload: '/api/app-shell/ops/action/upgrade/upload',
  opsUpgradeList: '/api/app-shell/ops/action/upgrade/list',
  opsUpgradeValidate: '/api/app-shell/ops/action/upgrade/validate',
  opsUpgradeApply: '/api/app-shell/ops/action/upgrade/apply',
  opsUpgradeRollback: '/api/app-shell/ops/action/upgrade/rollback',
  opsCleanup: '/api/app-shell/ops/action/cleanup',
  opsOutboxReplay: '/api/app-shell/ops/action/outbox/replay',
  opsLoggingSetLevel: '/api/app-shell/ops/action/logging/level',
  opsDiagnosticsExport: '/api/app-shell/ops/action/diagnostics/export',

  // ═══════════════════════════════════════════
  // Platform action APIs
  // ═══════════════════════════════════════════
  platformRestartSoftware: '/api/app-shell/platform/action/restartSoftware',
  platformRestartSystem: '/api/app-shell/platform/action/restartSystem',
  platformBasicInfo: '/api/app-shell/platform/action/basicInfo',
  platformStorageInfo: '/api/app-shell/platform/action/storageInfo',
};
