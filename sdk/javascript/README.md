# Beacon JavaScript SDK

JavaScript SDK for Beacon developer integration and core OpenAPI query endpoints.

## Included APIs

- `login()`
- `getControls()` / `getStreamInfo()`
- `getAlgorithms()` / `getAlgorithmInfo()`
- `reportDetection()`
- `uploadAlarm()`
- `checkVersion()`
- `getLicenseInfo()`
- `getLicenseUsage()`
- `getControlData()`
- `getStreamData()`
- `getPlatformBasicInfo()`
- `getPlatformStorageInfo()`
- `acquireLicenseLease()`
- `renewLicenseLease()`
- `releaseLicenseLease()`
- `addRecordingPlan()` / `listRecordingPlans()` / `editRecordingPlan()` / `deleteRecordingPlan()`
- `addTaskPlan()` / `listTaskPlans()` / `editTaskPlan()` / `deleteTaskPlan()`
- `listRecordingFiles()`
- `getRecordingFilePlayUrl()`
- `startRecording()` / `stopRecording()`
- `captureSnapshot()`
- `listFaces()`
- `addFace()` / `deleteFace()`
- `searchFace()`
- `enableFaceSearch()` / `disableFaceSearch()`
- `cloudPresignImage()` / `cloudIngestAlarmCreated()`
- `opsCleanup()` / `opsOutboxReplay()` / `opsSetLoggingLevel()`
- `opsHealth()` / `opsReady()` / `opsMetrics()`
- `opsAuditExport()` / `opsDiagnosticsExport()`
- `opsUpgradeList()` / `opsUpgradeValidate()` / `opsUpgradeApply()` / `opsUpgradeRollback()` / `opsUpgradeUpload()`
- `imageDetect()`
- `audioDetect()`
- `discover()`
- `getAllStreamData()` / `getAllAlgorithmFlowData()`
- `getAllCoreProcessData()` / `getAllCoreProcessData2()`
- `restartSoftware()` / `restartSystem()`
- `downloadFile()`

## Example

```javascript
import { BeaconClient } from "./beacon-sdk.mjs";

const client = new BeaconClient("http://localhost:9991", {
  openApiToken: "token-open-001",
  cloudEdgeToken: "edge-token-001",
});
await client.login("admin", "<your-admin-password>");

const controls = await client.getControls();
console.log(controls);
console.log(await client.getLicenseUsage());
console.log(await client.getPlatformStorageInfo());
console.log(await client.acquireLicenseLease({
  nodeId: "node-1",
  controlCode: "ctrl-1",
  algorithmCode: "alg-1",
}));
console.log(await client.listRecordingPlans());
console.log(await client.listRecordingFiles({ streamCode: "stream001" }));
console.log(await client.listFaces());
console.log(await client.opsCleanup({ targets: ["logs"], dry_run: true }));
console.log(await client.audioDetect({ code: "asr-api", audio_base64: "YmFy", language: "zh-CN" }));

await client.reportDetection({
  controlCode: "control_12345",
  detections: [{ class_name: "person", confidence: 0.95 }],
  triggerAlarm: true,
});
```
