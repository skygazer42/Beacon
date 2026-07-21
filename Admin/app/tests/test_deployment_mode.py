import os
from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from app.middleware import SimpleMiddleware
from app.utils.DeploymentMode import get_deployment_mode, is_cloud_mode, is_edge_mode


class DeploymentModeTest(SimpleTestCase):
    def test_default_is_edge(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BEACON_DEPLOYMENT_MODE", None)
            self.assertEqual(get_deployment_mode(), "edge")
            self.assertTrue(is_edge_mode())
            self.assertFalse(is_cloud_mode())


class EdgeCloudConnectionStateTest(SimpleTestCase):
    def test_configured_cloud_reports_real_health_result(self):
        from app.views import AppShellView
        from app.views.ViewsBase import g_config

        original = {
            "cloudEnabled": getattr(g_config, "cloudEnabled", False),
            "cloudBaseUrl": getattr(g_config, "cloudBaseUrl", ""),
            "cloudEdgeToken": getattr(g_config, "cloudEdgeToken", ""),
        }
        try:
            g_config.cloudEnabled = True
            g_config.cloudBaseUrl = "https://cloud.example.com"
            g_config.cloudEdgeToken = "edge-token"
            with mock.patch.object(
                AppShellView.CloudEdgeClient,
                "get_json",
                return_value={
                    "code": 1000,
                    "data": {"deployment_mode": "cloud", "version": "4.9.1"},
                },
            ):
                state = AppShellView._edge_cloud_connection_state()

            self.assertEqual(state.get("status"), "connected")
            self.assertEqual(state.get("version"), "4.9.1")
            self.assertNotIn("token", state)
        finally:
            for key, value in original.items():
                setattr(g_config, key, value)


class DeploymentModeMiddlewareTest(SimpleTestCase):
    def test_edge_blocks_open_cloud_paths_as_404(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BEACON_DEPLOYMENT_MODE", None)

            rf = RequestFactory()
            request = rf.get("/open/cloud/health", REMOTE_ADDR="8.8.8.8")
            request.session = {}

            middleware = SimpleMiddleware(get_response=lambda req: HttpResponse())
            response = middleware.process_request(request)

            self.assertIsNotNone(response)
            self.assertEqual(response.status_code, 404)

    def test_edge_blocks_open_cloud_path_without_trailing_slash_as_404(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BEACON_DEPLOYMENT_MODE", None)

            rf = RequestFactory()
            request = rf.get("/open/cloud", REMOTE_ADDR="8.8.8.8")
            request.session = {}

            middleware = SimpleMiddleware(get_response=lambda req: HttpResponse())
            response = middleware.process_request(request)

            self.assertIsNotNone(response)
            self.assertEqual(response.status_code, 404)

    def test_cloud_allows_open_cloud_path_through_guard(self):
        with mock.patch.dict(os.environ, {"BEACON_DEPLOYMENT_MODE": "cloud"}, clear=False):
            rf = RequestFactory()
            request = rf.get("/open/cloud/health", REMOTE_ADDR="8.8.8.8")
            request.session = {}

            middleware = SimpleMiddleware(get_response=lambda req: HttpResponse())
            response = middleware.process_request(request)

            self.assertIsNotNone(response)
            self.assertEqual(response.status_code, 401)
