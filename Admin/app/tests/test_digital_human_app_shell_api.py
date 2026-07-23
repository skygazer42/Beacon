import io
import os
import json
import tempfile
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from app.models import (
    DigitalHumanAiDiagnosisConfig,
    DigitalHumanAlert,
    DigitalHumanAlertRoute,
    DigitalHumanAlertRouteConfig,
    DigitalHumanDevice,
    DigitalHumanHumanLog,
)
from app.services import digital_human as dh_service
from app.views import DigitalHumanApiView, DigitalHumanView, ViewsBase


class DigitalHumanAppShellApiTests(TestCase):
    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()
        self.admin_user = User.objects.create_user(
            username="beacon-admin",
            password="test-password",
            is_staff=True,
        )
        self.regular_user = User.objects.create_user(
            username="beacon-user",
            password="test-password",
            is_staff=False,
        )

    def _create_ai_config(self):
        return DigitalHumanAiDiagnosisConfig.objects.create(
            enabled=True,
            base_url="https://api.example.com/v1",
            api_key="sk-saved-secret",
            model="gpt-4.1-mini",
            temperature=0.2,
            alert_system_prompt="alert",
            log_system_prompt="log",
            connect_timeout_ms=10000,
            read_timeout_ms=60000,
        )

    def _attach_session(self, request, *, logged_in=True, user=None):
        request.session = {}
        if logged_in:
            current_user = user or self.admin_user
            request.session["user"] = {"id": current_user.id, "username": current_user.username}
        return request

    def _login_client(self, user=None):
        current_user = user or self.admin_user
        session = self.client.session
        session["user"] = {"id": current_user.id, "username": current_user.username}
        session.save()

    def test_dashboard_endpoint_requires_beacon_login(self):
        request = self._attach_session(
            self.rf.get("/api/app-shell/digital-human/dashboard"),
            logged_in=False,
        )

        response = DigitalHumanApiView.api_dashboard(request)
        body = json.loads(response.content)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(body["code"], 401)
        self.assertEqual(body["msg"], "unauthorized")

    def test_shared_post_parser_rejects_empty_or_non_object_json(self):
        requests = [
            self.rf.get("/api/app-shell/digital-human/device/action/update-window"),
            self.rf.post("/probe", data={}),
            self.rf.post("/probe", data="{", content_type="application/json"),
            self.rf.post("/probe", data="[]", content_type="application/json"),
        ]
        for request in requests:
            self.assertEqual(ViewsBase.f_parsePostParams(request), {})

    def test_dashboard_endpoint_forbids_non_admin_beacon_user(self):
        request = self._attach_session(
            self.rf.get("/api/app-shell/digital-human/dashboard"),
            user=self.regular_user,
        )

        response = DigitalHumanApiView.api_dashboard(request)
        body = json.loads(response.content)

        self.assertEqual(body["code"], 403)
        self.assertEqual(body["msg"], "权限不足，仅管理员可访问")

    def test_alert_detail_returns_validation_error_for_non_numeric_id(self):
        request = self._attach_session(
            self.rf.get("/api/app-shell/digital-human/alert-detail?id=not-a-number"),
        )

        response = DigitalHumanApiView.api_alert_detail(request)
        body = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["code"], 0)
        self.assertIn("告警 ID 不合法", body["msg"])

    def test_dashboard_page_renders_shell_for_admin(self):
        request = self._attach_session(self.rf.get("/digital-human/dashboard"))

        response = DigitalHumanView.dashboard(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"beacon-app-root", response.content)
        self.assertIn(b'"isStaff": true', response.content)
        self.assertIn(f'"projectVersion": "{settings.PROJECT_VERSION}"'.encode(), response.content)
        self.assertIn("数字人监管".encode(), response.content)

    @mock.patch("app.services.digital_human.requests.post")
    def test_dashboard_endpoint_reads_local_digital_human_models(self, mocked_post):
        mocked_response = mock.Mock(status_code=200, text='{"errcode":0,"errmsg":"ok"}')
        mocked_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mocked_post.return_value = mocked_response
        DigitalHumanAlertRouteConfig.objects.create(enabled=True)
        DigitalHumanAlertRoute.objects.create(
            region="北京前厅",
            webhook="https://hooks.example.com/front",
            secret="secret-front",
            owner_name="李楠",
            owner_phone="13800000001",
            active=True,
            is_default_route=False,
        )
        now = datetime.now()
        DigitalHumanDevice.objects.create(
            device_code="KD-001",
            agent_device_id="AGENT-001",
            machine_code="a" * 64,
            machine_mac="A4-2F-91-10-BC-01",
            tenant_name="front-desk",
            registered_by_jwt_account_uuid="jwt-account-001",
            registered_by_jwt_tenant_name="front-desk",
            authorization_enabled=True,
            authorization_status="AUTHORIZED",
            display_name="数字员工-前台接待",
            region="北京前厅",
            computer_name="DESKTOP-001",
            processor="Intel i7",
            cpu_usage=72,
            gpu_usage=40,
            memory_usage=64,
            disk_usage=58,
            net_latency_ms=18,
            bandwidth_text="12.6 Mbps",
            peripheral_cam=True,
            peripheral_mic=True,
            service_stream=False,
            service_llm=True,
            active_window_title="欢迎播报",
            active_window_process="BeaconAvatar.exe",
            last_report_time=now,
            last_online_time=now,
        )

        request = self._attach_session(self.rf.get("/api/app-shell/digital-human/dashboard"))
        response = DigitalHumanApiView.api_dashboard(request)
        body = json.loads(response.content)

        self.assertEqual(body["code"], 1000, msg=body)
        self.assertEqual(body["data"]["kpis"][0]["title"], "终端总数")
        self.assertEqual(body["data"]["kpis"][0]["value"], 1)
        self.assertEqual(body["data"]["routingHealth"]["activeRoutes"], 1)
        self.assertEqual(body["data"]["alertFeed"][0]["title"], "推流服务异常")
        self.assertIn("数字员工-前台接待", body["data"]["topLoads"][0]["name"])

    @mock.patch("app.services.digital_human.requests.get")
    def test_ai_diagnosis_test_reuses_saved_api_key_when_payload_key_is_blank(self, mocked_get):
        mocked_response = mock.Mock(status_code=200, text="ok")
        mocked_response.json.return_value = {"data": [{"id": "gpt-4.1-mini"}]}
        mocked_get.return_value = mocked_response
        DigitalHumanAiDiagnosisConfig.objects.create(
            enabled=True,
            base_url="https://api.example.com/v1",
            api_key="sk-saved-secret",
            model="gpt-4.1-mini",
            temperature=0.2,
            alert_system_prompt="alert",
            log_system_prompt="log",
            connect_timeout_ms=10000,
            read_timeout_ms=60000,
        )
        request = self._attach_session(
            self.rf.post(
                "/api/app-shell/digital-human/system-settings/ai-diagnosis/action/test",
                data=json.dumps(
                    {
                        "baseUrl": "https://api.example.com/v1",
                        "apiKey": "",
                        "model": "gpt-4.1-mini",
                        "connectTimeoutMs": 10000,
                        "readTimeoutMs": 60000,
                    }
                ),
                content_type="application/json",
            )
        )

        response = DigitalHumanApiView.api_system_settings_ai_diagnosis_test(request)
        body = json.loads(response.content)

        self.assertEqual(body["code"], 1000, msg=body)
        self.assertTrue(body["data"]["success"])
        mocked_get.assert_called_once()
        self.assertEqual(
            mocked_get.call_args.kwargs["headers"]["Authorization"],
            "Bearer sk-saved-secret",
        )

    def test_device_authorization_update_persists_local_fields(self):
        future_start = datetime.now() - timedelta(days=1)
        future_end = datetime.now() + timedelta(days=30)
        device = DigitalHumanDevice.objects.create(
            device_code="KD-009",
            agent_device_id="AGENT-009",
            machine_code="b" * 64,
            machine_mac="A4-2F-91-10-BC-09",
            tenant_name="front-desk",
            authorization_enabled=False,
            authorization_status="PENDING",
            display_name="数字员工-前台接待",
            region="北京前厅",
            processor="Intel i7",
        )

        request = self._attach_session(
            self.rf.post(
                "/api/app-shell/digital-human/system-settings/device-authorizations/action/update",
                data=json.dumps(
                    {
                        "id": device.id,
                        "enabled": True,
                        "displayName": "数字员工-前台接待",
                        "region": "北京前厅",
                        "rustdeskId": "100001",
                        "rustdeskPassword": "front@123",
                        "validFrom": future_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "validUntil": future_end.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                ),
                content_type="application/json",
            )
        )

        response = DigitalHumanApiView.api_system_settings_device_authorization_update(request)
        body = json.loads(response.content)
        device.refresh_from_db()

        self.assertEqual(body["code"], 1000, msg=body)
        self.assertTrue(device.authorization_enabled)
        self.assertEqual(device.rustdesk_id, "100001")
        self.assertEqual(body["data"]["authorizationStatus"], "AUTHORIZED")
        self.assertEqual(body["data"]["rustdeskPassword"], "front@123")

    def test_alert_routing_enabled_handles_form_false_string(self):
        config = DigitalHumanAlertRouteConfig.objects.create(enabled=True)
        request = self._attach_session(
            self.rf.post(
                "/api/app-shell/digital-human/alert-routing/action/enabled",
                data={"enabled": "false"},
            )
        )

        response = DigitalHumanApiView.api_alert_routing_enabled(request)
        body = json.loads(response.content)
        config.refresh_from_db()

        self.assertEqual(body["code"], 1000, msg=body)
        self.assertFalse(config.enabled)
        self.assertFalse(body["data"]["enabled"])

    @mock.patch("app.services.digital_human.requests.post")
    def test_monitor_log_reanalyze_updates_local_record(self, mocked_post):
        mocked_response = mock.Mock(status_code=200, text="ok")
        mocked_response.json.return_value = {
            "choices": [{"message": {"content": "请优先检查推流服务、网络链路和最近的超时异常。"}}]
        }
        mocked_post.return_value = mocked_response
        self._create_ai_config()
        now = datetime.now()
        device = DigitalHumanDevice.objects.create(
            device_code="KD-011",
            agent_device_id="AGENT-011",
            machine_code="c" * 64,
            machine_mac="A4-2F-91-10-BC-11",
            tenant_name="front-desk",
            authorization_enabled=True,
            authorization_status="AUTHORIZED",
            display_name="数字员工-前台接待",
            region="北京前厅",
            last_report_time=now,
            last_online_time=now,
        )
        log_row = DigitalHumanHumanLog.objects.create(
            device=device,
            time=now - timedelta(minutes=1),
            level="ERROR",
            module="stream",
            message="push timeout",
            diagnosis_status="skipped",
            diagnosis_text="",
            diagnosis_error="",
        )

        request = self._attach_session(
            self.rf.post(
                "/api/app-shell/digital-human/monitor-logs/action/reanalyze",
                data=json.dumps({"id": log_row.id}),
                content_type="application/json",
            )
        )

        response = DigitalHumanApiView.api_monitor_log_reanalyze(request)
        body = json.loads(response.content)
        log_row.refresh_from_db()

        self.assertEqual(body["code"], 1000, msg=body)
        self.assertEqual(log_row.diagnosis_status, "success")
        self.assertEqual(log_row.diagnosis_text, "请优先检查推流服务、网络链路和最近的超时异常。")

    @mock.patch("app.services.digital_human.requests.post")
    def test_monitor_log_reanalyze_persists_ai_failure(self, mocked_post):
        mocked_response = mock.Mock(status_code=500, text="upstream error")
        mocked_post.return_value = mocked_response
        self._create_ai_config()
        now = datetime.now()
        device = DigitalHumanDevice.objects.create(
            device_code="KD-012",
            agent_device_id="AGENT-012",
            machine_code="d" * 64,
            machine_mac="A4-2F-91-10-BC-12",
            tenant_name="front-desk",
            authorization_enabled=True,
            authorization_status="AUTHORIZED",
            display_name="数字员工-前台接待",
            region="北京前厅",
            last_report_time=now,
            last_online_time=now,
        )
        log_row = DigitalHumanHumanLog.objects.create(
            device=device,
            time=now - timedelta(minutes=1),
            level="ERROR",
            module="stream",
            message="push timeout",
            diagnosis_status="skipped",
            diagnosis_text="",
            diagnosis_error="",
        )

        request = self._attach_session(
            self.rf.post(
                "/api/app-shell/digital-human/monitor-logs/action/reanalyze",
                data=json.dumps({"id": log_row.id}),
                content_type="application/json",
            )
        )

        response = DigitalHumanApiView.api_monitor_log_reanalyze(request)
        body = json.loads(response.content)
        log_row.refresh_from_db()

        self.assertEqual(body["code"], 1000, msg=body)
        self.assertEqual(log_row.diagnosis_status, "failed")
        self.assertIn("http 500", log_row.diagnosis_error)

    @mock.patch("app.services.digital_human.requests.post")
    def test_alert_refresh_persists_ai_diagnosis_and_dingtalk_success(self, mocked_post):
        self._create_ai_config()
        DigitalHumanAlertRouteConfig.objects.create(enabled=True)
        DigitalHumanAlertRoute.objects.create(
            region="北京前厅",
            webhook="https://oapi.dingtalk.com/robot/send?access_token=test-token",
            secret="secret-front",
            owner_name="李楠",
            owner_phone="13800000001",
            active=True,
            is_default_route=False,
        )
        now = datetime.now()
        device = DigitalHumanDevice.objects.create(
            device_code="KD-013",
            agent_device_id="AGENT-013",
            machine_code="e" * 64,
            machine_mac="A4-2F-91-10-BC-13",
            tenant_name="front-desk",
            authorization_enabled=True,
            authorization_status="AUTHORIZED",
            display_name="数字员工-前台接待",
            region="北京前厅",
            peripheral_cam=True,
            peripheral_mic=True,
            service_stream=False,
            service_llm=True,
            cpu_usage=20,
            gpu_usage=10,
            memory_usage=30,
            disk_usage=40,
            net_latency_ms=12,
            last_report_time=now,
            last_online_time=now,
        )

        def _fake_post(url, *args, **kwargs):
            response = mock.Mock()
            if "chat/completions" in url:
                response.status_code = 200
                response.text = "ok"
                response.json.return_value = {
                    "choices": [{"message": {"content": "建议优先检查推流服务进程和网络链路。"}}]
                }
                return response
            response.status_code = 200
            response.text = '{"errcode":0,"errmsg":"ok"}'
            response.json.return_value = {"errcode": 0, "errmsg": "ok"}
            return response

        mocked_post.side_effect = _fake_post

        request = self._attach_session(self.rf.get("/api/app-shell/digital-human/alerts"))
        response = DigitalHumanApiView.api_alerts(request)
        body = json.loads(response.content)
        alert = DigitalHumanAlert.objects.get(device=device, alert_type="stream_service_down")

        self.assertEqual(body["code"], 1000, msg=body)
        self.assertEqual(mocked_post.call_count, 2)
        self.assertEqual(alert.diagnosis_status, "success")
        self.assertEqual(alert.diagnosis_text, "建议优先检查推流服务进程和网络链路。")
        self.assertEqual(alert.dingtalk_push_status, "success")
        self.assertEqual(alert.dingtalk_error, "")
        self.assertIn("推流服务异常", alert.dingtalk_message_preview)
        self.assertIn("钉钉推送成功", alert.timeline_json)
        dingtalk_url = mocked_post.call_args_list[-1].args[0]
        self.assertIn("timestamp=", dingtalk_url)
        self.assertIn("sign=", dingtalk_url)

    @mock.patch("app.services.digital_human.requests.post")
    def test_alert_refresh_retries_failed_ai_diagnosis(self, mocked_post):
        mocked_response = mock.Mock(status_code=200, text="ok")
        mocked_response.json.return_value = {
            "choices": [{"message": {"content": "建议优先检查推流服务进程和网络链路。"}}]
        }
        mocked_post.return_value = mocked_response
        self._create_ai_config()
        DigitalHumanAlertRouteConfig.objects.create(enabled=True)
        DigitalHumanAlertRoute.objects.create(
            region="北京前厅",
            webhook="https://oapi.dingtalk.com/robot/send?access_token=test-token",
            secret="secret-front",
            owner_name="李楠",
            owner_phone="13800000001",
            active=True,
            is_default_route=False,
        )
        now = datetime.now()
        device = DigitalHumanDevice.objects.create(
            device_code="KD-013A",
            agent_device_id="AGENT-013A",
            machine_code="ea" * 32,
            machine_mac="A4-2F-91-10-BC-31",
            tenant_name="front-desk",
            authorization_enabled=True,
            authorization_status="AUTHORIZED",
            display_name="数字员工-前台接待",
            region="北京前厅",
            peripheral_cam=True,
            peripheral_mic=True,
            service_stream=False,
            service_llm=True,
            cpu_usage=20,
            gpu_usage=10,
            memory_usage=30,
            disk_usage=40,
            net_latency_ms=12,
            last_report_time=now,
            last_online_time=now,
        )
        alert = DigitalHumanAlert.objects.create(
            device=device,
            alert_type="stream_service_down",
            title="推流服务异常",
            description="推流服务状态异常，欢迎词播报或直播链路可能中断。",
            alert_module_text="推流服务",
            level="critical",
            status="pending",
            diagnosis_status="failed",
            diagnosis_text="",
            diagnosis_error="http 500 upstream error",
            first_occurred_at=now - timedelta(minutes=5),
            last_occurred_at=now - timedelta(minutes=1),
            dingtalk_push_status="success",
            dingtalk_route_region="北京前厅",
            dingtalk_owner_name="李楠",
            dingtalk_owner_phone="13800000001",
            dingtalk_message_preview="existing preview",
            dingtalk_error="",
        )

        request = self._attach_session(self.rf.get("/api/app-shell/digital-human/alerts"))
        response = DigitalHumanApiView.api_alerts(request)
        body = json.loads(response.content)
        alert.refresh_from_db()

        self.assertEqual(body["code"], 1000, msg=body)
        self.assertEqual(mocked_post.call_count, 1)
        self.assertEqual(alert.diagnosis_status, "success")
        self.assertEqual(alert.diagnosis_text, "建议优先检查推流服务进程和网络链路。")
        self.assertEqual(alert.dingtalk_push_status, "success")

    @mock.patch("app.services.digital_human.requests.post")
    def test_alert_refresh_persists_dingtalk_failure(self, mocked_post):
        mocked_response = mock.Mock(status_code=500, text="server error")
        mocked_response.json.return_value = {"errcode": 310000, "errmsg": "server error"}
        mocked_post.return_value = mocked_response
        DigitalHumanAlertRouteConfig.objects.create(enabled=True)
        DigitalHumanAlertRoute.objects.create(
            region="北京前厅",
            webhook="https://oapi.dingtalk.com/robot/send?access_token=test-token",
            secret="secret-front",
            owner_name="李楠",
            owner_phone="13800000001",
            active=True,
            is_default_route=False,
        )
        now = datetime.now()
        device = DigitalHumanDevice.objects.create(
            device_code="KD-014",
            agent_device_id="AGENT-014",
            machine_code="f" * 64,
            machine_mac="A4-2F-91-10-BC-14",
            tenant_name="front-desk",
            authorization_enabled=True,
            authorization_status="AUTHORIZED",
            display_name="数字员工-前台接待",
            region="北京前厅",
            peripheral_cam=True,
            peripheral_mic=True,
            service_stream=False,
            service_llm=True,
            cpu_usage=20,
            gpu_usage=10,
            memory_usage=30,
            disk_usage=40,
            net_latency_ms=12,
            last_report_time=now,
            last_online_time=now,
        )

        request = self._attach_session(self.rf.get("/api/app-shell/digital-human/alerts"))
        response = DigitalHumanApiView.api_alerts(request)
        body = json.loads(response.content)
        alert = DigitalHumanAlert.objects.get(device=device, alert_type="stream_service_down")

        self.assertEqual(body["code"], 1000, msg=body)
        self.assertEqual(mocked_post.call_count, 1)
        self.assertEqual(alert.dingtalk_push_status, "failed")
        self.assertIn("http 500", alert.dingtalk_error)
        self.assertIn("钉钉推送失败", alert.timeline_json)

    @mock.patch("app.services.digital_human.requests.post")
    def test_ops_ai_insight_uses_ai_completion_api(self, mocked_post):
        mocked_response = mock.Mock(status_code=200, text="ok")
        mocked_response.json.return_value = {
            "choices": [{"message": {"content": "请优先关注高频告警设备并复核推流链路稳定性。"}}]
        }
        mocked_post.return_value = mocked_response
        self._create_ai_config()

        request = self._attach_session(self.rf.get("/api/app-shell/digital-human/ops-report/ai-insight?range=7days"))
        response = DigitalHumanApiView.api_ops_ai_insight(request)
        body = json.loads(response.content)

        self.assertEqual(body["code"], 1000, msg=body)
        self.assertEqual(body["data"]["status"], "success")
        self.assertEqual(body["data"]["text"], "请优先关注高频告警设备并复核推流链路稳定性。")
        self.assertEqual(mocked_post.call_args.kwargs["json"]["model"], "gpt-4.1-mini")

    def test_device_screenshot_route_serves_local_file(self):
        image_bytes = b"local-screenshot-bytes"
        rel_path = "digital-human/screenshots/2026/05/13/device_15/frame.png"
        with tempfile.TemporaryDirectory() as tempdir:
            abs_path = os.path.join(tempdir, *rel_path.split("/"))
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "wb") as handle:
                handle.write(image_bytes)
            device = DigitalHumanDevice.objects.create(
                device_code="KD-015",
                agent_device_id="AGENT-015",
                machine_code="g" * 64,
                machine_mac="A4-2F-91-10-BC-15",
                tenant_name="front-desk",
            )
            device.screenshot_storage_path = rel_path
            device.screenshot_storage_url = f"/digital-human/device-screenshot?id={device.id}"
            device.screenshot_content_type = "image/png"
            device.screenshot_byte_size = len(image_bytes)
            device.save(
                update_fields=[
                    "screenshot_storage_path",
                    "screenshot_storage_url",
                    "screenshot_content_type",
                    "screenshot_byte_size",
                ]
            )

            with mock.patch.object(dh_service.g_config, "uploadDir", tempdir, create=True):
                self._login_client()
                response = self.client.get(f"/digital-human/device-screenshot?id={device.id}")
                payload = b"".join(response.streaming_content)
                response.close()

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "image/png")
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
                self.assertEqual(payload, image_bytes)

    @mock.patch("app.utils.CloudS3.make_s3_client_from_env")
    def test_device_screenshot_route_streams_s3_object(self, mocked_make_s3_client):
        image_bytes = b"s3-screenshot-bytes"
        device = DigitalHumanDevice.objects.create(
            device_code="KD-016",
            agent_device_id="AGENT-016",
            machine_code="h" * 64,
            machine_mac="A4-2F-91-10-BC-16",
            tenant_name="front-desk",
        )
        device.screenshot_object_bucket = "digital-human-bucket"
        device.screenshot_object_key = "digital-human/screenshots/2026/05/13/device_16/frame.png"
        device.screenshot_storage_url = f"/digital-human/device-screenshot?id={device.id}"
        device.screenshot_content_type = "image/png"
        device.screenshot_byte_size = len(image_bytes)
        device.save(
            update_fields=[
                "screenshot_object_bucket",
                "screenshot_object_key",
                "screenshot_storage_url",
                "screenshot_content_type",
                "screenshot_byte_size",
            ]
        )

        mocked_client = mock.Mock()
        mocked_client.get_object.return_value = {"Body": io.BytesIO(image_bytes)}
        mocked_make_s3_client.return_value = mocked_client

        self._login_client()
        response = self.client.get(f"/digital-human/device-screenshot?id={device.id}")
        payload = b"".join(response.streaming_content)
        response.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(payload, image_bytes)
        mocked_client.get_object.assert_called_once_with(
            Bucket="digital-human-bucket",
            Key="digital-human/screenshots/2026/05/13/device_16/frame.png",
        )
