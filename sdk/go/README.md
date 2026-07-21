# Beacon Go SDK

Go SDK for Beacon developer integration and core OpenAPI query endpoints.

## Included APIs

- `Login()`
- `GetControls()` / `GetStreamInfo()`
- `GetAlgorithms()` / `GetAlgorithmInfo()`
- `ReportDetection()`
- `UploadAlarm()`
- `CheckVersion()`
- `GetLicenseInfo()`
- `GetLicenseUsage()`
- `GetControlData()`
- `GetStreamData()`
- `GetPlatformBasicInfo()`
- `GetPlatformStorageInfo()`
- `AcquireLicenseLease()`
- `RenewLicenseLease()`
- `ReleaseLicenseLease()`
- `AddRecordingPlan()` / `ListRecordingPlans()` / `EditRecordingPlan()` / `DeleteRecordingPlan()`
- `AddTaskPlan()` / `ListTaskPlans()` / `EditTaskPlan()` / `DeleteTaskPlan()`
- `ListRecordingFiles()`
- `GetRecordingFilePlayURL()`
- `StartRecording()` / `StopRecording()`
- `CaptureSnapshot()`
- `ListFaces()`
- `AddFace()` / `DeleteFace()`
- `SearchFace()`
- `EnableFaceSearch()` / `DisableFaceSearch()`
- `CloudPresignImage()` / `CloudIngestAlarmCreated()`
- `OpsCleanup()` / `OpsOutboxReplay()` / `OpsSetLoggingLevel()`
- `OpsHealth()` / `OpsReady()` / `OpsMetrics()`
- `OpsAuditExport()` / `OpsDiagnosticsExport()`
- `OpsUpgradeList()` / `OpsUpgradeValidate()` / `OpsUpgradeApply()` / `OpsUpgradeRollback()` / `OpsUpgradeUpload()`
- `ImageDetect()`
- `AudioDetect()`
- `Discover()`
- `GetAllStreamDataOpen()` / `GetAllAlgorithmFlowDataOpen()`
- `GetAllCoreProcessDataOpen()` / `GetAllCoreProcessData2Open()`
- `RestartSoftware()` / `RestartSystem()`
- `DownloadFile()`

## Example

```go
package main

import (
	"log"

	beaconsdk "github.com/skygazer42/Beacon/sdk/go"
)

func main() {
	client, err := beaconsdk.NewClient(
		"http://localhost:9991",
		beaconsdk.WithOpenAPIToken("token-open-001"),
		beaconsdk.WithCloudEdgeToken("edge-token-001"),
	)
	if err != nil {
		log.Fatal(err)
	}

	if _, err := client.Login("admin", "<your-admin-password>", ""); err != nil {
		log.Fatal(err)
	}

	controls, err := client.GetControls()
	if err != nil {
		log.Fatal(err)
	}
	log.Println(controls)

	licenseInfo, err := client.GetLicenseInfo()
	if err != nil {
		log.Fatal(err)
	}
	log.Println(licenseInfo)

	lease, err := client.AcquireLicenseLease(beaconsdk.AcquireLicenseLeaseRequest{
		NodeID:        "node-1",
		ControlCode:   "ctrl-1",
		AlgorithmCode: "alg-1",
	})
	if err != nil {
		log.Fatal(err)
	}
	log.Println(lease)

	recordingPlans, err := client.ListRecordingPlans(map[string]any{})
	if err != nil {
		log.Fatal(err)
	}
	log.Println(recordingPlans)

	recordingFiles, err := client.ListRecordingFiles(map[string]any{"streamCode": "stream001"})
	if err != nil {
		log.Fatal(err)
	}
	log.Println(recordingFiles)

	faces, err := client.ListFaces()
	if err != nil {
		log.Fatal(err)
	}
	log.Println(faces)

	ops, err := client.OpsCleanup(map[string]any{"targets": []string{"logs"}, "dry_run": true})
	if err != nil {
		log.Fatal(err)
	}
	log.Println(ops)

	if _, err := client.ReportDetection(beaconsdk.ReportDetectionRequest{
		ControlCode:  "control_12345",
		TriggerAlarm: true,
		Detections: []beaconsdk.Detection{
			{ClassName: "person", Confidence: 0.95},
		},
	}); err != nil {
		log.Fatal(err)
	}

	asr, err := client.AudioDetect(map[string]any{
		"code":         "asr-api",
		"audio_base64": "YmFy",
	})
	if err != nil {
		log.Fatal(err)
	}
	log.Println(asr)
}
```

## Verification

Run each SDK's native core tests directly from the repository root:

```bash
python -m unittest sdk/python/tests/test_client.py
node --test sdk/javascript/tests/client.test.mjs
cd sdk/go && go test ./...
```

The Go runtime test requires a Go toolchain; absence of that toolchain is an environment gap, not a passing static fallback.
