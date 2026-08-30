from types import SimpleNamespace
from unittest import TestCase, mock

from app.utils.CloudEdgeClient import CloudEdgeClientError
from app.views.CloudRemotePlatformView import _fetch_remote_platform_data


class CloudRemotePlatformErrorRedactionTest(TestCase):
    def test_remote_client_error_is_not_returned_to_callers(self):
        cluster = SimpleNamespace(
            edge_admin_base_url="https://edge.example.test",
            edge_openapi_token="test-token",
        )
        with mock.patch(
            "app.views.CloudRemotePlatformView.CloudEdgeClient",
            side_effect=CloudEdgeClientError("internal upstream path /secret/edge"),
        ):
            error, flows, processes, info = _fetch_remote_platform_data(cluster)

        self.assertEqual(error, "远端平台暂不可用")
        self.assertNotIn("secret", error)
        self.assertEqual(flows, [])
        self.assertEqual(processes, [])
        self.assertEqual(info, {})
