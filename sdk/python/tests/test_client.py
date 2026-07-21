import sys
import secrets
import unittest
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

from beacon_sdk import BeaconApiError, BeaconClient


class FakeResponse:
    def __init__(self, payload=None, *, content=None, text=None):
        self._payload = payload
        if content is None:
            if text is not None:
                content = str(text).encode("utf-8")
            elif payload is not None:
                import json as _json

                content = _json.dumps(payload).encode("utf-8")
            else:
                content = b""
        self.content = content
        self.text = text if text is not None else content.decode("utf-8", errors="replace")

    def json(self):
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []
        self.next_json = {"code": 1000, "msg": "success", "data": []}
        self.next_responses = []

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if self.next_responses:
            return self.next_responses.pop(0)
        return FakeResponse(self.next_json)

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if self.next_responses:
            return self.next_responses.pop(0)
        return FakeResponse(self.next_json)


class BeaconClientSdkTest(unittest.TestCase):
    def test_login_posts_credentials_and_returns_payload(self):
        session = FakeSession()
        session.next_json = {"code": 1000, "msg": "登录成功"}
        client = BeaconClient("http://localhost:9991", session=session)

        login_value = f"test-{secrets.token_hex(8)}"
        payload = client.login("admin", login_value, verify_code="1234")

        self.assertEqual(payload["code"], 1000)
        self.assertEqual(
            session.calls,
            [
                (
                    "post",
                    "http://localhost:9991/login",
                    {
                        "data": {
                            "username": "admin",
                            "password": login_value,
                            "verify_code": "1234",
                        },
                        "timeout": 10.0,
                    },
                )
            ],
        )

    def test_get_controls_returns_stream_info_data(self):
        session = FakeSession()
        session.next_json = {"code": 1000, "msg": "success", "data": [{"control_code": "c001"}]}
        client = BeaconClient("http://localhost:9991/", session=session)

        result = client.get_controls()

        self.assertEqual(result, [{"control_code": "c001"}])
        self.assertEqual(
            session.calls,
            [
                (
                    "get",
                    "http://localhost:9991/developer/getStreamInfo",
                    {"timeout": 10.0},
                )
            ],
        )

    def test_get_algorithms_returns_algorithm_info_data(self):
        session = FakeSession()
        session.next_json = {"code": 1000, "msg": "success", "data": [{"code": "algo001"}]}
        client = BeaconClient("http://localhost:9991", session=session)

        result = client.get_algorithms()

        self.assertEqual(result, [{"code": "algo001"}])
        self.assertEqual(
            session.calls,
            [
                (
                    "get",
                    "http://localhost:9991/developer/getAlgorithmInfo",
                    {"timeout": 10.0},
                )
            ],
        )

    def test_report_detection_posts_expected_json_payload(self):
        session = FakeSession()
        session.next_json = {"code": 1000, "msg": "success"}
        client = BeaconClient("http://localhost:9991", session=session)

        result = client.report_detection(
            control_code="ctrl001",
            detections=[{"class_name": "person", "confidence": 0.95}],
            frame_index=12,
            timestamp=1702700000,
            trigger_alarm=True,
            image_base64="ZmFrZS1pbWFnZQ==",
        )

        self.assertEqual(result["code"], 1000)
        self.assertEqual(
            session.calls,
            [
                (
                    "post",
                    "http://localhost:9991/developer/algorithmCallback",
                    {
                        "json": {
                            "control_code": "ctrl001",
                            "frame_index": 12,
                            "timestamp": 1702700000,
                            "detections": [{"class_name": "person", "confidence": 0.95}],
                            "trigger_alarm": True,
                            "image_base64": "ZmFrZS1pbWFnZQ==",
                        },
                        "timeout": 10.0,
                    },
                )
            ],
        )

    def test_non_success_response_raises_api_error(self):
        session = FakeSession()
        session.next_json = {"code": 0, "msg": "密码错误"}
        client = BeaconClient("http://localhost:9991", session=session)

        with self.assertRaises(BeaconApiError) as ctx:
            client.login("admin", "wrong")

        self.assertIn("密码错误", str(ctx.exception))

    def test_upload_alarm_posts_openapi_token_and_json_payload(self):
        session = FakeSession()
        session.next_json = {"code": 1000, "msg": "success", "data": {"id": 1}}
        client = BeaconClient(
            "http://localhost:9991",
            session=session,
            open_api_token="token-open-001",
        )

        result = client.upload_alarm(
            control_code="C001",
            desc="sdk upload",
            image_base64="ZmFrZS1pbWFnZQ==",
            alarm_type="crossing",
        )

        self.assertEqual(result["code"], 1000)
        self.assertEqual(
            session.calls,
            [
                (
                    "post",
                    "http://localhost:9991/open/alarm/upload",
                    {
                        "json": {
                            "control_code": "C001",
                            "desc": "sdk upload",
                            "image_base64": "ZmFrZS1pbWFnZQ==",
                            "alarm_type": "crossing",
                        },
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                )
            ],
        )

    def test_check_version_forwards_query_params_and_returns_data(self):
        session = FakeSession()
        session.next_json = {
            "code": 1000,
            "msg": "success",
            "data": {"currentVersion": "4.22.0", "hasUpdate": False},
        }
        client = BeaconClient("http://localhost:9991", session=session)

        result = client.check_version(infer_engine="openvino", infer_engine_version="2024.4")

        self.assertEqual(result, {"currentVersion": "4.22.0", "hasUpdate": False})
        self.assertEqual(
            session.calls,
            [
                (
                    "get",
                    "http://localhost:9991/open/checkVersion",
                    {
                        "params": {"infer_engine": "openvino", "infer_engine_version": "2024.4"},
                        "headers": {},
                        "timeout": 10.0,
                    },
                )
            ],
        )

    def test_core_openapi_queries_return_data_and_send_token(self):
        session = FakeSession()
        client = BeaconClient(
            "http://localhost:9991",
            session=session,
            open_api_token="token-open-001",
        )

        session.next_json = {"code": 1000, "msg": "success", "data": {"license_id": "LIC-1"}}
        self.assertEqual(client.get_license_info(), {"license_id": "LIC-1"})

        session.next_json = {"code": 1000, "msg": "success", "data": {"active_controls": 2}}
        self.assertEqual(client.get_license_usage(), {"active_controls": 2})

        session.next_json = {"code": 1000, "msg": "success", "data": [{"code": "ctrl-1"}]}
        self.assertEqual(client.get_control_data(code="ctrl-1"), [{"code": "ctrl-1"}])

        session.next_json = {"code": 1000, "msg": "success", "data": [{"code": "stream-1"}]}
        self.assertEqual(client.get_stream_data(code="stream-1"), [{"code": "stream-1"}])

        session.next_json = {"code": 1000, "msg": "success", "data": {"nodeCode": "node-1"}}
        self.assertEqual(client.get_platform_basic_info(), {"nodeCode": "node-1"})

        session.next_json = {"code": 1000, "msg": "success", "data": {"storageRootPath": "/data"}}
        self.assertEqual(client.get_platform_storage_info(), {"storageRootPath": "/data"})

        self.assertEqual(
            session.calls,
            [
                (
                    "get",
                    "http://localhost:9991/open/license/info",
                    {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
                (
                    "get",
                    "http://localhost:9991/open/license/usage",
                    {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
                (
                    "get",
                    "http://localhost:9991/open/getControlData",
                    {"params": {"code": "ctrl-1"}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
                (
                    "get",
                    "http://localhost:9991/open/getStreamData",
                    {"params": {"code": "stream-1"}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
                (
                    "get",
                    "http://localhost:9991/open/platform/basicInfo",
                    {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
                (
                    "get",
                    "http://localhost:9991/open/platform/storageInfo",
                    {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
            ],
        )

    def test_license_lease_methods_post_openapi_json_payloads(self):
        session = FakeSession()
        client = BeaconClient(
            "http://localhost:9991",
            session=session,
            open_api_token="token-open-001",
        )

        session.next_json = {
            "code": 1000,
            "msg": "success",
            "data": {"lease_id": "lease-1", "expires_at": "2026-03-09T10:00:00"},
        }
        self.assertEqual(
            client.acquire_license_lease(
                node_id="node-1",
                control_code="ctrl-1",
                algorithm_code="alg-1",
                stream_code="cam-001",
                ttl_seconds=180,
            ),
            {"lease_id": "lease-1", "expires_at": "2026-03-09T10:00:00"},
        )

        session.next_json = {
            "code": 1000,
            "msg": "success",
            "data": {"expires_at": "2026-03-09T10:30:00"},
        }
        self.assertEqual(
            client.renew_license_lease("lease-1", ttl_seconds=240),
            {"expires_at": "2026-03-09T10:30:00"},
        )

        session.next_json = {"code": 1000, "msg": "success"}
        self.assertEqual(client.release_license_lease("lease-1"), {"code": 1000, "msg": "success"})

        self.assertEqual(
            session.calls,
            [
                (
                    "post",
                    "http://localhost:9991/open/license/lease/acquire",
                    {
                        "json": {
                            "node_id": "node-1",
                            "control_code": "ctrl-1",
                            "algorithm_code": "alg-1",
                            "stream_code": "cam-001",
                            "ttl_seconds": 180,
                        },
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/license/lease/renew",
                    {
                        "json": {
                            "lease_id": "lease-1",
                            "ttl_seconds": 240,
                        },
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/license/lease/release",
                    {
                        "json": {
                            "lease_id": "lease-1",
                        },
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
            ],
        )

    def test_recording_and_task_plan_methods_post_openapi_json_payloads(self):
        session = FakeSession()
        client = BeaconClient(
            "http://localhost:9991",
            session=session,
            open_api_token="token-open-001",
        )

        session.next_json = {"code": 1000, "msg": "success", "data": {"code": "plan001"}}
        self.assertEqual(
            client.add_recording_plan(
                code="plan001",
                name="Plan 1",
                streamCode="stream001",
                startTime="00:00",
                endTime="23:59",
            ),
            {"code": "plan001"},
        )

        session.next_json = {"code": 1000, "msg": "success", "data": [{"code": "plan001"}]}
        self.assertEqual(client.list_recording_plans(), [{"code": "plan001"}])

        session.next_json = {"code": 1000, "msg": "success", "data": {"enabled": False}}
        self.assertEqual(client.edit_recording_plan(code="plan001", enabled=0), {"enabled": False})

        session.next_json = {"code": 1000, "msg": "success", "data": {"deleted": 1}}
        self.assertEqual(client.delete_recording_plan("plan001"), {"deleted": 1})

        session.next_json = {"code": 1000, "msg": "success", "data": {"code": "task001"}}
        self.assertEqual(
            client.add_task_plan(
                code="task001",
                name="Task 1",
                taskType="restart_software",
                scheduleType="daily",
                runTime="02:00",
            ),
            {"code": "task001"},
        )

        session.next_json = {"code": 1000, "msg": "success", "data": [{"code": "task001"}]}
        self.assertEqual(client.list_task_plans(), [{"code": "task001"}])

        session.next_json = {"code": 1000, "msg": "success", "data": {"enabled": False}}
        self.assertEqual(client.edit_task_plan(code="task001", enabled=0), {"enabled": False})

        session.next_json = {"code": 1000, "msg": "success", "data": {"deleted": 1}}
        self.assertEqual(client.delete_task_plan("task001"), {"deleted": 1})

        self.assertEqual(
            session.calls,
            [
                (
                    "post",
                    "http://localhost:9991/open/recordingPlan/add",
                    {
                        "json": {"code": "plan001", "name": "Plan 1", "streamCode": "stream001", "startTime": "00:00", "endTime": "23:59"},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/recordingPlan/list",
                    {
                        "json": {},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/recordingPlan/edit",
                    {
                        "json": {"code": "plan001", "enabled": 0},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/recordingPlan/delete",
                    {
                        "json": {"code": "plan001"},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/taskPlan/add",
                    {
                        "json": {"code": "task001", "name": "Task 1", "taskType": "restart_software", "scheduleType": "daily", "runTime": "02:00"},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/taskPlan/list",
                    {
                        "json": {},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/taskPlan/edit",
                    {
                        "json": {"code": "task001", "enabled": 0},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/taskPlan/delete",
                    {
                        "json": {"code": "task001"},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
            ],
        )

    def test_recording_runtime_methods_use_openapi_json_payloads(self):
        session = FakeSession()
        client = BeaconClient(
            "http://localhost:9991",
            session=session,
            open_api_token="token-open-001",
        )

        session.next_json = {"code": 1000, "msg": "success", "data": [{"filename": "demo.mp4"}], "total": 1}
        self.assertEqual(client.list_recording_files(streamCode="stream001"), [{"filename": "demo.mp4"}])

        session.next_json = {"code": 1000, "msg": "success", "data": {"play_url": "http://demo/open/fileService/recordings/a.mp4"}}
        self.assertEqual(
            client.get_recording_file_play_url(relPath="recordings/stream001/demo.mp4"),
            {"play_url": "http://demo/open/fileService/recordings/a.mp4"},
        )

        session.next_json = {"code": 1000, "msg": "success", "data": {"record_id": "rec-1", "save_path": "recordings/stream001/demo.mp4"}}
        self.assertEqual(
            client.start_recording(streamCode="stream001", streamUrl="rtsp://127.0.0.1/demo", duration=10, format="mp4", recordAudio=1),
            {"record_id": "rec-1", "save_path": "recordings/stream001/demo.mp4"},
        )

        session.next_json = {"code": 1000, "msg": "success", "data": {"save_path": "recordings/stream001/demo.mp4", "duration": 1.2}}
        self.assertEqual(
            client.stop_recording(streamCode="stream001"),
            {"save_path": "recordings/stream001/demo.mp4", "duration": 1.2},
        )

        session.next_json = {"code": 1000, "msg": "success", "data": {"image_path": "snapshots/stream001/demo.jpg"}}
        self.assertEqual(
            client.capture_snapshot(streamCode="stream001", streamUrl="rtsp://127.0.0.1/demo"),
            {"image_path": "snapshots/stream001/demo.jpg"},
        )

        self.assertEqual(
            session.calls,
            [
                (
                    "post",
                    "http://localhost:9991/open/recording/file/list",
                    {
                        "json": {"streamCode": "stream001"},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/recording/file/playUrl",
                    {
                        "json": {"relPath": "recordings/stream001/demo.mp4"},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/recording/startRecording",
                    {
                        "json": {"streamCode": "stream001", "streamUrl": "rtsp://127.0.0.1/demo", "duration": 10, "format": "mp4", "recordAudio": 1},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/recording/stopRecording",
                    {
                        "json": {"streamCode": "stream001"},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/recording/captureSnapshot",
                    {
                        "json": {"streamCode": "stream001", "streamUrl": "rtsp://127.0.0.1/demo"},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
            ],
        )

    def test_face_methods_use_openapi_json_payloads(self):
        session = FakeSession()
        client = BeaconClient(
            "http://localhost:9991",
            session=session,
            open_api_token="token-open-001",
        )

        session.next_json = {"code": 1000, "msg": "success", "data": {"count": 1, "items": [{"id": "alice"}]}}
        self.assertEqual(client.list_faces(), {"count": 1, "items": [{"id": "alice"}]})

        session.next_json = {"code": 1000, "msg": "success", "data": {"code": 1000, "msg": "success"}}
        self.assertEqual(client.add_face(id="alice", name="Alice", embedding=[1, 0]), {"code": 1000, "msg": "success"})

        session.next_json = {"code": 1000, "msg": "success", "data": {"found": False}}
        self.assertEqual(client.search_face(embedding=[1, 0], minScore=0.8), {"found": False})

        session.next_json = {"code": 1000, "msg": "success", "data": {"code": 1000, "msg": "success"}}
        self.assertEqual(client.enable_face_search(), {"code": 1000, "msg": "success"})

        session.next_json = {"code": 1000, "msg": "success", "data": {"code": 1000, "msg": "success"}}
        self.assertEqual(client.disable_face_search(), {"code": 1000, "msg": "success"})

        session.next_json = {"code": 1000, "msg": "success", "data": {"code": 1000, "msg": "success"}}
        self.assertEqual(client.delete_face("alice"), {"code": 1000, "msg": "success"})

        self.assertEqual(
            session.calls,
            [
                (
                    "post",
                    "http://localhost:9991/open/face/list",
                    {"json": {}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
                (
                    "post",
                    "http://localhost:9991/open/face/add",
                    {"json": {"id": "alice", "name": "Alice", "embedding": [1, 0]}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
                (
                    "post",
                    "http://localhost:9991/open/face/search",
                    {"json": {"embedding": [1, 0], "minScore": 0.8}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
                (
                    "post",
                    "http://localhost:9991/open/face/enable",
                    {"json": {}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
                (
                    "post",
                    "http://localhost:9991/open/face/disable",
                    {"json": {}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
                (
                    "post",
                    "http://localhost:9991/open/face/delete",
                    {"json": {"id": "alice"}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0},
                ),
            ],
        )

    def test_cloud_and_ops_methods_use_expected_auth_and_payloads(self):
        session = FakeSession()
        client = BeaconClient(
            "http://localhost:9991",
            session=session,
            open_api_token="token-open-001",
            cloud_edge_token="edge-token-001",
        )

        session.next_json = {"code": 1000, "msg": "success", "data": {"bucket": "beacon-alarms"}}
        self.assertEqual(
            client.cloud_presign_image(event_id="evt-1", content_type="image/jpeg", ext=".jpg"),
            {"bucket": "beacon-alarms"},
        )

        session.next_json = {"code": 1000, "msg": "success"}
        self.assertEqual(
            client.cloud_ingest_alarm_created(
                schema="beacon.event.v1",
                event_id="evt-1",
                event_type="alarm.created",
                event_source="openAdd",
            ),
            {"code": 1000, "msg": "success"},
        )

        session.next_json = {"code": 1000, "msg": "success", "data": {"targets": {"logs": {"deleted_files": 1}}}}
        self.assertEqual(
            client.ops_cleanup(targets=["logs"], dry_run=True),
            {"targets": {"logs": {"deleted_files": 1}}},
        )

        session.next_json = {"code": 1000, "msg": "success", "data": {"updated": 1}}
        self.assertEqual(
            client.ops_outbox_replay(event_id="evt-1"),
            {"updated": 1},
        )

        session.next_json = {"code": 1000, "msg": "success", "data": {"level": "DEBUG", "loggers": ["app.middleware"]}}
        self.assertEqual(
            client.ops_set_logging_level(level="DEBUG", logger="app.middleware"),
            {"level": "DEBUG", "loggers": ["app.middleware"]},
        )

        self.assertEqual(
            session.calls,
            [
                (
                    "post",
                    "http://localhost:9991/open/cloud/v1/presign/image",
                    {
                        "json": {"event_id": "evt-1", "content_type": "image/jpeg", "ext": ".jpg"},
                        "headers": {"Authorization": "Bearer edge-token-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/cloud/v1/events/alarm-created",
                    {
                        "json": {
                            "schema": "beacon.event.v1",
                            "event_id": "evt-1",
                            "event_type": "alarm.created",
                            "event_source": "openAdd",
                        },
                        "headers": {"Authorization": "Bearer edge-token-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/ops/cleanup",
                    {
                        "json": {"targets": ["logs"], "dry_run": True},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/ops/outbox/replay",
                    {
                        "json": {"event_id": "evt-1"},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
                (
                    "post",
                    "http://localhost:9991/open/ops/logging/level",
                    {
                        "json": {"level": "DEBUG", "logger": "app.middleware"},
                        "headers": {"X-Beacon-Token": "token-open-001"},
                        "timeout": 10.0,
                    },
                ),
            ],
        )

    def test_low_level_openapi_methods_use_expected_payloads(self):
        session = FakeSession()
        client = BeaconClient(
            "http://localhost:9991",
            session=session,
            open_api_token="token-open-001",
        )
        session.next_responses = [
            FakeResponse({"code": 1000, "msg": "success", "data": {"engine": "api", "detects": []}}),
            FakeResponse({"code": 1000, "msg": "success", "data": {"engine": "api", "text": "alarm detected", "language": "en-US", "segments": []}}),
            FakeResponse({"code": 1000, "msg": "success", "info": {"code": "node-1"}}),
            FakeResponse({"code": 1000, "msg": "success", "data": [{"code": "stream-1"}]}),
            FakeResponse({"code": 1000, "msg": "success", "data": [{"code": "algo-1"}]}),
            FakeResponse({"code": 1000, "msg": "success", "data": [{"process_index": 0}], "info": {"processNum": 1}}),
            FakeResponse({"code": 1000, "msg": "success", "info": {"processNum": 1, "controlCount": 2}}),
            FakeResponse({"code": 1000, "msg": "restarting"}),
            FakeResponse({"code": 1000, "msg": "restarting"}),
            FakeResponse(None, content=b"hello"),
        ]

        self.assertEqual(client.image_detect(code="alg-api", image_base64="Zm9v"), {"engine": "api", "detects": []})
        self.assertEqual(
            client.audio_detect(code="asr-api", audio_base64="YmFy", language="en-US"),
            {"engine": "api", "text": "alarm detected", "language": "en-US", "segments": []},
        )
        self.assertEqual(client.discover(), {"code": "node-1"})
        self.assertEqual(client.get_all_stream_data(), [{"code": "stream-1"}])
        self.assertEqual(client.get_all_algorithm_flow_data(), [{"code": "algo-1"}])
        self.assertEqual(client.get_all_core_process_data(), {"data": [{"process_index": 0}], "info": {"processNum": 1}})
        self.assertEqual(client.get_all_core_process_data2(), {"processNum": 1, "controlCount": 2})
        self.assertEqual(client.restart_software(), {"code": 1000, "msg": "restarting"})
        self.assertEqual(client.restart_system(), {"code": 1000, "msg": "restarting"})
        self.assertEqual(client.download_file("hello.txt"), b"hello")

        self.assertEqual(
            session.calls,
            [
                ("post", "http://localhost:9991/open/algorithm/imageDetect", {"json": {"code": "alg-api", "image_base64": "Zm9v"}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("post", "http://localhost:9991/open/algorithm/audioDetect", {"json": {"code": "asr-api", "audio_base64": "YmFy", "language": "en-US"}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/discover", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/getAllStreamData", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/getAllAlgroithmFlowData", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/getAllCoreProcessData", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/getAllCoreProcessData2", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("post", "http://localhost:9991/open/platform/restartSoftware", {"json": {}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("post", "http://localhost:9991/open/platform/restartSystem", {"json": {}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/fileService/hello.txt", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
            ],
        )

    def test_ops_export_and_upgrade_methods_use_expected_payloads(self):
        session = FakeSession()
        client = BeaconClient(
            "http://localhost:9991",
            session=session,
            open_api_token="token-open-001",
        )
        session.next_responses = [
            FakeResponse({"code": 1000, "msg": "success", "data": {"status": "ok"}}),
            FakeResponse({"code": 1000, "msg": "success", "data": {"status": "ok"}}),
            FakeResponse(None, text="metric 1\n"),
            FakeResponse(None, content=b"event_type\nlicense.lease.acquire\n"),
            FakeResponse(None, content=b"PK\x03\x04demo"),
            FakeResponse({"code": 1000, "msg": "success", "data": [{"package_id": "pkg-a"}]}),
            FakeResponse({"code": 1000, "msg": "success", "data": {"ok": True, "package_id": "pkg-a"}}),
            FakeResponse({"code": 1000, "msg": "success", "data": {"applied_package_id": "pkg-a"}}),
            FakeResponse({"code": 1000, "msg": "success", "data": {"applied_package_id": "pkg-prev"}}),
            FakeResponse({"code": 1000, "msg": "success", "data": {"package_id": "pkg-up"}}),
        ]

        self.assertEqual(client.ops_health(), {"status": "ok"})
        self.assertEqual(client.ops_ready(), {"status": "ok"})
        self.assertEqual(client.ops_metrics(), "metric 1\n")
        self.assertEqual(client.ops_audit_export(format="csv"), b"event_type\nlicense.lease.acquire\n")
        self.assertEqual(client.ops_diagnostics_export(), b"PK\x03\x04demo")
        self.assertEqual(client.ops_upgrade_list(), [{"package_id": "pkg-a"}])
        self.assertEqual(client.ops_upgrade_validate("pkg-a"), {"ok": True, "package_id": "pkg-a"})
        self.assertEqual(client.ops_upgrade_apply(package_id="pkg-a"), {"applied_package_id": "pkg-a"})
        self.assertEqual(client.ops_upgrade_rollback(), {"applied_package_id": "pkg-prev"})
        self.assertEqual(
            client.ops_upgrade_upload("upgrade.zip", b"ZIPDATA"),
            {"package_id": "pkg-up"},
        )

        self.assertEqual(
            session.calls,
            [
                ("get", "http://localhost:9991/open/ops/health", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/ops/ready", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/ops/metrics", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/ops/audit/export", {"params": {"format": "csv"}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/ops/diagnostics/export", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/ops/upgrade/list", {"params": None, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("get", "http://localhost:9991/open/ops/upgrade/validate", {"params": {"package_id": "pkg-a"}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("post", "http://localhost:9991/open/ops/upgrade/apply", {"json": {"package_id": "pkg-a"}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("post", "http://localhost:9991/open/ops/upgrade/rollback", {"json": {}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
                ("post", "http://localhost:9991/open/ops/upgrade/upload", {"files": {"file": ("upgrade.zip", b"ZIPDATA", "application/zip")}, "headers": {"X-Beacon-Token": "token-open-001"}, "timeout": 10.0}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
