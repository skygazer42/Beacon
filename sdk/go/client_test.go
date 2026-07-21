package beaconsdk

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"reflect"
	"strconv"
	"strings"
	"testing"
)

const (
	newClientErrFmt      = "NewClient() error = %v"
	contentTypeHeader    = "Content-Type"
	decodeRequestErrFmt  = "decode request: %v"
	bodiesLenContext     = "bodies len"
	tokensLenContext     = "tokens len"
	fakeImageBase64      = "ZmFrZS1pbWFnZQ=="
	beaconTokenHeader    = "X-Beacon-Token"
	openAPIToken         = "token-open-001"
	controlCodeCtrl1     = "ctrl-1"
	streamCodeStream1    = "stream-1"
	nodeCodeNode1        = "node-1"
	pathMismatchFmt      = "path[%d] = %q, want %q"
	tokenMismatchFmt     = "token[%d] = %q, want %s"
	leaseIDLease1        = "lease-1"
	recordingPathDemoMP4 = "recordings/stream001/demo.mp4"
)

func TestLoginPersistsSessionCookieForDeveloperEndpoints(t *testing.T) {
	var lastCookie string

	mux := http.NewServeMux()
	mux.HandleFunc("/login", func(w http.ResponseWriter, r *http.Request) {
		requireNoErr(t, r.ParseForm(), "parse form")
		requireEqual(t, r.Form.Get("username"), "admin", "username")
		requireEqual(t, r.Form.Get("password"), "pass12345", "password")
		requireEqual(t, r.Form.Get("verify_code"), "1234", "verify_code")
		http.SetCookie(w, &http.Cookie{Name: "v3_sessionid", Value: "session123", Path: "/", Secure: true, HttpOnly: true})
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "登录成功"})
	})
	mux.HandleFunc("/developer/getStreamInfo", func(w http.ResponseWriter, r *http.Request) {
		lastCookie = r.Header.Get("Cookie")
		writeJSON(t, w, map[string]any{
			"code": 1000,
			"msg":  "success",
			"data": []map[string]any{{"control_code": "c001"}},
		})
	})
	server := httptest.NewTLSServer(mux)
	defer server.Close()

	client, err := NewClient(server.URL, WithHTTPClient(server.Client()))
	requireNoErr(t, err, "NewClient()")
	loginResp, err := client.Login("admin", "pass12345", "1234")
	requireNoErr(t, err, "Login()")
	requireEqual(t, loginResp.Code, 1000, "Login() code")

	controls, err := client.GetControls()
	requireNoErr(t, err, "GetControls()")
	requireEqual(t, len(controls), 1, "GetControls() len")
	requireEqual(t, controls[0]["control_code"], "c001", "GetControls() control_code")
	requireEqual(t, lastCookie, "v3_sessionid=session123", "developer cookie")
}

func TestGetAlgorithmsReturnsDataArray(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/developer/getAlgorithmInfo" {
			http.NotFound(w, r)
			return
		}
		writeJSON(t, w, map[string]any{
			"code": 1000,
			"msg":  "success",
			"data": []map[string]any{{"code": "algo001"}},
		})
	}))
	defer server.Close()

	client, err := NewClient(server.URL)
	if err != nil {
		t.Fatalf(newClientErrFmt, err)
	}

	algorithms, err := client.GetAlgorithms()
	if err != nil {
		t.Fatalf("GetAlgorithms() error = %v", err)
	}
	if len(algorithms) != 1 || algorithms[0]["code"] != "algo001" {
		t.Fatalf("GetAlgorithms() = %#v, want algo001", algorithms)
	}
}

func TestReportDetectionPostsExpectedJSONPayload(t *testing.T) {
	var got map[string]any

	mux := http.NewServeMux()
	mux.HandleFunc("/developer/algorithmCallback", func(w http.ResponseWriter, r *http.Request) {
		requireEqual(t, r.Header.Get(contentTypeHeader), "application/json", "content-type")
		got = decodeJSONBody(t, r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success"})
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	client := mustNewClient(t, server.URL)
	resp, err := client.ReportDetection(ReportDetectionRequest{
		ControlCode:  "ctrl001",
		FrameIndex:   12,
		Timestamp:    1702700000,
		TriggerAlarm: true,
		ImageBase64:  fakeImageBase64,
		Detections: []Detection{
			{ClassName: "person", Confidence: 0.95},
		},
	})
	requireNoErr(t, err, "ReportDetection()")
	requireEqual(t, resp.Code, 1000, "ReportDetection() code")
	requireEqual(t, got["control_code"], "ctrl001", "control_code")
	requireEqual(t, got["frame_index"], float64(12), "frame_index")
	requireEqual(t, got["timestamp"], float64(1702700000), "timestamp")
	requireEqual(t, got["trigger_alarm"], true, "trigger_alarm")
	requireEqual(t, got["image_base64"], fakeImageBase64, "image_base64")
	detections := requireAnySlice(t, got["detections"], "detections")
	requireEqual(t, len(detections), 1, "detections len")
}

func TestUploadAlarmPostsOpenAPITokenAndJSONPayload(t *testing.T) {
	var got map[string]any
	var gotToken string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/open/alarm/upload" {
			http.NotFound(w, r)
			return
		}
		gotToken = r.Header.Get(beaconTokenHeader)
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Fatalf(decodeRequestErrFmt, err)
		}
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"id": 1}})
	}))
	defer server.Close()

	client, err := NewClient(server.URL, WithOpenAPIToken(openAPIToken))
	if err != nil {
		t.Fatalf(newClientErrFmt, err)
	}

	resp, err := client.UploadAlarm(UploadAlarmRequest{
		ControlCode: "C001",
		Desc:        "sdk upload",
		ImageBase64: fakeImageBase64,
		AlarmType:   "crossing",
	})
	if err != nil {
		t.Fatalf("UploadAlarm() error = %v", err)
	}
	if resp.Code != 1000 {
		t.Fatalf("UploadAlarm() code = %d, want 1000", resp.Code)
	}
	if gotToken != openAPIToken {
		t.Fatalf("%s = %q, want %s", beaconTokenHeader, gotToken, openAPIToken)
	}
	if got["control_code"] != "C001" || got["alarm_type"] != "crossing" {
		t.Fatalf("UploadAlarm() payload = %#v", got)
	}
}

func TestNonSuccessResponseReturnsAPIError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, map[string]any{"code": 0, "msg": "密码错误"})
	}))
	defer server.Close()

	client, err := NewClient(server.URL)
	if err != nil {
		t.Fatalf(newClientErrFmt, err)
	}

	_, err = client.Login("admin", "wrong", "")
	if err == nil {
		t.Fatal("Login() error = nil, want APIError")
	}

	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("error = %T, want *APIError", err)
	}
	if apiErr.Code != 0 {
		t.Fatalf("APIError.Code = %d, want 0", apiErr.Code)
	}
	if apiErr.Error() != "密码错误" {
		t.Fatalf("APIError.Error() = %q, want 密码错误", apiErr.Error())
	}
}

func TestCheckVersionForwardsQueryParamsAndReturnsData(t *testing.T) {
	var gotQuery url.Values
	var gotToken string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/open/checkVersion" {
			http.NotFound(w, r)
			return
		}
		gotQuery = r.URL.Query()
		gotToken = r.Header.Get(headerBeaconToken)
		writeJSON(t, w, map[string]any{
			"code": 1000,
			"msg":  "success",
			"data": map[string]any{"currentVersion": "4.22.0", "hasUpdate": false},
		})
	}))
	defer server.Close()

	client, err := NewClient(server.URL, WithOpenAPIToken("token-open-001"))
	if err != nil {
		t.Fatalf(newClientErrFmt, err)
	}

	data, err := client.CheckVersion(map[string]string{
		"infer_engine":         "openvino",
		"infer_engine_version": "2024.4",
	})
	if err != nil {
		t.Fatalf("CheckVersion() error = %v", err)
	}
	if data["currentVersion"] != "4.22.0" {
		t.Fatalf("CheckVersion() data = %#v", data)
	}
	if got := gotQuery.Get("infer_engine"); got != "openvino" {
		t.Fatalf("infer_engine = %q, want openvino", got)
	}
	if got := gotQuery.Get("infer_engine_version"); got != "2024.4" {
		t.Fatalf("infer_engine_version = %q, want 2024.4", got)
	}
	if gotToken != "token-open-001" {
		t.Fatalf("X-Beacon-Token = %q, want token-open-001", gotToken)
	}
}

func TestCoreOpenAPIQueriesReturnDataAndSendToken(t *testing.T) {
	var paths []string
	var tokens []string

	record := func(r *http.Request) {
		paths = append(paths, r.URL.RequestURI())
		tokens = append(tokens, r.Header.Get(beaconTokenHeader))
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/open/license/info", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"license_id": "LIC-1"}})
	})
	mux.HandleFunc("/open/license/usage", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"active_controls": 2}})
	})
	mux.HandleFunc("/open/getControlData", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": []map[string]any{{"code": controlCodeCtrl1}}})
	})
	mux.HandleFunc("/open/getStreamData", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": []map[string]any{{"code": streamCodeStream1}}})
	})
	mux.HandleFunc("/open/platform/basicInfo", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"nodeCode": nodeCodeNode1}})
	})
	mux.HandleFunc("/open/platform/storageInfo", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"storageRootPath": "/data"}})
	})

	server := httptest.NewServer(mux)
	defer server.Close()

	client := mustNewClient(t, server.URL, WithOpenAPIToken(openAPIToken))

	info, err := client.GetLicenseInfo()
	requireNoErr(t, err, "GetLicenseInfo()")
	requireEqual(t, info["license_id"], "LIC-1", "license_id")
	usage, err := client.GetLicenseUsage()
	requireNoErr(t, err, "GetLicenseUsage()")
	requireEqual(t, usage["active_controls"], float64(2), "active_controls")
	controls, err := client.GetControlData(controlCodeCtrl1)
	requireNoErr(t, err, "GetControlData()")
	requireEqual(t, len(controls), 1, "controls len")
	requireEqual(t, controls[0]["code"], controlCodeCtrl1, "control code")
	streams, err := client.GetStreamData(streamCodeStream1)
	requireNoErr(t, err, "GetStreamData()")
	requireEqual(t, len(streams), 1, "streams len")
	requireEqual(t, streams[0]["code"], streamCodeStream1, "stream code")
	basic, err := client.GetPlatformBasicInfo()
	requireNoErr(t, err, "GetPlatformBasicInfo()")
	requireEqual(t, basic["nodeCode"], nodeCodeNode1, "nodeCode")
	storage, err := client.GetPlatformStorageInfo()
	requireNoErr(t, err, "GetPlatformStorageInfo()")
	requireEqual(t, storage["storageRootPath"], "/data", "storageRootPath")

	expectedPaths := []string{
		"/open/license/info",
		"/open/license/usage",
		"/open/getControlData?code=" + controlCodeCtrl1,
		"/open/getStreamData?code=" + streamCodeStream1,
		"/open/platform/basicInfo",
		"/open/platform/storageInfo",
	}
	requirePathsAndTokens(t, paths, tokens, expectedPaths, openAPIToken)
}

func TestLicenseLeaseMethodsPostOpenAPIJSONPayloads(t *testing.T) {
	var paths []string
	var tokens []string
	var bodies []map[string]any

	record := func(r *http.Request) {
		paths = append(paths, r.URL.Path)
		tokens = append(tokens, r.Header.Get(beaconTokenHeader))
		bodies = append(bodies, decodeJSONBody(t, r))
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/open/license/lease/acquire", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"lease_id": leaseIDLease1, "expires_at": "2026-03-09T10:00:00"}})
	})
	mux.HandleFunc("/open/license/lease/renew", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"expires_at": "2026-03-09T10:30:00"}})
	})
	mux.HandleFunc("/open/license/lease/release", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success"})
	})

	server := httptest.NewServer(mux)
	defer server.Close()

	client := mustNewClient(t, server.URL, WithOpenAPIToken(openAPIToken))

	acquire, err := client.AcquireLicenseLease(AcquireLicenseLeaseRequest{
		NodeID:        nodeCodeNode1,
		ControlCode:   controlCodeCtrl1,
		AlgorithmCode: "alg-1",
		StreamCode:    "cam-001",
		TTLSeconds:    180,
	})
	requireNoErr(t, err, "AcquireLicenseLease()")
	requireEqual(t, acquire["lease_id"], leaseIDLease1, "lease_id")

	renew, err := client.RenewLicenseLease(RenewLicenseLeaseRequest{
		LeaseID:    leaseIDLease1,
		TTLSeconds: 240,
	})
	requireNoErr(t, err, "RenewLicenseLease()")
	requireEqual(t, renew["expires_at"], "2026-03-09T10:30:00", "expires_at")

	release, err := client.ReleaseLicenseLease(leaseIDLease1)
	requireNoErr(t, err, "ReleaseLicenseLease()")
	requireEqual(t, release.Code, 1000, "ReleaseLicenseLease() code")

	expectedPaths := []string{
		"/open/license/lease/acquire",
		"/open/license/lease/renew",
		"/open/license/lease/release",
	}
	requirePathsAndTokens(t, paths, tokens, expectedPaths, openAPIToken)
	requireEqual(t, len(bodies), 3, bodiesLenContext)
	requireEqual(t, bodies[0]["node_id"], nodeCodeNode1, "acquire node_id")
	requireEqual(t, bodies[0]["stream_code"], "cam-001", "acquire stream_code")
	requireEqual(t, bodies[0]["ttl_seconds"], float64(180), "acquire ttl_seconds")
	requireEqual(t, bodies[1]["lease_id"], leaseIDLease1, "renew lease_id")
	requireEqual(t, bodies[1]["ttl_seconds"], float64(240), "renew ttl_seconds")
	requireEqual(t, bodies[2]["lease_id"], leaseIDLease1, "release lease_id")
}

func TestRecordingAndTaskPlanMethodsPostOpenAPIJSONPayloads(t *testing.T) {
	var paths []string
	var tokens []string
	var bodies []map[string]any

	record := func(r *http.Request) {
		paths = append(paths, r.URL.Path)
		tokens = append(tokens, r.Header.Get(beaconTokenHeader))
		bodies = append(bodies, decodeJSONBody(t, r))
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/open/recordingPlan/add", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"code": "plan001"}})
	})
	mux.HandleFunc("/open/recordingPlan/list", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": []map[string]any{{"code": "plan001"}}})
	})
	mux.HandleFunc("/open/recordingPlan/edit", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"enabled": false}})
	})
	mux.HandleFunc("/open/recordingPlan/delete", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"deleted": 1}})
	})
	mux.HandleFunc("/open/taskPlan/add", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"code": "task001"}})
	})
	mux.HandleFunc("/open/taskPlan/list", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": []map[string]any{{"code": "task001"}}})
	})
	mux.HandleFunc("/open/taskPlan/edit", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"enabled": false}})
	})
	mux.HandleFunc("/open/taskPlan/delete", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"deleted": 1}})
	})

	server := httptest.NewServer(mux)
	defer server.Close()

	client := mustNewClient(t, server.URL, WithOpenAPIToken(openAPIToken))

	recordingAdd, err := client.AddRecordingPlan(map[string]any{
		"code":       "plan001",
		"name":       "Plan 1",
		"streamCode": "stream001",
		"startTime":  "00:00",
		"endTime":    "23:59",
	})
	requireNoErr(t, err, "AddRecordingPlan()")
	requireEqual(t, recordingAdd["code"], "plan001", "recording add code")
	recordingList, err := client.ListRecordingPlans(map[string]any{})
	requireNoErr(t, err, "ListRecordingPlans()")
	requireEqual(t, len(recordingList), 1, "recording list len")
	requireEqual(t, recordingList[0]["code"], "plan001", "recording list code")
	recordingEdit, err := client.EditRecordingPlan(map[string]any{"code": "plan001", "enabled": 0})
	requireNoErr(t, err, "EditRecordingPlan()")
	requireEqual(t, recordingEdit["enabled"], false, "recording edit enabled")
	recordingDelete, err := client.DeleteRecordingPlan("plan001")
	requireNoErr(t, err, "DeleteRecordingPlan()")
	requireEqual(t, recordingDelete["deleted"], float64(1), "recording delete deleted")

	taskAdd, err := client.AddTaskPlan(map[string]any{
		"code":         "task001",
		"name":         "Task 1",
		"taskType":     "restart_software",
		"scheduleType": "daily",
		"runTime":      "02:00",
	})
	requireNoErr(t, err, "AddTaskPlan()")
	requireEqual(t, taskAdd["code"], "task001", "task add code")
	taskList, err := client.ListTaskPlans(map[string]any{})
	requireNoErr(t, err, "ListTaskPlans()")
	requireEqual(t, len(taskList), 1, "task list len")
	requireEqual(t, taskList[0]["code"], "task001", "task list code")
	taskEdit, err := client.EditTaskPlan(map[string]any{"code": "task001", "enabled": 0})
	requireNoErr(t, err, "EditTaskPlan()")
	requireEqual(t, taskEdit["enabled"], false, "task edit enabled")
	taskDelete, err := client.DeleteTaskPlan("task001")
	requireNoErr(t, err, "DeleteTaskPlan()")
	requireEqual(t, taskDelete["deleted"], float64(1), "task delete deleted")

	expectedPaths := []string{
		"/open/recordingPlan/add",
		"/open/recordingPlan/list",
		"/open/recordingPlan/edit",
		"/open/recordingPlan/delete",
		"/open/taskPlan/add",
		"/open/taskPlan/list",
		"/open/taskPlan/edit",
		"/open/taskPlan/delete",
	}
	requirePathsAndTokens(t, paths, tokens, expectedPaths, openAPIToken)
	requireEqual(t, len(bodies), 8, bodiesLenContext)
	requireEqual(t, bodies[0]["code"], "plan001", "recording add body code")
	requireEqual(t, bodies[0]["streamCode"], "stream001", "recording add body streamCode")
	requireEqual(t, bodies[1]["code"], nil, "recording list body code")
	requireEqual(t, bodies[4]["code"], "task001", "task add body code")
	requireEqual(t, bodies[4]["taskType"], "restart_software", "task add body taskType")
	requireEqual(t, bodies[7]["code"], "task001", "task delete body code")
}

func TestRecordingRuntimeMethodsUseOpenAPIJSONPayloads(t *testing.T) {
	var paths []string
	var tokens []string
	var bodies []map[string]any

	record := func(r *http.Request) {
		paths = append(paths, r.URL.Path)
		tokens = append(tokens, r.Header.Get(beaconTokenHeader))
		bodies = append(bodies, decodeJSONBody(t, r))
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/open/recording/file/list", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": []map[string]any{{"filename": "demo.mp4"}}, "total": 1})
	})
	mux.HandleFunc("/open/recording/file/playUrl", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"play_url": "http://demo/open/fileService/recordings/a.mp4"}})
	})
	mux.HandleFunc("/open/recording/startRecording", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"record_id": "rec-1", "save_path": recordingPathDemoMP4}})
	})
	mux.HandleFunc("/open/recording/stopRecording", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"save_path": recordingPathDemoMP4, "duration": 1.2}})
	})
	mux.HandleFunc("/open/recording/captureSnapshot", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"image_path": "snapshots/stream001/demo.jpg"}})
	})

	server := httptest.NewServer(mux)
	defer server.Close()

	client := mustNewClient(t, server.URL, WithOpenAPIToken(openAPIToken))

	files, err := client.ListRecordingFiles(map[string]any{"streamCode": "stream001"})
	requireNoErr(t, err, "ListRecordingFiles()")
	requireEqual(t, len(files), 1, "files len")
	requireEqual(t, files[0]["filename"], "demo.mp4", "files[0].filename")
	playURL, err := client.GetRecordingFilePlayURL(map[string]any{"relPath": recordingPathDemoMP4})
	requireNoErr(t, err, "GetRecordingFilePlayURL()")
	requireEqual(t, playURL["play_url"], "http://demo/open/fileService/recordings/a.mp4", "play_url")
	start, err := client.StartRecording(map[string]any{"streamCode": "stream001", "streamUrl": "rtsp://127.0.0.1/demo", "duration": 10, "format": "mp4", "recordAudio": 1})
	requireNoErr(t, err, "StartRecording()")
	requireEqual(t, start["record_id"], "rec-1", "record_id")
	stop, err := client.StopRecording(map[string]any{"streamCode": "stream001"})
	requireNoErr(t, err, "StopRecording()")
	requireEqual(t, stop["save_path"], recordingPathDemoMP4, "save_path")
	snapshot, err := client.CaptureSnapshot(map[string]any{"streamCode": "stream001", "streamUrl": "rtsp://127.0.0.1/demo"})
	requireNoErr(t, err, "CaptureSnapshot()")
	requireEqual(t, snapshot["image_path"], "snapshots/stream001/demo.jpg", "image_path")

	expectedPaths := []string{
		"/open/recording/file/list",
		"/open/recording/file/playUrl",
		"/open/recording/startRecording",
		"/open/recording/stopRecording",
		"/open/recording/captureSnapshot",
	}
	requirePathsAndTokens(t, paths, tokens, expectedPaths, openAPIToken)
	requireEqual(t, len(bodies), 5, bodiesLenContext)
	requireEqual(t, bodies[0]["streamCode"], "stream001", "list files streamCode")
	requireEqual(t, bodies[1]["relPath"], recordingPathDemoMP4, "play url relPath")
	requireEqual(t, bodies[2]["streamCode"], "stream001", "start recording streamCode")
	requireEqual(t, bodies[2]["recordAudio"], float64(1), "start recording recordAudio")
	requireEqual(t, bodies[4]["streamCode"], "stream001", "snapshot streamCode")
}

func TestFaceMethodsUseOpenAPIJSONPayloads(t *testing.T) {
	var paths []string
	var tokens []string
	var bodies []map[string]any

	record := func(r *http.Request) {
		paths = append(paths, r.URL.Path)
		tokens = append(tokens, r.Header.Get(beaconTokenHeader))
		bodies = append(bodies, decodeJSONBody(t, r))
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/open/face/list", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"count": 1, "items": []map[string]any{{"id": "alice"}}}})
	})
	mux.HandleFunc("/open/face/add", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"code": 1000, "msg": "success"}})
	})
	mux.HandleFunc("/open/face/search", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"found": false}})
	})
	mux.HandleFunc("/open/face/enable", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"code": 1000, "msg": "success"}})
	})
	mux.HandleFunc("/open/face/disable", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"code": 1000, "msg": "success"}})
	})
	mux.HandleFunc("/open/face/delete", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"code": 1000, "msg": "success"}})
	})

	server := httptest.NewServer(mux)
	defer server.Close()

	client := mustNewClient(t, server.URL, WithOpenAPIToken(openAPIToken))

	list, err := client.ListFaces()
	requireNoErr(t, err, "ListFaces()")
	requireEqual(t, list["count"], float64(1), "count")
	add, err := client.AddFace(map[string]any{"id": "alice", "name": "Alice", "embedding": []int{1, 0}})
	requireNoErr(t, err, "AddFace()")
	requireEqual(t, add["code"], float64(1000), "add code")
	search, err := client.SearchFace(map[string]any{"embedding": []int{1, 0}, "minScore": 0.8})
	requireNoErr(t, err, "SearchFace()")
	requireEqual(t, search["found"], false, "found")
	enable, err := client.EnableFaceSearch()
	requireNoErr(t, err, "EnableFaceSearch()")
	requireEqual(t, enable["code"], float64(1000), "enable code")
	disable, err := client.DisableFaceSearch()
	requireNoErr(t, err, "DisableFaceSearch()")
	requireEqual(t, disable["code"], float64(1000), "disable code")
	del, err := client.DeleteFace("alice")
	requireNoErr(t, err, "DeleteFace()")
	requireEqual(t, del["code"], float64(1000), "delete code")

	expectedPaths := []string{
		"/open/face/list",
		"/open/face/add",
		"/open/face/search",
		"/open/face/enable",
		"/open/face/disable",
		"/open/face/delete",
	}
	requirePathsAndTokens(t, paths, tokens, expectedPaths, openAPIToken)
	requireEqual(t, len(bodies), 6, bodiesLenContext)
	requireEqual(t, bodies[1]["id"], "alice", "add face body id")
	requireEqual(t, bodies[2]["minScore"], 0.8, "search face body minScore")
	requireEqual(t, bodies[5]["id"], "alice", "delete face body id")
}

func TestCloudAndOpsMethodsUseExpectedAuthAndPayloads(t *testing.T) {
	var paths []string
	var authz []string
	var tokens []string
	var bodies []map[string]any

	record := func(r *http.Request) {
		paths = append(paths, r.URL.Path)
		authz = append(authz, r.Header.Get("Authorization"))
		tokens = append(tokens, r.Header.Get(beaconTokenHeader))
		bodies = append(bodies, decodeJSONBody(t, r))
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/open/cloud/v1/presign/image", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"bucket": "beacon-alarms"}})
	})
	mux.HandleFunc("/open/cloud/v1/events/alarm-created", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success"})
	})
	mux.HandleFunc("/open/ops/cleanup", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"targets": map[string]any{"logs": map[string]any{"deleted_files": 1}}}})
	})
	mux.HandleFunc("/open/ops/outbox/replay", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"updated": 1}})
	})
	mux.HandleFunc("/open/ops/logging/level", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"level": "DEBUG", "loggers": []string{"app.middleware"}}})
	})

	server := httptest.NewServer(mux)
	defer server.Close()

	client := mustNewClient(t, server.URL, WithOpenAPIToken(openAPIToken), WithCloudEdgeToken("edge-token-001"))

	presign, err := client.CloudPresignImage(map[string]any{"event_id": "evt-1", "content_type": "image/jpeg", "ext": ".jpg"})
	requireNoErr(t, err, "CloudPresignImage()")
	requireEqual(t, presign["bucket"], "beacon-alarms", "bucket")
	ingest, err := client.CloudIngestAlarmCreated(map[string]any{"schema": "beacon.event.v1", "event_id": "evt-1", "event_type": "alarm.created", "event_source": "openAdd"})
	requireNoErr(t, err, "CloudIngestAlarmCreated()")
	requireEqual(t, ingest.Code, 1000, "CloudIngestAlarmCreated code")
	cleanup, err := client.OpsCleanup(map[string]any{"targets": []string{"logs"}, "dry_run": true})
	requireNoErr(t, err, "OpsCleanup()")
	requireTrue(t, cleanup["targets"] != nil, "cleanup targets present")
	replay, err := client.OpsOutboxReplay(map[string]any{"event_id": "evt-1"})
	requireNoErr(t, err, "OpsOutboxReplay()")
	requireEqual(t, replay["updated"], float64(1), "updated")
	level, err := client.OpsSetLoggingLevel(map[string]any{"level": "DEBUG", "logger": "app.middleware"})
	requireNoErr(t, err, "OpsSetLoggingLevel()")
	requireEqual(t, level["level"], "DEBUG", "level")

	expectedPaths := []string{
		"/open/cloud/v1/presign/image",
		"/open/cloud/v1/events/alarm-created",
		"/open/ops/cleanup",
		"/open/ops/outbox/replay",
		"/open/ops/logging/level",
	}
	requireEqual(t, paths, expectedPaths, "paths")
	requireEqual(t, len(authz), 5, "authz len")
	requireEqual(t, len(tokens), 5, tokensLenContext)
	requireEqual(t, len(bodies), 5, bodiesLenContext)
	requireEqual(t, authz[0], "Bearer edge-token-001", "authz[0]")
	requireEqual(t, authz[1], "Bearer edge-token-001", "authz[1]")
	requireEqual(t, tokens[2], openAPIToken, "ops token[2]")
	requireEqual(t, tokens[3], openAPIToken, "ops token[3]")
	requireEqual(t, tokens[4], openAPIToken, "ops token[4]")
	requireEqual(t, bodies[4]["level"], "DEBUG", "logging level body level")
}

func TestOpsExportAndUpgradeMethodsUseExpectedPayloads(t *testing.T) {
	var paths []string
	var tokens []string
	var queries []string
	var contentTypes []string

	record := func(r *http.Request) {
		paths = append(paths, r.URL.Path)
		queries = append(queries, r.URL.RawQuery)
		tokens = append(tokens, r.Header.Get(beaconTokenHeader))
		contentTypes = append(contentTypes, r.Header.Get(contentTypeHeader))
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/open/ops/health", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"status": "ok"}})
	})
	mux.HandleFunc("/open/ops/ready", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"status": "ok"}})
	})
	mux.HandleFunc("/open/ops/metrics", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		_, _ = w.Write([]byte("metric 1\n"))
	})
	mux.HandleFunc("/open/ops/audit/export", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		_, _ = w.Write([]byte("event_type\nlicense.lease.acquire\n"))
	})
	mux.HandleFunc("/open/ops/diagnostics/export", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		_, _ = w.Write([]byte("PK\x03\x04demo"))
	})
	mux.HandleFunc("/open/ops/upgrade/list", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": []map[string]any{{"package_id": "pkg-a"}}})
	})
	mux.HandleFunc("/open/ops/upgrade/validate", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"ok": true, "package_id": "pkg-a"}})
	})
	mux.HandleFunc("/open/ops/upgrade/apply", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"applied_package_id": "pkg-a"}})
	})
	mux.HandleFunc("/open/ops/upgrade/rollback", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"applied_package_id": "pkg-prev"}})
	})
	mux.HandleFunc("/open/ops/upgrade/upload", func(w http.ResponseWriter, r *http.Request) {
		record(r)
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"package_id": "pkg-up"}})
	})

	server := httptest.NewServer(mux)
	defer server.Close()

	client := mustNewClient(t, server.URL, WithOpenAPIToken(openAPIToken))

	health, err := client.OpsHealth()
	requireNoErr(t, err, "OpsHealth()")
	requireEqual(t, health["status"], "ok", "OpsHealth status")
	ready, err := client.OpsReady()
	requireNoErr(t, err, "OpsReady()")
	requireEqual(t, ready["status"], "ok", "OpsReady status")
	metrics, err := client.OpsMetrics()
	requireNoErr(t, err, "OpsMetrics()")
	requireEqual(t, metrics, "metric 1\n", "OpsMetrics value")
	audit, err := client.OpsAuditExport("csv")
	requireNoErr(t, err, "OpsAuditExport()")
	requireEqual(t, string(audit), "event_type\nlicense.lease.acquire\n", "OpsAuditExport value")
	diag, err := client.OpsDiagnosticsExport(nil)
	requireNoErr(t, err, "OpsDiagnosticsExport()")
	requireEqual(t, string(diag), "PK\x03\x04demo", "OpsDiagnosticsExport value")
	list, err := client.OpsUpgradeList(false)
	requireNoErr(t, err, "OpsUpgradeList()")
	requireEqual(t, len(list), 1, "upgrade list len")
	requireEqual(t, list[0]["package_id"], "pkg-a", "upgrade list package_id")
	validate, err := client.OpsUpgradeValidate("pkg-a")
	requireNoErr(t, err, "OpsUpgradeValidate()")
	requireEqual(t, validate["ok"], true, "upgrade validate ok")
	apply, err := client.OpsUpgradeApply(map[string]any{"package_id": "pkg-a"})
	requireNoErr(t, err, "OpsUpgradeApply()")
	requireEqual(t, apply["applied_package_id"], "pkg-a", "upgrade apply applied_package_id")
	rollback, err := client.OpsUpgradeRollback()
	requireNoErr(t, err, "OpsUpgradeRollback()")
	requireEqual(t, rollback["applied_package_id"], "pkg-prev", "upgrade rollback applied_package_id")
	upload, err := client.OpsUpgradeUpload("upgrade.zip", []byte("ZIPDATA"), "application/zip")
	requireNoErr(t, err, "OpsUpgradeUpload()")
	requireEqual(t, upload["package_id"], "pkg-up", "upgrade upload package_id")

	expectedPaths := []string{
		"/open/ops/health",
		"/open/ops/ready",
		"/open/ops/metrics",
		"/open/ops/audit/export",
		"/open/ops/diagnostics/export",
		"/open/ops/upgrade/list",
		"/open/ops/upgrade/validate",
		"/open/ops/upgrade/apply",
		"/open/ops/upgrade/rollback",
		"/open/ops/upgrade/upload",
	}
	requireEqual(t, paths, expectedPaths, "paths")
	requireEqual(t, len(queries), 10, "queries len")
	requireEqual(t, len(tokens), 10, tokensLenContext)
	requireEqual(t, len(contentTypes), 10, "contentTypes len")
	requireEqual(t, queries[3], "format=csv", "audit export query")
	requireEqual(t, queries[6], "package_id=pkg-a", "upgrade validate query")
	requireAllTokens(t, tokens, openAPIToken)
	requireStringContains(t, contentTypes[9], "multipart/form-data", "upload content-type")
}

func TestLowLevelOpenAPIMethodsUseExpectedPayloads(t *testing.T) {
	var paths []string
	var tokens []string
	var queries []string
	var bodies []map[string]any

	record := func(r *http.Request, body map[string]any) {
		paths = append(paths, r.URL.Path)
		queries = append(queries, r.URL.RawQuery)
		tokens = append(tokens, r.Header.Get(beaconTokenHeader))
		bodies = append(bodies, body)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/open/algorithm/imageDetect", func(w http.ResponseWriter, r *http.Request) {
		record(r, decodeJSONBody(t, r))
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"engine": "api", "detects": []any{}}})
	})
	mux.HandleFunc("/open/algorithm/audioDetect", func(w http.ResponseWriter, r *http.Request) {
		record(r, decodeJSONBody(t, r))
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": map[string]any{"engine": "api", "text": "demo asr", "language": "zh-CN", "segments": []any{}}})
	})
	mux.HandleFunc("/open/discover", func(w http.ResponseWriter, r *http.Request) {
		record(r, map[string]any{})
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "info": map[string]any{"code": nodeCodeNode1}})
	})
	mux.HandleFunc("/open/getAllStreamData", func(w http.ResponseWriter, r *http.Request) {
		record(r, map[string]any{})
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": []map[string]any{{"code": streamCodeStream1}}})
	})
	mux.HandleFunc("/open/getAllAlgroithmFlowData", func(w http.ResponseWriter, r *http.Request) {
		record(r, map[string]any{})
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": []map[string]any{{"code": "algo-1"}}})
	})
	mux.HandleFunc("/open/getAllCoreProcessData", func(w http.ResponseWriter, r *http.Request) {
		record(r, map[string]any{})
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "data": []map[string]any{{"process_index": 0}}, "info": map[string]any{"processNum": 1}})
	})
	mux.HandleFunc("/open/getAllCoreProcessData2", func(w http.ResponseWriter, r *http.Request) {
		record(r, map[string]any{})
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "success", "info": map[string]any{"processNum": 1, "controlCount": 2}})
	})
	mux.HandleFunc("/open/platform/restartSoftware", func(w http.ResponseWriter, r *http.Request) {
		record(r, decodeJSONBody(t, r))
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "restarting"})
	})
	mux.HandleFunc("/open/platform/restartSystem", func(w http.ResponseWriter, r *http.Request) {
		record(r, decodeJSONBody(t, r))
		writeJSON(t, w, map[string]any{"code": 1000, "msg": "restarting"})
	})
	mux.HandleFunc("/open/fileService/hello.txt", func(w http.ResponseWriter, r *http.Request) {
		record(r, map[string]any{})
		_, _ = w.Write([]byte("hello"))
	})

	server := httptest.NewServer(mux)
	defer server.Close()

	client := mustNewClient(t, server.URL, WithOpenAPIToken(openAPIToken))

	detect, err := client.ImageDetect(map[string]any{"code": "alg-api", "image_base64": "Zm9v"})
	requireNoErr(t, err, "ImageDetect()")
	requireEqual(t, detect["engine"], "api", "image detect engine")
	audioDetect, err := client.AudioDetect(map[string]any{"code": "asr-api", "audio_base64": "YmFy"})
	requireNoErr(t, err, "AudioDetect()")
	requireEqual(t, audioDetect["text"], "demo asr", "audio detect text")
	discover, err := client.Discover()
	requireNoErr(t, err, "Discover()")
	requireEqual(t, discover["code"], nodeCodeNode1, "discover code")
	streams, err := client.GetAllStreamDataOpen()
	requireNoErr(t, err, "GetAllStreamDataOpen()")
	requireEqual(t, len(streams), 1, "streams len")
	requireEqual(t, streams[0]["code"], streamCodeStream1, "streams[0].code")
	algos, err := client.GetAllAlgorithmFlowDataOpen()
	requireNoErr(t, err, "GetAllAlgorithmFlowDataOpen()")
	requireEqual(t, len(algos), 1, "algos len")
	requireEqual(t, algos[0]["code"], "algo-1", "algos[0].code")
	core, err := client.GetAllCoreProcessDataOpen()
	requireNoErr(t, err, "GetAllCoreProcessDataOpen()")
	coreInfo := requireAnyMap(t, core["info"], "core info")
	requireEqual(t, coreInfo["processNum"], float64(1), "core processNum")
	core2, err := client.GetAllCoreProcessData2Open()
	requireNoErr(t, err, "GetAllCoreProcessData2Open()")
	requireEqual(t, core2["controlCount"], float64(2), "controlCount")
	rs, err := client.RestartSoftware()
	requireNoErr(t, err, "RestartSoftware()")
	requireEqual(t, rs.Code, 1000, "RestartSoftware code")
	rsys, err := client.RestartSystem()
	requireNoErr(t, err, "RestartSystem()")
	requireEqual(t, rsys.Code, 1000, "RestartSystem code")
	file, err := client.DownloadFile("hello.txt")
	requireNoErr(t, err, "DownloadFile()")
	requireEqual(t, string(file), "hello", "downloaded file")

	expectedPaths := []string{
		"/open/algorithm/imageDetect",
		"/open/algorithm/audioDetect",
		"/open/discover",
		"/open/getAllStreamData",
		"/open/getAllAlgroithmFlowData",
		"/open/getAllCoreProcessData",
		"/open/getAllCoreProcessData2",
		"/open/platform/restartSoftware",
		"/open/platform/restartSystem",
		"/open/fileService/hello.txt",
	}
	requireEqual(t, paths, expectedPaths, "paths")
	requireEqual(t, len(queries), 10, "queries len")
	requireAllTokens(t, tokens, openAPIToken)
	requireEqual(t, len(bodies), 10, bodiesLenContext)
	requireEqual(t, bodies[0]["code"], "alg-api", "image detect body code")
	requireEqual(t, bodies[1]["code"], "asr-api", "audio detect body code")
}

func writeJSON(t *testing.T, w http.ResponseWriter, payload any) {
	t.Helper()
	w.Header().Set(contentTypeHeader, "application/json")
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		t.Fatalf("encode json: %v", err)
	}
}

func mustNewClient(t *testing.T, baseURL string, opts ...Option) *Client {
	t.Helper()
	client, err := NewClient(baseURL, opts...)
	if err != nil {
		t.Fatalf(newClientErrFmt, err)
	}
	return client
}

func requireNoErr(t *testing.T, err error, context string) {
	t.Helper()
	if err != nil {
		t.Fatalf("%s error = %v", context, err)
	}
}

func requireErr(t *testing.T, err error, context string) {
	t.Helper()
	if err == nil {
		t.Fatalf("%s error = nil, want error", context)
	}
}

func requireTrue(t *testing.T, ok bool, context string) {
	t.Helper()
	if !ok {
		t.Fatalf("expected true: %s", context)
	}
}

func requireEqual(t *testing.T, got any, want any, context string) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("%s = %#v, want %#v", context, got, want)
	}
}

func requireAnySlice(t *testing.T, value any, context string) []any {
	t.Helper()
	items, ok := value.([]any)
	if !ok {
		t.Fatalf("%s = %#v, want []any", context, value)
	}
	return items
}

func requireAnyMap(t *testing.T, value any, context string) map[string]any {
	t.Helper()
	items, ok := value.(map[string]any)
	if !ok {
		t.Fatalf("%s = %#v, want map[string]any", context, value)
	}
	return items
}

func decodeJSONBody(t *testing.T, r *http.Request) map[string]any {
	t.Helper()
	body := map[string]any{}
	requireNoErr(t, json.NewDecoder(r.Body).Decode(&body), "decode request")
	return body
}

func requirePathsAndTokens(t *testing.T, gotPaths []string, gotTokens []string, wantPaths []string, wantToken string) {
	t.Helper()
	requireEqual(t, len(gotPaths), len(wantPaths), "paths len")
	requireEqual(t, len(gotTokens), len(wantPaths), tokensLenContext)
	for i := 0; i < len(wantPaths); i++ {
		requireEqual(t, gotPaths[i], wantPaths[i], "path index "+strconv.Itoa(i))
		requireEqual(t, gotTokens[i], wantToken, "token index "+strconv.Itoa(i))
	}
}

func requireAllTokens(t *testing.T, gotTokens []string, wantToken string) {
	t.Helper()
	for i := 0; i < len(gotTokens); i++ {
		requireEqual(t, gotTokens[i], wantToken, "token index "+strconv.Itoa(i))
	}
}

func requireStringContains(t *testing.T, got string, substr string, context string) {
	t.Helper()
	if !strings.Contains(got, substr) {
		t.Fatalf("%s = %q, want to contain %q", context, got, substr)
	}
}
