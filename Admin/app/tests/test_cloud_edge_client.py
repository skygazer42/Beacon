from unittest import mock

from django.test import SimpleTestCase


class _DummyResponse:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"code": 1000, "msg": "success", "data": []}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class CloudEdgeClientTest(SimpleTestCase):
    def test_list_streams_normalizes_base_url_and_injects_token_header(self):
        from app.utils.CloudEdgeClient import CloudEdgeClient

        with mock.patch(
            "app.utils.CloudEdgeClient.requests.get",
            return_value=_DummyResponse(payload={"code": 1000, "msg": "success", "data": [{"code": "cam001"}]}),
        ) as mocked_get:
            client = CloudEdgeClient(base_url="http://edge.local///", open_api_token="edge-token")
            data = client.list_streams()

        self.assertEqual(data, [{"code": "cam001"}])
        mocked_get.assert_called_once()
        args, kwargs = mocked_get.call_args
        self.assertEqual(args[0], "http://edge.local/open/getAllStreamData")
        self.assertEqual(kwargs.get("headers"), {"X-Beacon-Token": "edge-token"})
        self.assertEqual(kwargs.get("timeout"), 5.0)

    def test_edit_stream_posts_json_payload(self):
        from app.utils.CloudEdgeClient import CloudEdgeClient

        with mock.patch(
            "app.utils.CloudEdgeClient.requests.post",
            return_value=_DummyResponse(payload={"code": 1000, "msg": "success", "data": {"updated": True}}),
        ) as mocked_post:
            client = CloudEdgeClient(base_url="http://edge.local", open_api_token="edge-token")
            data = client.edit_stream({"code": "cam002", "nickname": "new-name"})

        self.assertEqual(data, {"updated": True})
        mocked_post.assert_called_once()
        args, kwargs = mocked_post.call_args
        self.assertEqual(args[0], "http://edge.local/stream/openEdit")
        self.assertEqual(kwargs.get("headers"), {"X-Beacon-Token": "edge-token"})
        self.assertEqual(kwargs.get("json"), {"code": "cam002", "nickname": "new-name"})
        self.assertEqual(kwargs.get("timeout"), 5.0)

    def test_list_core_processes_returns_info_and_data(self):
        from app.utils.CloudEdgeClient import CloudEdgeClient

        payload = {
            "code": 1000,
            "msg": "success",
            "info": {"processNum": 2},
            "data": [{"process_index": 0}, {"process_index": 1}],
        }
        with mock.patch("app.utils.CloudEdgeClient.requests.get", return_value=_DummyResponse(payload=payload)):
            client = CloudEdgeClient(base_url="http://edge.local", open_api_token="edge-token")
            data = client.list_core_processes()

        self.assertEqual(data.get("info"), {"processNum": 2})
        self.assertEqual(data.get("data"), [{"process_index": 0}, {"process_index": 1}])

    def test_timeout_raises_clear_error(self):
        import requests

        from app.utils.CloudEdgeClient import CloudEdgeClient, CloudEdgeClientError

        with mock.patch("app.utils.CloudEdgeClient.requests.get", side_effect=requests.Timeout("timed out")):
            client = CloudEdgeClient(base_url="http://edge.local", open_api_token="edge-token")
            with self.assertRaises(CloudEdgeClientError) as ctx:
                client.list_streams()

        self.assertIn("timed out", str(ctx.exception))

    def test_edge_error_code_raises_clear_error(self):
        from app.utils.CloudEdgeClient import CloudEdgeClient, CloudEdgeClientError

        with mock.patch(
            "app.utils.CloudEdgeClient.requests.get",
            return_value=_DummyResponse(payload={"code": 0, "msg": "edge denied"}),
        ):
            client = CloudEdgeClient(base_url="http://edge.local", open_api_token="edge-token")
            with self.assertRaises(CloudEdgeClientError) as ctx:
                client.list_streams()

        self.assertIn("edge denied", str(ctx.exception))

    def test_invalid_edge_code_raises_client_error(self):
        from app.utils.CloudEdgeClient import CloudEdgeClient, CloudEdgeClientError

        with mock.patch(
            "app.utils.CloudEdgeClient.requests.get",
            return_value=_DummyResponse(payload={"code": "invalid", "msg": "bad response"}),
        ):
            client = CloudEdgeClient(base_url="http://edge.local", open_api_token="edge-token")
            with self.assertRaises(CloudEdgeClientError):
                client.list_streams()
