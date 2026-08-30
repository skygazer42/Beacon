import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from app.services.digital_human import DigitalHumanError
from app.utils.CloudEdgeClient import CloudEdgeClientError
from app.views import (
    CloudConsoleView,
    CloudRemoteStreamDetailView,
    CloudRemoteStreamsView,
    ConfigExportView,
    ControlView,
    DigitalHumanApiView,
    DigitalHumanOpenView,
    StreamRecordingView,
    StreamView,
    api,
)


class PublicErrorRedactionTest(SimpleTestCase):
    secret_detail = "/secret/internal/runtime-path"

    @staticmethod
    def _body(response):
        return json.loads(response.content.decode("utf-8"))

    def test_cloud_alarm_preview_redacts_signing_error(self):
        row = SimpleNamespace(id=7, image_key="alarm/key.jpg", image_bucket="private")
        with mock.patch("app.utils.CloudS3.presign_get", side_effect=PermissionError(self.secret_detail)):
            url, error = CloudConsoleView._resolve_cloud_alarm_image_preview(row, use_proxy=False)

        self.assertEqual(url, "")
        self.assertEqual(error, "告警图片预览暂不可用")
        self.assertNotIn("secret", error)

    def test_remote_stream_list_redacts_client_error(self):
        cluster = SimpleNamespace(edge_admin_base_url="https://edge.example.test", edge_openapi_token="token")
        with mock.patch(
            "app.views.CloudRemoteStreamsView.CloudEdgeClient",
            side_effect=CloudEdgeClientError(self.secret_detail),
        ):
            error, rows = CloudRemoteStreamsView._fetch_remote_streams(cluster)

        self.assertEqual(rows, [])
        self.assertEqual(error, "远程摄像头列表暂不可用")
        self.assertNotIn("secret", error)

    def test_remote_stream_update_redacts_client_error(self):
        request = SimpleNamespace(method="POST", POST={})
        context = {"can_manage": True}
        client = mock.Mock()
        client.edit_stream.side_effect = CloudEdgeClientError(self.secret_detail)

        CloudRemoteStreamDetailView._handle_stream_detail_post(
            request,
            client=client,
            context=context,
            stream_code="camera-1",
        )

        self.assertEqual(context["error_msg"], "远程摄像头保存失败")
        self.assertNotIn("secret", context["error_msg"])

    def test_config_import_redacts_file_read_error(self):
        uploaded_file = mock.Mock()
        uploaded_file.read.side_effect = PermissionError(self.secret_detail)

        data, error = ConfigExportView._load_import_data_from_uploaded_file(uploaded_file)

        self.assertIsNone(data)
        self.assertEqual(error, "unable to read import file")
        self.assertNotIn("secret", error)

    def test_control_batch_operation_redacts_database_error(self):
        with mock.patch.object(ControlView.Control.objects, "filter", side_effect=PermissionError(self.secret_detail)):
            ok, error = ControlView._batch_control_try_apply("control-1", mock.Mock())

        self.assertFalse(ok)
        self.assertEqual(error, "布控操作失败")
        self.assertNotIn("secret", error)

    def test_stream_recording_redacts_runtime_error(self):
        request = SimpleNamespace(method="POST")
        params = {"stream_code": "camera-1", "stream_url": "rtsp://camera.example.test/live"}
        with (
            mock.patch.object(StreamRecordingView, "f_parsePostParams", return_value=params),
            mock.patch.object(StreamRecordingView, "get_stream_recorder", side_effect=PermissionError(self.secret_detail)),
        ):
            body = self._body(StreamRecordingView.api_start_recording(request))

        self.assertEqual(body["msg"], "开始录像失败")
        self.assertNotIn("secret", body["msg"])

    def test_stream_import_redacts_file_read_error(self):
        uploaded_file = mock.Mock()
        uploaded_file.read.side_effect = PermissionError(self.secret_detail)

        rows, error = StreamView._parse_stream_import_rows_csv(uploaded_file)

        self.assertIsNone(rows)
        self.assertEqual(error, "读取CSV失败")
        self.assertNotIn("secret", error)

    def test_platform_info_redacts_runtime_error(self):
        with mock.patch.object(api, "OSSystem", side_effect=PermissionError(self.secret_detail)):
            body = self._body(api.api_open_basic_info(SimpleNamespace()))

        self.assertEqual(body["msg"], "basic info unavailable")
        self.assertNotIn("secret", body["msg"])

    def test_digital_human_views_map_service_errors_to_public_messages(self):
        failure = mock.Mock(side_effect=DigitalHumanError(self.secret_detail, status_code=503))

        admin_body = self._body(DigitalHumanApiView._run(failure))
        open_response = DigitalHumanOpenView._run(failure)
        open_body = self._body(open_response)

        self.assertEqual(admin_body["msg"], "数字人监管服务暂不可用")
        self.assertEqual(open_body["message"], "service unavailable")
        self.assertEqual(open_response.status_code, 503)
        self.assertNotIn("secret", json.dumps([admin_body, open_body], ensure_ascii=False))
