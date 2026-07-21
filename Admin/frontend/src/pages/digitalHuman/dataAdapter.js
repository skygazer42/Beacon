import { apiGet, apiPost } from '../../api/client';
import { API } from '../../api/endpoints';

const DIGITAL_HUMAN_WEEKDAY_OPTIONS = [
  { label: '周一', value: '1' },
  { label: '周二', value: '2' },
  { label: '周三', value: '3' },
  { label: '周四', value: '4' },
  { label: '周五', value: '5' },
  { label: '周六', value: '6' },
  { label: '周日', value: '7' },
];

function normalizeText(value) {
  return String(value || '').trim();
}

function buildAiPayload(payload) {
  return {
    enabled: Boolean(payload.enabled),
    baseUrl: normalizeText(payload.baseUrl),
    apiKey: normalizeText(payload.apiKey),
    model: normalizeText(payload.model),
    temperature: Number(payload.temperature),
    alertSystemPrompt: payload.alertSystemPrompt || '',
    logSystemPrompt: payload.logSystemPrompt || '',
    connectTimeoutMs: Number(payload.connectTimeoutMs),
    readTimeoutMs: Number(payload.readTimeoutMs),
  };
}

export { DIGITAL_HUMAN_WEEKDAY_OPTIONS };

export function getDigitalHumanDashboard() {
  return apiGet(API.digitalHumanDashboard);
}

export function listDigitalHumanDevices() {
  return apiGet(API.digitalHumanDevices);
}

export function updateDigitalHumanDeviceWindow(deviceId, payload) {
  const enabled = Boolean(payload.enabled);
  return apiPost(API.digitalHumanDeviceUpdateWindow, {
    deviceId,
    enabled,
    weekdays: enabled ? payload.weekdays || [] : [],
    startTime: enabled ? String(payload.startTime || '') : '',
    endTime: enabled ? String(payload.endTime || '') : '',
  });
}

export function listDigitalHumanAlerts() {
  return apiGet(API.digitalHumanAlerts);
}

export function getDigitalHumanAlertDetail(alertId) {
  return apiGet(API.digitalHumanAlertDetail, { id: alertId });
}

export function resolveDigitalHumanAlert(alertId) {
  return apiPost(API.digitalHumanAlertResolve, { id: alertId });
}

export function getDigitalHumanAlertRoutingConfig() {
  return apiGet(API.digitalHumanAlertRouting);
}

export function saveDigitalHumanAlertRoutingEnabled(enabled) {
  return apiPost(API.digitalHumanAlertRoutingToggle, { enabled: Boolean(enabled) });
}

export function createDigitalHumanAlertRoute(payload) {
  return apiPost(API.digitalHumanAlertRoutingCreate, payload);
}

export function updateDigitalHumanAlertRoute(routeId, payload) {
  return apiPost(API.digitalHumanAlertRoutingUpdate, { id: routeId, ...payload });
}

export function deleteDigitalHumanAlertRoute(routeId) {
  return apiPost(API.digitalHumanAlertRoutingDelete, { id: routeId });
}

export function listDigitalHumanMonitorLogs() {
  return apiGet(API.digitalHumanMonitorLogs);
}

export function reanalyzeDigitalHumanMonitorLog(logId) {
  return apiPost(API.digitalHumanMonitorLogReanalyze, { id: logId });
}

export function getDigitalHumanLogNodeStatus() {
  return apiGet(API.digitalHumanMonitorLogNodeStatus);
}

export function getDigitalHumanOpsReport(rangeKey) {
  return apiGet(API.digitalHumanOpsReport, { range: rangeKey });
}

export function getDigitalHumanOpsAiInsight(rangeKey) {
  return apiGet(API.digitalHumanOpsAiInsight, { range: rangeKey });
}

export function listDigitalHumanJwtAccounts() {
  return apiGet(API.digitalHumanSystemSettingsJwtAccounts);
}

export function createDigitalHumanJwtAccount(payload) {
  return apiPost(API.digitalHumanSystemSettingsJwtAccountCreate, {
    projectName: normalizeText(payload.projectName),
    tenantName: normalizeText(payload.tenantName),
    tokenTtlMinutes: Number(payload.tokenTtlMinutes),
  });
}

export function rotateDigitalHumanJwtAccountSecret(accountUuid) {
  return apiPost(API.digitalHumanSystemSettingsJwtAccountRotateSecret, { accountUuid });
}

export function updateDigitalHumanJwtAccountStatus(accountUuid, enabled) {
  return apiPost(API.digitalHumanSystemSettingsJwtAccountStatus, { accountUuid, enabled: Boolean(enabled) });
}

export function deleteDigitalHumanJwtAccount(accountUuid) {
  return apiPost(API.digitalHumanSystemSettingsJwtAccountDelete, { accountUuid });
}

export function listDigitalHumanDeviceAuthorizations(filters = {}) {
  return apiGet(API.digitalHumanSystemSettingsDeviceAuthorizations, filters);
}

export function getDigitalHumanDeviceAuthorizationDetail(id) {
  return apiGet(API.digitalHumanSystemSettingsDeviceAuthorizationDetail, { id });
}

export function updateDigitalHumanDeviceAuthorization(id, payload) {
  return apiPost(API.digitalHumanSystemSettingsDeviceAuthorizationUpdate, {
    id,
    enabled: Boolean(payload.enabled),
    displayName: normalizeText(payload.displayName),
    region: normalizeText(payload.region),
    rustdeskId: normalizeText(payload.rustdeskId),
    rustdeskPassword: normalizeText(payload.rustdeskPassword),
    validFrom: normalizeText(payload.validFrom),
    validUntil: normalizeText(payload.validUntil),
  });
}

export function deleteDigitalHumanDeviceAuthorization(id) {
  return apiPost(API.digitalHumanSystemSettingsDeviceAuthorizationDelete, { id });
}

export function getDigitalHumanAiDiagnosisConfig() {
  return apiGet(API.digitalHumanSystemSettingsAiDiagnosis);
}

export function saveDigitalHumanAiDiagnosisConfig(payload) {
  return apiPost(API.digitalHumanSystemSettingsAiDiagnosisSave, buildAiPayload(payload));
}

export function testDigitalHumanAiDiagnosisConnection(payload) {
  return apiPost(API.digitalHumanSystemSettingsAiDiagnosisTest, buildAiPayload(payload));
}
