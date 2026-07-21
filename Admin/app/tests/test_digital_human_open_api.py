import base64
import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest import mock

from django.test import TestCase

from app.models import (
    DigitalHumanAiDiagnosisConfig,
    DigitalHumanCommandResult,
    DigitalHumanCommandTask,
    DigitalHumanDevice,
    DigitalHumanHumanLog,
    DigitalHumanJwtAccount,
)
from app.services import digital_human as dh_service
from app.utils.DigitalHumanCrypto import sm4_encrypt_ecb_pkcs7


def _machine_code(secret, os_name, machine_mac, tenant_name):
    import hashlib

    return hashlib.sha256(f"{secret}{os_name}*{machine_mac}*{tenant_name}".encode("utf-8")).hexdigest()


class DigitalHumanOpenApiTests(TestCase):
    def setUp(self):
        super().setUp()
        os.environ["BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET"] = "test-authorization-secret"
        os.environ["BEACON_DIGITAL_HUMAN_UPLOAD_AUTH_SM4_SECRET_KEY"] = "00112233445566778899aabbccddeeff"
        self.addCleanup(os.environ.pop, "BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET", None)
        self.addCleanup(os.environ.pop, "BEACON_DIGITAL_HUMAN_UPLOAD_AUTH_SM4_SECRET_KEY", None)
        dh_service._REPLAY_CACHE.clear()
        dh_service._REPLAY_REDIS_CLIENT = None
        dh_service._REPLAY_REDIS_URL = ""
        dh_service._REPLAY_REDIS_CONFIG.update(
            {
                "expires_at": 0.0,
                "url": "",
                "cache_key_prefix": "beacon:digital-human:replay",
            }
        )

        self.jwt_secret = "0" * 32
        DigitalHumanJwtAccount.objects.create(
            account_uuid="jwt-account-001",
            project_name="数字人终端",
            tenant_name="front-desk",
            secret_hash=__import__("hashlib").sha256(self.jwt_secret.encode("utf-8")).hexdigest(),
            secret_mask="0011****eeff",
            token_ttl_minutes=30,
            credential_version=1,
            enabled=True,
        )

    def test_machine_secrets_are_required(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET": "",
                "APP_AGENT_AUTHORIZATION_SECRET": "",
                "BEACON_DIGITAL_HUMAN_UPLOAD_AUTH_SM4_SECRET_KEY": "",
                "APP_AGENT_UPLOAD_AUTH_SM4_SECRET_KEY": "",
            },
        ):
            for resolver in (dh_service._authorization_secret, dh_service._upload_auth_sm4_secret_key):
                with self.assertRaises(dh_service.DigitalHumanError) as raised:
                    resolver()
                self.assertEqual(raised.exception.status_code, 503)

    def _encrypted_machine_code_bearer(self, machine_code, timestamp):
        plain = f"{machine_code}*{timestamp}"
        cipher = sm4_encrypt_ecb_pkcs7(plain, os.environ["BEACON_DIGITAL_HUMAN_UPLOAD_AUTH_SM4_SECRET_KEY"])
        return f"Bearer {cipher}"

    def _issue_jwt_token(self, tenant_name="front-desk"):
        token_response = self.client.post(
            "/open/agent/token",
            data=json.dumps({"tenantName": tenant_name, "secret": self.jwt_secret}),
            content_type="application/json",
        )
        self.assertEqual(token_response.status_code, 200, msg=token_response.content)
        token_body = json.loads(token_response.content.decode("utf-8"))
        self.assertEqual(token_body["code"], 200, msg=token_body)
        return token_body["data"]["token"]

    def _register_authorized_device(self, *, tenant_name="front-desk", os_name="Windows 11", machine_mac="A4-2F-91-10-BC-01"):
        machine_code = _machine_code(
            os.environ["BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET"],
            os_name,
            machine_mac,
            tenant_name,
        )
        jwt_token = self._issue_jwt_token(tenant_name)
        register_response = self.client.post(
            "/open/agent/register",
            data=json.dumps(
                {
                    "machineCode": machine_code,
                    "machineMac": machine_mac,
                    "tenantName": tenant_name,
                    "osName": os_name,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        self.assertEqual(register_response.status_code, 200, msg=register_response.content)
        device = DigitalHumanDevice.objects.get(machine_code=machine_code)
        device.authorization_enabled = True
        device.authorization_status = "AUTHORIZED"
        device.save(update_fields=["authorization_enabled", "authorization_status"])
        return device, machine_code

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

    def test_open_agent_register_report_and_human_report_flow(self):
        os_name = "Windows 11"
        machine_mac = "A4-2F-91-10-BC-01"
        tenant_name = "front-desk"
        report_time = datetime.now().replace(microsecond=0)
        report_time_text = report_time.strftime("%Y-%m-%d %H:%M:%S")
        machine_code_timestamp = report_time.strftime("%Y%m%d%H%M%S")
        human_report_time_text = (report_time + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
        machine_code = _machine_code(
            os.environ["BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET"],
            os_name,
            machine_mac,
            tenant_name,
        )

        jwt_token = self._issue_jwt_token(tenant_name)

        register_response = self.client.post(
            "/open/agent/register",
            data=json.dumps(
                {
                    "machineCode": machine_code,
                    "machineMac": machine_mac,
                    "tenantName": tenant_name,
                    "osName": os_name,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        self.assertEqual(register_response.status_code, 200, msg=register_response.content)
        register_body = json.loads(register_response.content.decode("utf-8"))
        self.assertEqual(register_body["code"], 200, msg=register_body)
        self.assertEqual(register_body["data"]["authorizationStatus"], "PENDING")

        device = DigitalHumanDevice.objects.get(machine_code=machine_code)
        device.authorization_enabled = True
        device.authorization_status = "AUTHORIZED"
        device.save(update_fields=["authorization_enabled", "authorization_status"])

        report_response = self.client.post(
            "/open/agent/report",
            data=json.dumps(
                {
                    "osName": os_name,
                    "osVersion": "23H2",
                    "computerName": "DESKTOP-001",
                    "osUser": "beacon",
                    "processor": "Intel i7",
                    "processorArchitecture": "x64",
                    "macAddress": machine_mac,
                    "systemUptime": "1 day",
                    "cpuUsage": "72",
                    "gpuUsage": "40",
                    "memoryUsage": "64",
                    "diskUsage": "58",
                    "networkStatus": json.dumps({"latencyMs": 18, "bandwidth": "12.6 Mbps"}),
                    "netSpeed": "12.6 Mbps",
                    "activeWindow": json.dumps({"title": "欢迎播报", "process": "BeaconAvatar.exe"}),
                    "hardwareDevices": json.dumps({"camera": True, "microphone": True}),
                    "remoteMonitor": json.dumps({"status": "ok"}),
                    "serviceStatus": json.dumps({"stream": False, "llm": True}),
                    "reportTime": report_time_text,
                    "image": "",
                    "localIp": "10.0.0.9",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=self._encrypted_machine_code_bearer(machine_code, machine_code_timestamp),
        )
        self.assertEqual(report_response.status_code, 200, msg=report_response.content)
        report_body = json.loads(report_response.content.decode("utf-8"))
        self.assertEqual(report_body["code"], 200, msg=report_body)
        self.assertEqual(report_body["data"]["deviceId"], device.id)

        device.refresh_from_db()
        self.assertEqual(device.computer_name, "DESKTOP-001")
        self.assertEqual(int(device.cpu_usage), 72)
        self.assertFalse(device.service_stream)
        self.assertEqual(device.alert_rows.filter(status="pending", alert_type="stream_service_down").count(), 1)

        human_report_response = self.client.post(
            "/open/human/report",
            data=json.dumps(
                {
                    "deviceId": device.id,
                    "time": human_report_time_text,
                    "level": "ERROR",
                    "module": "stream",
                    "message": "push timeout",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=self._encrypted_machine_code_bearer(
                machine_code,
                (report_time + timedelta(seconds=1)).strftime("%Y%m%d%H%M%S"),
            ),
        )
        self.assertEqual(human_report_response.status_code, 200, msg=human_report_response.content)
        human_body = json.loads(human_report_response.content.decode("utf-8"))
        self.assertEqual(human_body["code"], 200, msg=human_body)
        self.assertEqual(DigitalHumanHumanLog.objects.filter(device=device).count(), 1)

    def test_open_agent_register_allows_multiple_new_devices(self):
        tenant_name = "front-desk"

        jwt_token = self._issue_jwt_token(tenant_name)

        register_payloads = [
            {
                "machineCode": _machine_code(
                    os.environ["BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET"],
                    "Windows 11",
                    "A4-2F-91-10-BC-01",
                    tenant_name,
                ),
                "machineMac": "A4-2F-91-10-BC-01",
                "tenantName": tenant_name,
                "osName": "Windows 11",
            },
            {
                "machineCode": _machine_code(
                    os.environ["BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET"],
                    "Windows 10",
                    "A4-2F-91-10-BC-02",
                    tenant_name,
                ),
                "machineMac": "A4-2F-91-10-BC-02",
                "tenantName": tenant_name,
                "osName": "Windows 10",
            },
        ]

        for payload in register_payloads:
            response = self.client.post(
                "/open/agent/register",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
            )
            self.assertEqual(response.status_code, 200, msg=response.content)
            body = json.loads(response.content.decode("utf-8"))
            self.assertEqual(body["code"], 200, msg=body)

        devices = list(DigitalHumanDevice.objects.order_by("id"))
        self.assertEqual(len(devices), 2)
        self.assertTrue(all(device.device_code for device in devices))
        self.assertTrue(all(device.agent_device_id for device in devices))

    def test_open_agent_register_uses_jwt_tenant_when_payload_tenant_mismatches(self):
        tenant_name = "front-desk"
        os_name = "Windows 11"
        machine_mac = "A4-2F-91-10-BC-09"
        machine_code = _machine_code(
            os.environ["BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET"],
            os_name,
            machine_mac,
            tenant_name,
        )
        jwt_token = self._issue_jwt_token(tenant_name)

        response = self.client.post(
            "/open/agent/register",
            data=json.dumps(
                {
                    "machineCode": machine_code,
                    "machineMac": machine_mac,
                    "tenantName": "wrong-tenant",
                    "osName": os_name,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        body = json.loads(response.content.decode("utf-8"))
        self.assertEqual(body["code"], 200, msg=body)

        device = DigitalHumanDevice.objects.get(machine_code=machine_code)
        self.assertEqual(device.tenant_name, tenant_name)
        self.assertEqual(device.registered_by_jwt_tenant_name, tenant_name)

    def test_open_agent_register_accepts_legacy_machine_code_for_payload_tenant_mismatch(self):
        jwt_tenant_name = "front-desk"
        payload_tenant_name = "user"
        os_name = "Windows 11"
        machine_mac = "A4-2F-91-10-BC-10"
        machine_code = _machine_code(
            os.environ["BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET"],
            os_name,
            machine_mac,
            payload_tenant_name,
        )
        jwt_token = self._issue_jwt_token(jwt_tenant_name)

        response = self.client.post(
            "/open/agent/register",
            data=json.dumps(
                {
                    "machineCode": machine_code,
                    "machineMac": machine_mac,
                    "tenantName": payload_tenant_name,
                    "osName": os_name,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        body = json.loads(response.content.decode("utf-8"))
        self.assertEqual(body["code"], 200, msg=body)

        device = DigitalHumanDevice.objects.get(machine_code=machine_code)
        self.assertEqual(device.tenant_name, jwt_tenant_name)
        self.assertEqual(device.registered_by_jwt_tenant_name, jwt_tenant_name)

    @mock.patch("app.services.digital_human.requests.post")
    def test_open_human_report_persists_ai_diagnosis_during_ingest(self, mocked_post):
        mocked_response = mock.Mock(status_code=200, text="ok")
        mocked_response.json.return_value = {
            "choices": [{"message": {"content": "请优先检查推流服务、网络链路和最近的超时异常。"}}]
        }
        mocked_post.return_value = mocked_response
        self._create_ai_config()
        report_time = datetime.now().replace(microsecond=0)
        device, machine_code = self._register_authorized_device(machine_mac="A4-2F-91-10-BC-03")

        response = self.client.post(
            "/open/human/report",
            data=json.dumps(
                {
                    "deviceId": device.id,
                    "time": report_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "level": "ERROR",
                    "module": "stream",
                    "message": "push timeout",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=self._encrypted_machine_code_bearer(
                machine_code,
                report_time.strftime("%Y%m%d%H%M%S"),
            ),
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        log_row = DigitalHumanHumanLog.objects.get(device=device)
        self.assertEqual(log_row.diagnosis_status, "success")
        self.assertEqual(log_row.diagnosis_text, "请优先检查推流服务、网络链路和最近的超时异常。")
        mocked_post.assert_called_once()

    @mock.patch("app.services.digital_human.requests.post")
    def test_open_human_report_skips_ai_during_ingest_for_info_level(self, mocked_post):
        self._create_ai_config()
        report_time = datetime.now().replace(microsecond=0)
        device, machine_code = self._register_authorized_device(machine_mac="A4-2F-91-10-BC-04")

        response = self.client.post(
            "/open/human/report",
            data=json.dumps(
                {
                    "deviceId": device.id,
                    "time": report_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "level": "INFO",
                    "module": "stream",
                    "message": "heartbeat ok",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=self._encrypted_machine_code_bearer(
                machine_code,
                report_time.strftime("%Y%m%d%H%M%S"),
            ),
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        log_row = DigitalHumanHumanLog.objects.get(device=device)
        self.assertEqual(log_row.diagnosis_status, "skipped")
        self.assertEqual(log_row.diagnosis_text, "INFO 级别日志无需 AI 分析。")
        mocked_post.assert_not_called()

    def test_open_agent_report_rejects_plain_invalid_machine_code(self):
        response = self.client.post(
            "/open/agent/report",
            data=json.dumps(
                {
                    "computerName": "DESKTOP-001",
                    "macAddress": "AA-BB-CC",
                    "reportTime": "2026-05-13 10:12:30",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )

        self.assertEqual(response.status_code, 401, msg=response.content)
        body = json.loads(response.content.decode("utf-8"))
        self.assertEqual(body["code"], -1)

    def test_open_agent_config_and_commands_flow(self):
        tenant_name = "front-desk"
        os_name = "Windows 11"
        machine_mac = "A4-2F-91-10-BC-08"
        machine_code = _machine_code(
            os.environ["BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET"],
            os_name,
            machine_mac,
            tenant_name,
        )
        jwt_token = self._issue_jwt_token(tenant_name)

        register_response = self.client.post(
            "/open/agent/register",
            data=json.dumps(
                {
                    "machineCode": machine_code,
                    "machineMac": machine_mac,
                    "tenantName": tenant_name,
                    "osName": os_name,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        self.assertEqual(register_response.status_code, 200, msg=register_response.content)
        device = DigitalHumanDevice.objects.get(machine_code=machine_code)
        device.authorization_enabled = True
        device.authorization_status = "AUTHORIZED"
        device.save(update_fields=["authorization_enabled", "authorization_status"])

        config_response = self.client.get(
            f"/open/agent/config/latest?deviceId={device.id}",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        self.assertEqual(config_response.status_code, 200, msg=config_response.content)
        config_body = json.loads(config_response.content.decode("utf-8"))
        self.assertEqual(config_body["code"], 200, msg=config_body)
        self.assertEqual(config_body["data"]["deviceId"], device.id)
        self.assertEqual(config_body["data"]["config"]["reportIntervalSec"], 30)

        task = DigitalHumanCommandTask.objects.create(
            device=device,
            command_type="RESTART_STREAM",
            command_payload='{"force":true}',
            status="PENDING",
        )
        pull_response = self.client.get(
            f"/open/agent/commands/pull?deviceId={device.id}",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        self.assertEqual(pull_response.status_code, 200, msg=pull_response.content)
        pull_body = json.loads(pull_response.content.decode("utf-8"))
        self.assertEqual(pull_body["code"], 200, msg=pull_body)
        self.assertEqual(pull_body["data"]["pendingCount"], 1)
        self.assertEqual(pull_body["data"]["commands"][0]["commandId"], task.id)

        result_response = self.client.post(
            "/open/agent/commands/result",
            data=json.dumps(
                {
                    "deviceId": device.id,
                    "commandId": task.id,
                    "success": True,
                    "resultMessage": "stream restarted",
                    "resultPayload": '{"restartAt":"2026-05-13 10:22:00"}',
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        self.assertEqual(result_response.status_code, 200, msg=result_response.content)
        result_body = json.loads(result_response.content.decode("utf-8"))
        self.assertEqual(result_body["code"], 200, msg=result_body)

        task.refresh_from_db()
        self.assertEqual(task.status, "SUCCESS")
        self.assertTrue(DigitalHumanCommandResult.objects.filter(command_task=task, success=True).exists())

    def test_open_agent_report_rejects_replayed_machine_code_payload(self):
        report_time = datetime.now().replace(microsecond=0)
        report_time_text = report_time.strftime("%Y-%m-%d %H:%M:%S")
        machine_code_timestamp = report_time.strftime("%Y%m%d%H%M%S")
        device, machine_code = self._register_authorized_device(machine_mac="A4-2F-91-10-BC-77")
        authorization = self._encrypted_machine_code_bearer(machine_code, machine_code_timestamp)
        payload = {
            "osName": "Windows 11",
            "computerName": "DESKTOP-REPLAY",
            "macAddress": "A4-2F-91-10-BC-77",
            "reportTime": report_time_text,
            "image": "",
        }

        first = self.client.post(
            "/open/agent/report",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=authorization,
        )
        second = self.client.post(
            "/open/agent/report",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=authorization,
        )

        self.assertEqual(first.status_code, 200, msg=first.content)
        self.assertEqual(second.status_code, 401, msg=second.content)
        self.assertEqual(DigitalHumanDevice.objects.get(id=device.id).metric_rows.count(), 1)

    @mock.patch("app.services.digital_human.cache.add")
    @mock.patch("app.services.digital_human._get_replay_redis_client")
    def test_open_agent_report_prefers_redis_replay_guard_when_available(self, mocked_get_redis_client, mocked_cache_add):
        report_time = datetime.now().replace(microsecond=0)
        report_time_text = report_time.strftime("%Y-%m-%d %H:%M:%S")
        machine_code_timestamp = report_time.strftime("%Y%m%d%H%M%S")
        device, machine_code = self._register_authorized_device(machine_mac="A4-2F-91-10-BC-78")
        authorization = self._encrypted_machine_code_bearer(machine_code, machine_code_timestamp)
        redis_client = mock.Mock()
        redis_client.set.side_effect = [True, False]
        mocked_get_redis_client.return_value = (redis_client, "beacon:digital-human:test")
        payload = {
            "osName": "Windows 11",
            "computerName": "DESKTOP-REDIS-REPLAY",
            "macAddress": "A4-2F-91-10-BC-78",
            "reportTime": report_time_text,
            "image": "",
        }

        first = self.client.post(
            "/open/agent/report",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=authorization,
        )
        second = self.client.post(
            "/open/agent/report",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=authorization,
        )

        self.assertEqual(first.status_code, 200, msg=first.content)
        self.assertEqual(second.status_code, 401, msg=second.content)
        self.assertEqual(redis_client.set.call_count, 2)
        mocked_cache_add.assert_not_called()
        self.assertEqual(DigitalHumanDevice.objects.get(id=device.id).metric_rows.count(), 1)

    def test_open_agent_report_persists_screenshot_to_local_storage(self):
        report_time = datetime.now().replace(microsecond=0)
        report_time_text = report_time.strftime("%Y-%m-%d %H:%M:%S")
        machine_code_timestamp = report_time.strftime("%Y%m%d%H%M%S")
        device, machine_code = self._register_authorized_device(machine_mac="A4-2F-91-10-BC-88")
        image_bytes = b"fake-png-bytes"
        image_data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")

        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch("app.services.digital_human._digital_human_screenshot_bucket", return_value=""):
                with mock.patch.object(dh_service.g_config, "uploadDir", tempdir, create=True):
                    response = self.client.post(
                        "/open/agent/report",
                        data=json.dumps(
                            {
                                "osName": "Windows 11",
                                "computerName": "DESKTOP-SCREENSHOT",
                                "macAddress": "A4-2F-91-10-BC-88",
                                "reportTime": report_time_text,
                                "image": image_data_url,
                            }
                        ),
                        content_type="application/json",
                        HTTP_AUTHORIZATION=self._encrypted_machine_code_bearer(machine_code, machine_code_timestamp),
                    )
                    self.assertEqual(response.status_code, 200, msg=response.content)
                    device.refresh_from_db()
                    self.assertEqual(device.screenshot_object_bucket, "")
                    self.assertEqual(device.screenshot_object_key, "")
                    self.assertTrue(device.screenshot_storage_path)
                    self.assertEqual(device.screenshot_storage_url, f"/digital-human/device-screenshot?id={device.id}")
                    self.assertEqual(device.screenshot_content_type, "image/png")
                    self.assertEqual(device.screenshot_byte_size, len(image_bytes))
                    self.assertEqual(device.screenshot_base64, "")
                    stored_path = os.path.join(tempdir, *device.screenshot_storage_path.split("/"))
                    self.assertTrue(os.path.isfile(stored_path))
                    with open(stored_path, "rb") as handle:
                        self.assertEqual(handle.read(), image_bytes)

    @mock.patch("app.utils.CloudS3.make_s3_client_from_env")
    def test_open_agent_report_persists_screenshot_to_object_storage(self, mocked_make_s3_client):
        report_time = datetime.now().replace(microsecond=0)
        report_time_text = report_time.strftime("%Y-%m-%d %H:%M:%S")
        machine_code_timestamp = report_time.strftime("%Y%m%d%H%M%S")
        device, machine_code = self._register_authorized_device(machine_mac="A4-2F-91-10-BC-91")
        image_bytes = b"fake-png-object-bytes"
        image_data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        mocked_client = mock.Mock()
        mocked_make_s3_client.return_value = mocked_client

        with mock.patch("app.services.digital_human._digital_human_screenshot_bucket", return_value="digital-human-bucket"):
            response = self.client.post(
                "/open/agent/report",
                data=json.dumps(
                    {
                        "osName": "Windows 11",
                        "computerName": "DESKTOP-S3-SCREENSHOT",
                        "macAddress": "A4-2F-91-10-BC-91",
                        "reportTime": report_time_text,
                        "image": image_data_url,
                    }
                ),
                content_type="application/json",
                HTTP_AUTHORIZATION=self._encrypted_machine_code_bearer(machine_code, machine_code_timestamp),
            )

        self.assertEqual(response.status_code, 200, msg=response.content)
        device.refresh_from_db()
        self.assertEqual(device.screenshot_object_bucket, "digital-human-bucket")
        self.assertTrue(device.screenshot_object_key.startswith(report_time.strftime("digital-human/screenshots/%Y/%m/%d/")))
        self.assertIn(f"/device_{device.id}/", device.screenshot_object_key)
        self.assertTrue(device.screenshot_object_key.endswith(".png"))
        self.assertEqual(device.screenshot_storage_path, "")
        self.assertEqual(device.screenshot_storage_url, f"/digital-human/device-screenshot?id={device.id}")
        self.assertEqual(device.screenshot_content_type, "image/png")
        self.assertEqual(device.screenshot_byte_size, len(image_bytes))
        self.assertEqual(device.screenshot_base64, "")
        mocked_client.put_object.assert_called_once_with(
            Bucket="digital-human-bucket",
            Key=device.screenshot_object_key,
            Body=image_bytes,
            ContentType="image/png",
        )

    def test_open_agent_report_replaces_previous_local_screenshot_file(self):
        first_report_time = datetime.now().replace(microsecond=0)
        second_report_time = first_report_time + timedelta(seconds=1)
        device, machine_code = self._register_authorized_device(machine_mac="A4-2F-91-10-BC-89")
        first_image_bytes = b"first-png-bytes"
        second_image_bytes = b"second-png-bytes"
        first_image = "data:image/png;base64," + base64.b64encode(first_image_bytes).decode("ascii")
        second_image = "data:image/png;base64," + base64.b64encode(second_image_bytes).decode("ascii")

        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch("app.services.digital_human._digital_human_screenshot_bucket", return_value=""):
                with mock.patch.object(dh_service.g_config, "uploadDir", tempdir, create=True):
                    first_response = self.client.post(
                        "/open/agent/report",
                        data=json.dumps(
                            {
                                "osName": "Windows 11",
                                "computerName": "DESKTOP-SCREENSHOT",
                                "macAddress": "A4-2F-91-10-BC-89",
                                "reportTime": first_report_time.strftime("%Y-%m-%d %H:%M:%S"),
                                "image": first_image,
                            }
                        ),
                        content_type="application/json",
                        HTTP_AUTHORIZATION=self._encrypted_machine_code_bearer(
                            machine_code,
                            first_report_time.strftime("%Y%m%d%H%M%S"),
                        ),
                    )
                    self.assertEqual(first_response.status_code, 200, msg=first_response.content)
                    device.refresh_from_db()
                    first_rel_path = device.screenshot_storage_path
                    first_abs_path = os.path.join(tempdir, *first_rel_path.split("/"))
                    self.assertTrue(os.path.isfile(first_abs_path))

                    with self.captureOnCommitCallbacks(execute=True):
                        second_response = self.client.post(
                            "/open/agent/report",
                            data=json.dumps(
                                {
                                    "osName": "Windows 11",
                                    "computerName": "DESKTOP-SCREENSHOT",
                                    "macAddress": "A4-2F-91-10-BC-89",
                                    "reportTime": second_report_time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "image": second_image,
                                }
                            ),
                            content_type="application/json",
                            HTTP_AUTHORIZATION=self._encrypted_machine_code_bearer(
                                machine_code,
                                second_report_time.strftime("%Y%m%d%H%M%S"),
                            ),
                        )
                    self.assertEqual(second_response.status_code, 200, msg=second_response.content)
                    device.refresh_from_db()
                    second_abs_path = os.path.join(tempdir, *device.screenshot_storage_path.split("/"))

                    self.assertNotEqual(device.screenshot_storage_path, first_rel_path)
                    self.assertFalse(os.path.exists(first_abs_path))
                    self.assertTrue(os.path.isfile(second_abs_path))
                    with open(second_abs_path, "rb") as handle:
                        self.assertEqual(handle.read(), second_image_bytes)

    def test_open_agent_report_ignores_non_image_data_url(self):
        report_time = datetime.now().replace(microsecond=0)
        report_time_text = report_time.strftime("%Y-%m-%d %H:%M:%S")
        machine_code_timestamp = report_time.strftime("%Y%m%d%H%M%S")
        device, machine_code = self._register_authorized_device(machine_mac="A4-2F-91-10-BC-90")
        html_payload = "data:text/html;base64," + base64.b64encode(b"<script>alert(1)</script>").decode("ascii")

        response = self.client.post(
            "/open/agent/report",
            data=json.dumps(
                {
                    "osName": "Windows 11",
                    "computerName": "DESKTOP-NONIMAGE",
                    "macAddress": "A4-2F-91-10-BC-90",
                    "reportTime": report_time_text,
                    "image": html_payload,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=self._encrypted_machine_code_bearer(machine_code, machine_code_timestamp),
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        device.refresh_from_db()
        self.assertEqual(device.screenshot_object_bucket, "")
        self.assertEqual(device.screenshot_object_key, "")
        self.assertEqual(device.screenshot_storage_path, "")
        self.assertEqual(device.screenshot_storage_url, "")
        self.assertEqual(device.screenshot_content_type, "")
        self.assertEqual(device.screenshot_byte_size, 0)
        self.assertEqual(device.screenshot_base64, "")
