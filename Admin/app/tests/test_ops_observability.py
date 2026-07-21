import json
import os
from unittest import mock
from datetime import datetime, time as datetime_time, timedelta, timezone as datetime_timezone
from types import SimpleNamespace

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from app.middleware import SimpleMiddleware
from app.views import OpsView
from app.views import api as api_view


class RestartSchedulingTest(SimpleTestCase):
    def _capture_thread(self):
        captured = {}

        def fake_thread(*, target=None, name=None, daemon=None):
            captured.update(target=target, name=name, daemon=daemon)
            thread = mock.Mock()
            thread.start.return_value = None
            captured["thread"] = thread
            return thread

        return captured, fake_thread

    def test_admin_restart_is_scheduled_without_blocking_request_thread(self):
        captured, fake_thread = self._capture_thread()
        with mock.patch("app.views.api.threading.Thread", side_effect=fake_thread):
            api_view._schedule_admin_restart(delay_seconds=5)

        captured["thread"].start.assert_called_once_with()
        self.assertTrue(callable(captured["target"]))
        self.assertTrue(captured["daemon"])

    def test_system_restart_is_scheduled_without_blocking_request_thread(self):
        captured, fake_thread = self._capture_thread()
        with mock.patch("app.views.api.threading.Thread", side_effect=fake_thread):
            api_view._schedule_system_restart(delay_seconds=5)

        captured["thread"].start.assert_called_once_with()
        self.assertTrue(callable(captured["target"]))
        self.assertTrue(captured["daemon"])


class DestructiveBoundaryTest(TestCase):
    def _post_openapi(self, path, payload):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN="ops-boundary-token",
        )

    def test_restart_routes_only_cross_mocked_scheduler_boundaries(self):
        with (
            mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "ops-boundary-token"}, clear=False),
            mock.patch("app.views.api._schedule_admin_restart") as admin_restart,
        ):
            software = self._post_openapi("/open/platform/restartSoftware", {})
        software_payload = json.loads(software.content.decode("utf-8"))
        self.assertEqual(software_payload.get("code"), 1000, msg=software_payload)
        admin_restart.assert_called_once()

        with (
            mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "ops-boundary-token"}, clear=False),
            mock.patch("app.views.api._schedule_system_restart") as system_restart,
        ):
            system = self._post_openapi("/open/platform/restartSystem", {})
        system_payload = json.loads(system.content.decode("utf-8"))
        self.assertEqual(system_payload.get("code"), 1000, msg=system_payload)
        system_restart.assert_called_once()

    def test_logging_level_route_only_crosses_mocked_apply_boundary(self):
        with (
            mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "ops-boundary-token"}, clear=False),
            mock.patch("app.views.OpsView._apply_logging_levels", return_value=["app.middleware"]) as apply_levels,
        ):
            response = self._post_openapi(
                "/open/ops/logging/level",
                {"level": "INFO", "logger": "app.middleware"},
            )

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)
        self.assertEqual((payload.get("data") or {}).get("loggers"), ["app.middleware"])
        apply_levels.assert_called_once()

    def test_cleanup_dry_run_reports_metrics_cache_target(self):
        with OpsView._METRICS_COUNT_CACHE_LOCK:
            original_cache = dict(OpsView._METRICS_COUNT_CACHE)
            OpsView._METRICS_COUNT_CACHE.clear()
            OpsView._METRICS_COUNT_CACHE.update({"k1": {"value": 1}, "k2": {"value": 2}})

        def restore_metrics_cache():
            with OpsView._METRICS_COUNT_CACHE_LOCK:
                OpsView._METRICS_COUNT_CACHE.clear()
                OpsView._METRICS_COUNT_CACHE.update(original_cache)

        self.addCleanup(restore_metrics_cache)

        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "ops-boundary-token"}, clear=False):
            response = self._post_openapi(
                "/open/ops/cleanup",
                {"targets": ["metrics_cache"], "dry_run": True},
            )

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)
        data = payload.get("data") or {}
        self.assertTrue(data.get("dry_run"))
        self.assertEqual(((data.get("targets") or {}).get("metrics_cache") or {}).get("cleared_keys"), 2)


class OpsMiddlewareAuthTest(SimpleTestCase):
    def _build_get(self, path: str, *, remote_addr: str = "8.8.8.8", token: str = ""):
        rf = RequestFactory()
        kwargs = {"REMOTE_ADDR": remote_addr}
        if token:
            kwargs["HTTP_X_BEACON_TOKEN"] = token
        req = rf.get(path, **kwargs)
        req.session = {}
        return req

    def test_healthz_unauthorized_is_401_not_redirect(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            req = self._build_get("/healthz")
            mw = SimpleMiddleware(get_response=lambda r: HttpResponse())
            resp = mw.process_request(req)

            self.assertIsNotNone(resp)
            self.assertEqual(resp.status_code, 401)

    def test_metrics_authorized_passes_through_middleware(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            req = self._build_get("/metrics", token="t1")
            mw = SimpleMiddleware(get_response=lambda r: HttpResponse("ok"))
            resp = mw.process_request(req)

            self.assertIsNone(resp)


class OpsHealthEndpointTest(TestCase):
    def test_healthz_ok(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")

        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)
        self.assertEqual((body.get("data") or {}).get("status"), "ok", msg=body)
        self.assertIn("background_services", body.get("data") or {})

    def test_open_ops_health_alias_ok(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            res = self.client.get("/open/ops/health", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")

        self.assertEqual(res.status_code, 200, msg=res.content)


class BackgroundServicesStartupStateTest(SimpleTestCase):
    _STATE_DEFAULTS = {
        "_started": False,
        "_startup_state": "not_started",
        "_startup_failures": {},
        "_started_components": set(),
        "_background_threads": {},
        "_service_candidates": {},
        "_services": {},
    }

    def _reset_module_state(self, module):
        missing = object()
        originals = {name: getattr(module, name, missing) for name in self._STATE_DEFAULTS}
        for name, value in self._STATE_DEFAULTS.items():
            if isinstance(value, (dict, set)):
                value = value.copy()
            setattr(module, name, value)

        def restore():
            for name, value in originals.items():
                if value is missing:
                    delattr(module, name)
                else:
                    setattr(module, name, value)

        self.addCleanup(restore)

    @staticmethod
    def _thread_factory(created_threads):
        def create_thread(**kwargs):
            thread = mock.Mock()
            thread.name = kwargs.get("name")
            created_threads.append(thread)
            return thread

        return create_thread

    def test_partial_start_is_degraded_and_second_call_retries_only_missing_component(self):
        from app.utils import BackgroundServices as background

        self._reset_module_state(background)
        alarm_sink = mock.Mock()
        alarm_sink.start.side_effect = (RuntimeError("thread unavailable"), None)
        services = {
            "AlarmSinkDispatcher": alarm_sink,
            "AlarmOutboxDispatcher": mock.Mock(),
            "TranscodeManager": mock.Mock(),
            "RecordingPlanService": mock.Mock(),
            "TaskPlanService": mock.Mock(),
        }
        created_threads = []

        with (
            mock.patch.dict(os.environ, {"BEACON_DISABLE_BACKGROUND": "0"}, clear=False),
            mock.patch.object(background, "AlarmSinkDispatcher", return_value=services["AlarmSinkDispatcher"]),
            mock.patch.object(background, "AlarmOutboxDispatcher", return_value=services["AlarmOutboxDispatcher"]),
            mock.patch.object(background, "TranscodeManager", return_value=services["TranscodeManager"]),
            mock.patch.object(background, "RecordingPlanService", return_value=services["RecordingPlanService"]),
            mock.patch.object(background, "TaskPlanService", return_value=services["TaskPlanService"]),
            mock.patch.object(
                background.threading,
                "Thread",
                side_effect=self._thread_factory(created_threads),
            ),
        ):
            first = background.start_background_services()
            self.assertEqual(first["state"], "degraded")
            self.assertEqual(first["failed_components"], ["alarm_sink"])
            self.assertEqual(first["failure_types"], {"alarm_sink": "RuntimeError"})
            self.assertFalse(background._started)

            second = background.start_background_services()

        self.assertEqual(second["state"], "running")
        self.assertEqual(second["failed_components"], [])
        self.assertTrue(background._started)
        self.assertIs(background.get_alarm_sink_dispatcher(), alarm_sink)
        self.assertEqual(background.get_background_services_status(), second)
        self.assertEqual(alarm_sink.start.call_count, 2)
        for name, service in services.items():
            expected_calls = 2 if name == "AlarmSinkDispatcher" else 1
            self.assertEqual(service.start.call_count, expected_calls)
        self.assertEqual(len(created_threads), 7)
        self.assertTrue(all(thread.start.call_count == 1 for thread in created_threads))

    def test_disabled_background_state_is_observable_without_starting_components(self):
        from app.utils import BackgroundServices as background

        self._reset_module_state(background)
        with (
            mock.patch.dict(os.environ, {"BEACON_DISABLE_BACKGROUND": "1"}, clear=False),
            mock.patch.object(background, "AlarmSinkDispatcher") as service_factory,
            mock.patch.object(background.threading, "Thread") as thread_factory,
        ):
            status = background.start_background_services()

        self.assertEqual(status["state"], "disabled")
        self.assertEqual(background.get_background_services_status(), status)
        self.assertFalse(background._started)
        service_factory.assert_not_called()
        thread_factory.assert_not_called()

    def test_starting_state_can_be_observed_while_component_start_is_in_progress(self):
        from app.utils import BackgroundServices as background

        self._reset_module_state(background)
        real_thread_class = background.threading.Thread
        event_class = background.threading.Event
        start_entered = event_class()
        allow_start_to_finish = event_class()
        alarm_sink = mock.Mock()

        def blocking_start():
            start_entered.set()
            allow_start_to_finish.wait(timeout=2)

        alarm_sink.start.side_effect = blocking_start
        other_services = [mock.Mock() for _ in range(4)]
        created_threads = []
        start_results = []

        with (
            mock.patch.dict(os.environ, {"BEACON_DISABLE_BACKGROUND": "0"}, clear=False),
            mock.patch.object(background, "AlarmSinkDispatcher", return_value=alarm_sink),
            mock.patch.object(background, "AlarmOutboxDispatcher", return_value=other_services[0]),
            mock.patch.object(background, "TranscodeManager", return_value=other_services[1]),
            mock.patch.object(background, "RecordingPlanService", return_value=other_services[2]),
            mock.patch.object(background, "TaskPlanService", return_value=other_services[3]),
            mock.patch.object(
                background.threading,
                "Thread",
                side_effect=self._thread_factory(created_threads),
            ),
        ):
            starter = real_thread_class(
                target=lambda: start_results.append(background.start_background_services())
            )
            starter.start()
            self.assertTrue(start_entered.wait(timeout=1))

            snapshots = []
            observer = real_thread_class(
                target=lambda: snapshots.append(background.get_background_services_status())
            )
            observer.start()
            observer.join(timeout=0.2)
            observed_before_finish = not observer.is_alive()

            allow_start_to_finish.set()
            starter.join(timeout=2)
            observer.join(timeout=2)

        self.assertTrue(observed_before_finish)
        self.assertEqual(snapshots[0]["state"], "starting")
        self.assertEqual(start_results[0]["state"], "running")


class OpsReadyEndpointTest(TestCase):
    def test_readyz_ok(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            res = self.client.get("/readyz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_readyz_db_fail_is_503(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            with mock.patch("app.views.OpsView._check_db", return_value={"ok": False, "error": "boom"}, create=True):
                res = self.client.get("/readyz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")
        self.assertEqual(res.status_code, 503, msg=res.content)


class OpsMetricsEndpointTest(TestCase):
    def test_metrics_contains_key_metrics(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            res = self.client.get("/metrics", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")

        self.assertEqual(res.status_code, 200, msg=res.content)
        self.assertTrue(str(res["Content-Type"]).startswith("text/plain"), msg=res["Content-Type"])

        text = res.content.decode("utf-8")
        self.assertIn("beacon_admin_build_info", text)
        self.assertIn("beacon_admin_uptime_seconds", text)
        self.assertIn("beacon_admin_db_up", text)

    def test_metrics_accepts_authorization_bearer(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            res = self.client.get("/metrics", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Bearer t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_metrics_accepts_authorization_bearer_with_mixed_case_and_whitespace(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            res = self.client.get("/metrics", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="bEaReR\t  t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_metrics_caches_expensive_counts(self):
        """
        工业场景：Prometheus 抓取频率高，如果每次都对大表做 count/distinct，容易拖垮 DB。

        这个用例用“行为可观测”的方式验证缓存存在：
        - 第一次 scrape 后创建新的 outbox 记录
        - TTL 内再次 scrape，pending 数应该保持不变（来自缓存）
        """
        from app.models import AlarmEventOutbox

        AlarmEventOutbox.objects.create(event_id="e1", sink_type="webhook", status="pending")

        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            from app.views import OpsView
            # isolate cache between tests (if implemented)
            for name in ("_METRICS_COUNT_CACHE", "_METRICS_CACHE"):
                cache = getattr(OpsView, name, None)
                if isinstance(cache, dict):
                    cache.clear()

            res1 = self.client.get("/metrics", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")
        self.assertEqual(res1.status_code, 200, msg=res1.content)
        text1 = res1.content.decode("utf-8")

        def _metric_value(text: str, metric: str) -> int:
            for line in (text or "").splitlines():
                if line.startswith(metric + " "):
                    try:
                        return int(float(line.split()[-1]))
                    except Exception:
                        return -1
            return -1

        pending1 = _metric_value(text1, "beacon_admin_alarm_outbox_pending")
        self.assertEqual(pending1, 1, msg=text1)

        # create new row after first scrape
        AlarmEventOutbox.objects.create(event_id="e2", sink_type="webhook", status="pending")

        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            res2 = self.client.get("/metrics", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")
        self.assertEqual(res2.status_code, 200, msg=res2.content)
        text2 = res2.content.decode("utf-8")

        pending2 = _metric_value(text2, "beacon_admin_alarm_outbox_pending")
        self.assertEqual(pending2, 1, msg=text2)

    def test_metrics_cache_ttl_env_can_disable_count_cache(self):
        from app.models import AlarmEventOutbox
        from app.views import OpsView

        AlarmEventOutbox.objects.create(event_id="e1_ttl0", sink_type="webhook", status="pending")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_OPS_METRICS_COUNT_CACHE_TTL_SECONDS": "0",
            },
            clear=False,
        ):
            for name in ("_METRICS_COUNT_CACHE", "_METRICS_CACHE"):
                cache = getattr(OpsView, name, None)
                if isinstance(cache, dict):
                    cache.clear()

            res1 = self.client.get("/metrics", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")
            self.assertEqual(res1.status_code, 200, msg=res1.content)
            text1 = res1.content.decode("utf-8")

            def _metric_value(text: str, metric: str) -> int:
                for line in (text or "").splitlines():
                    if line.startswith(metric + " "):
                        try:
                            return int(float(line.split()[-1]))
                        except Exception:
                            return -1
                return -1

            self.assertEqual(_metric_value(text1, "beacon_admin_alarm_outbox_pending"), 1, msg=text1)

            AlarmEventOutbox.objects.create(event_id="e2_ttl0", sink_type="webhook", status="pending")
            res2 = self.client.get("/metrics", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")
            self.assertEqual(res2.status_code, 200, msg=res2.content)
            text2 = res2.content.decode("utf-8")

            # TTL=0 means no count cache reuse; second scrape should observe new row.
            self.assertEqual(_metric_value(text2, "beacon_admin_alarm_outbox_pending"), 2, msg=text2)

    def test_metrics_contains_login_lockout_metrics(self):
        from app.models import LoginLockout
        from app.views import OpsView

        now_ts = timezone.now()
        LoginLockout.objects.create(
            username="user:100",
            source_ip="15.15.15.15",
            failures=3,
            first_failure_at=now_ts - timedelta(minutes=1),
            last_failure_at=now_ts - timedelta(seconds=10),
            locked_until=now_ts + timedelta(minutes=5),
        )
        for name in ("_METRICS_COUNT_CACHE", "_METRICS_CACHE"):
            cache = getattr(OpsView, name, None)
            if isinstance(cache, dict):
                cache.clear()

        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            res = self.client.get("/metrics", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")

        self.assertEqual(res.status_code, 200, msg=res.content)
        text = res.content.decode("utf-8")

        def _metric_value(text: str, metric: str) -> int:
            for line in (text or "").splitlines():
                if line.startswith(metric + " "):
                    try:
                        return int(float(line.split()[-1]))
                    except Exception:
                        return -1
            return -1

        self.assertEqual(_metric_value(text, "beacon_admin_login_lockout_active"), 1, msg=text)
        self.assertGreaterEqual(_metric_value(text, "beacon_admin_login_lockout_principals"), 1, msg=text)


class OpsAuditExportTest(TestCase):
    def test_audit_export_csv_contains_lease_events(self):
        from app.models import AlgorithmModel, LicenseState

        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            AlgorithmModel.objects.create(
                sort=0,
                code="alg-1",
                name="alg-1",
                object_count=0,
                object_str="",
                state=1,
                license_package="core",
            )
            LicenseState.objects.create(
                license_json='{"license_id":"TEST"}',
                license_id="TEST",
                cluster_id="cluster-1",
                not_before=timezone.now() - timedelta(minutes=5),
                not_after=timezone.now() + timedelta(days=1),
                max_active_controls=10,
                max_nodes=10,
                packages_json='["core"]',
                valid=True,
            )

            acquire = self.client.post(
                "/open/license/lease/acquire",
                data=json.dumps({"node_id": "node-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"}),
                content_type="application/json",
                REMOTE_ADDR="8.8.8.8",
                HTTP_X_BEACON_TOKEN="t1",
            )
            self.assertEqual(acquire.status_code, 200, msg=acquire.content)
            acquire_body = json.loads(acquire.content.decode("utf-8"))
            self.assertEqual(acquire_body.get("code"), 1000, msg=acquire_body)

            export = self.client.get(
                "/open/ops/audit/export?format=csv",
                REMOTE_ADDR="8.8.8.8",
                HTTP_X_BEACON_TOKEN="t1",
            )
            self.assertEqual(export.status_code, 200, msg=export.content)
            text = export.content.decode("utf-8")
            self.assertIn("event_type", text)
            self.assertIn("license.lease.acquire", text)


class AdminIndexAnalyzerInfoTest(TestCase):
    def setUp(self):
        session = self.client.session
        session["user"] = {"id": 1, "username": "admin"}
        session.save()

    def test_dashboard_includes_runtime_and_process_summary(self):
        process_rows = [
            {
                "process_index": 0,
                "analyzer_host": "http://a1:9993",
                "ok": True,
                "resource": {"cpuUsage": 0.22, "memoryUsage": 0.33, "currentControls": 2},
                "scheduler": {"runningControls": 2},
                "msg": "success",
            },
            {
                "process_index": 1,
                "analyzer_host": "http://a2:9994",
                "ok": True,
                "resource": {"cpuUsage": 0.41, "memoryUsage": 0.52, "currentControls": 1},
                "scheduler": {"runningControls": 1},
                "msg": "success",
            },
        ]
        os_info = {
            "machine_node": "edge-node-a",
            "system_name": "Linux",
            "os_cpu_used_rate": 0.185,
            "os_virtual_mem_used_rate": 0.42,
            "os_disk_used_rate": 0.61,
            "os_cpu_used_rate_str": "18.5% (32核)",
            "os_virtual_mem_used_rate_str": "42.0% (128.00GB)",
            "os_disk_used_rate_str": "61.0% (4.00TB)",
            "os_run_date_str": "3天6小时12分钟",
        }
        diagnostics = {
            "host": "edge-node-a",
            "system_name": "Linux",
            "os_release": "Ubuntu 22.04",
            "cpu": "Intel Xeon",
            "cpu_usage": "18.5%",
            "memory_usage": "42.0%",
            "disk_usage": "61.0%",
            "uptime": "3d 6h",
            "summary_ok": True,
        }
        with (
            mock.patch("app.views.api.OSSystem.get_os_info", return_value=os_info),
            mock.patch("app.views.OpsDiagnosticsView._load_diagnostics_summary", return_value=diagnostics),
            mock.patch(
                "app.views.api.g_analyzer.scheduler_info",
                return_value=(True, "ok", {"runningControls": 3, "queuedControls": 1}),
            ),
            mock.patch(
                "app.views.api.g_analyzer.device_info",
                return_value=(
                    True,
                    "ok",
                    {
                        "code": 1000,
                        "onnxProviders": ["CPUExecutionProvider", "CUDAExecutionProvider"],
                        "openvinoDevices": ["CPU", "GPU.0"],
                    },
                ),
            ),
            mock.patch("app.views.api._core_process_hosts", return_value=["http://a1:9993", "http://a2:9994"]),
            mock.patch("app.views.api._core_process_entry", side_effect=process_rows),
        ):
            response = self.client.get("/api/app-shell/dashboard")

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)
        runtime = payload["data"]["runtime"]
        self.assertEqual(runtime["host"], "edge-node-a")
        self.assertEqual(runtime["cpu"]["usage"], "18.5% (32核)")
        self.assertEqual(runtime["memory"]["usage"], "42.0% (128.00GB)")
        self.assertEqual(runtime["disk"]["usage"], "61.0% (4.00TB)")
        self.assertTrue(runtime["analyzer"]["ok"])
        self.assertEqual(runtime["processes"]["process_num"], 2)
        self.assertEqual(runtime["processes"]["rows"][0]["analyzer_host"], "http://a1:9993")
        self.assertEqual(runtime["processes"]["rows"][1]["resource"]["currentControls"], 1)
        self.assertEqual(payload["data"]["diagnostics"]["uptime"], "3d 6h")

    def test_dashboard_analyzer_scheduler_info_is_cached_and_uses_short_timeout(self):
        """
        工业场景：Analyzer 掉线/不通时，Admin 首页不应因为运维统计接口卡死。
        目标：
        - scheduler_info 使用短超时（而不是 60s）
        - 短时间内多次刷新使用缓存，避免每次都打 Analyzer
        """
        from app.utils.Analyzer import Analyzer

        analyzer = Analyzer("http://127.0.0.1:9999", openApiToken="t1")

        dummy = mock.Mock()
        dummy.status_code = 200
        dummy.json.return_value = {"code": 1000, "msg": "success", "stats": {"workerSize": 1}}

        captured_timeouts = []

        def fake_get(*args, **kwargs):
            url = kwargs.get("url")
            if not url and args:
                url = args[0]
            if str(url or "").endswith("/api/scheduler/info"):
                captured_timeouts.append(kwargs.get("timeout"))
            return dummy

        with mock.patch("app.views.api.g_analyzer", analyzer, create=True):
            with mock.patch("app.utils.Analyzer.requests.get", side_effect=fake_get):
                res1 = self.client.get("/api/app-shell/dashboard", REMOTE_ADDR="127.0.0.1")
                first_hit_count = len(captured_timeouts)
                res2 = self.client.get("/api/app-shell/dashboard", REMOTE_ADDR="127.0.0.1")
                second_hit_count = len(captured_timeouts)

        self.assertEqual(res1.status_code, 200, msg=res1.content)
        self.assertEqual(res2.status_code, 200, msg=res2.content)

        # Cached: second request within TTL should not add scheduler fetches.
        self.assertGreaterEqual(first_hit_count, 1)
        self.assertLessEqual(second_hit_count - first_hit_count, 1)

        timeout = captured_timeouts[0]
        self.assertIsNotNone(timeout)
        if isinstance(timeout, tuple):
            self.assertLessEqual(max(timeout), 3)
        else:
            self.assertLessEqual(float(timeout), 3)

    def test_dashboard_reuses_cached_device_license_and_resource_probes(self):
        """
        dashboard 聚合会同时访问 device/license/resource 等运维探测。
        短时间内再次打开 dashboard 时，不应重复触发这些重探测。
        """
        from app.utils.Analyzer import Analyzer

        analyzer = Analyzer("http://127.0.0.1:9999", openApiToken="t1")

        def _json_response(payload):
            resp = mock.Mock()
            resp.status_code = 200
            resp.json.return_value = payload
            return resp

        endpoint_hits = {"scheduler": 0, "device": 0, "license": 0, "resource": 0}

        def fake_get(*args, **kwargs):
            url = kwargs.get("url")
            if not url and args:
                url = args[0]
            url = str(url or "")
            if url.endswith("/api/scheduler/info"):
                endpoint_hits["scheduler"] += 1
                return _json_response({"code": 1000, "msg": "success", "stats": {"workerSize": 1}})
            if url.endswith("/api/device/info"):
                endpoint_hits["device"] += 1
                return _json_response(
                    {
                        "code": 1000,
                        "msg": "success",
                        "onnxProviders": ["CPUExecutionProvider"],
                        "openvinoDevices": ["CPU"],
                    }
                )
            if url.endswith("/api/license/info"):
                endpoint_hits["license"] += 1
                return _json_response(
                    {
                        "code": 1000,
                        "msg": "success",
                        "data": {
                            "ok": False,
                            "type": "machine",
                            "machine_code": "0123456789abcdef0123456789abcdef",
                        },
                    }
                )
            if url.endswith("/api/resource/info"):
                endpoint_hits["resource"] += 1
                return _json_response(
                    {
                        "code": 1000,
                        "msg": "success",
                        "cpuUsage": 0.1,
                        "memoryUsage": 0.2,
                        "currentControls": 1,
                    }
                )
            raise AssertionError(f"unexpected url: {url}")

        with mock.patch.dict(os.environ, {"BEACON_ANALYZER_HOSTS": "http://127.0.0.1:9999"}, clear=False):
            with mock.patch("app.views.api.g_analyzer", analyzer, create=True), mock.patch("app.views.AppShellView.g_config.licenseType", "machine"):
                with mock.patch("app.utils.Analyzer.requests.get", side_effect=fake_get):
                    res1 = self.client.get("/api/app-shell/dashboard", REMOTE_ADDR="127.0.0.1")
                    hits_after_first = dict(endpoint_hits)
                    res2 = self.client.get("/api/app-shell/dashboard", REMOTE_ADDR="127.0.0.1")
                    hits_after_second = dict(endpoint_hits)

        self.assertEqual(res1.status_code, 200, msg=res1.content)
        self.assertEqual(res2.status_code, 200, msg=res2.content)
        self.assertEqual(hits_after_first["device"], 1)
        self.assertEqual(hits_after_first["license"], 1)
        self.assertEqual(hits_after_first["resource"], 1)
        self.assertEqual(hits_after_second["device"], 1)
        self.assertEqual(hits_after_second["license"], 1)
        self.assertEqual(hits_after_second["resource"], 1)


class OpsMetricsCacheTtlEnvTest(TestCase):
    def setUp(self):
        session = self.client.session
        session["user"] = {"id": 1, "username": "admin"}
        session.save()

    def test_metrics_count_cache_ttl_defaults_and_clamps(self):
        from app.views import OpsView

        with mock.patch.dict(os.environ, {"BEACON_OPS_METRICS_COUNT_CACHE_TTL_SECONDS": ""}, clear=False):
            self.assertEqual(float(OpsView._metrics_count_cache_ttl_seconds()), 10.0)

        with mock.patch.dict(os.environ, {"BEACON_OPS_METRICS_COUNT_CACHE_TTL_SECONDS": "not-a-number"}, clear=False):
            self.assertEqual(float(OpsView._metrics_count_cache_ttl_seconds()), 10.0)

        with mock.patch.dict(os.environ, {"BEACON_OPS_METRICS_COUNT_CACHE_TTL_SECONDS": "-1"}, clear=False):
            self.assertEqual(float(OpsView._metrics_count_cache_ttl_seconds()), 0.0)

        with mock.patch.dict(os.environ, {"BEACON_OPS_METRICS_COUNT_CACHE_TTL_SECONDS": "999"}, clear=False):
            self.assertEqual(float(OpsView._metrics_count_cache_ttl_seconds()), 300.0)

    def test_dashboard_analyzer_cache_ttl_can_be_overridden_by_env(self):
        fake_analyzer = mock.Mock()
        fake_analyzer.scheduler_info.return_value = (True, "success", {"workerSize": 1})

        with mock.patch.dict(os.environ, {"BEACON_INDEX_ANALYZER_CACHE_TTL_SECONDS": "7"}, clear=False):
            with mock.patch("app.views.api.g_analyzer", fake_analyzer, create=True):
                res = self.client.get("/api/app-shell/dashboard", REMOTE_ADDR="127.0.0.1")

        self.assertEqual(res.status_code, 200, msg=res.content)
        fake_analyzer.scheduler_info.assert_called_once()
        kwargs = fake_analyzer.scheduler_info.call_args.kwargs or {}
        self.assertEqual(int(kwargs.get("timeout_seconds") or 0), 2)
        self.assertEqual(float(kwargs.get("cache_ttl_seconds") or 0), 7.0)


class TaskPlanFailClosedTest(SimpleTestCase):
    def test_invalid_days_mask_is_not_allowed(self):
        from app.utils.TaskPlanService import TaskPlanService

        plan = SimpleNamespace(days_mask="not-a-mask")

        self.assertFalse(TaskPlanService()._plan_allows_today(plan, datetime(2026, 7, 10, 12, 0)))

    def test_interval_datetime_subtraction_error_is_not_due(self):
        from app.utils.TaskPlanService import TaskPlanService

        plan = SimpleNamespace(interval_seconds=60)
        aware_now = datetime(2026, 7, 10, 12, 0, tzinfo=datetime_timezone.utc)
        naive_last_run = datetime(2026, 7, 10, 11, 58)

        self.assertFalse(TaskPlanService()._is_due_interval(plan, aware_now, naive_last_run))

    def test_daily_schedule_requires_real_time(self):
        from app.utils.TaskPlanService import TaskPlanService

        service = TaskPlanService()
        midnight = datetime(2026, 7, 10, 0, 0)
        for run_time in (None, "00:00", SimpleNamespace(hour=0, minute=0)):
            with self.subTest(run_time=repr(run_time)):
                self.assertFalse(service._is_due_daily(SimpleNamespace(run_time=run_time), midnight, None))

        self.assertTrue(
            service._is_due_daily(SimpleNamespace(run_time=datetime_time(0, 0)), midnight, None)
        )

    def test_zlm_media_probe_marks_transport_and_api_errors_unknown(self):
        from app.utils.ZLMediaKit import ZLMediaKit

        config = SimpleNamespace(mediaHttpHost="http://zlm", mediaSecret="secret")
        zlm = ZLMediaKit(config)
        cases = (
            (503, {}, False, False),
            (200, {"code": -1}, False, False),
            (200, {"code": -500}, True, False),
            (200, {"code": 0, "tracks": []}, True, False),
        )
        for status_code, payload, expected_probe_ok, expected_ret in cases:
            with self.subTest(status_code=status_code, payload=payload):
                response = mock.Mock(status_code=status_code)
                response.json.return_value = payload
                with mock.patch("app.utils.ZLMediaKit._requests_get", return_value=response):
                    info = zlm.getMediaInfo("live", "camera-1")

                self.assertIs(info.get("probe_ok"), expected_probe_ok)
                self.assertIs(info.get("ret"), expected_ret)

    def test_zlm_delete_proxy_status_distinguishes_removed_absent_and_unknown(self):
        from app.utils.ZLMediaKit import ZLMediaKit

        config = SimpleNamespace(mediaHttpHost="http://zlm", mediaSecret="secret")
        zlm = ZLMediaKit(config)
        cases = (
            (200, {"code": 0, "data": {"flag": True}}, "removed"),
            (200, {"code": 0, "data": {"flag": False}}, "confirmed_absent"),
            (503, {}, "unknown"),
            (200, {"code": -1, "data": {"flag": True}}, "unknown"),
            (200, {"code": 0, "data": {}}, "unknown"),
            (200, {"code": 0, "data": {"flag": 1}}, "unknown"),
        )

        for status_code, payload, expected_status in cases:
            with self.subTest(status_code=status_code, payload=payload):
                response = mock.Mock(status_code=status_code)
                response.json.return_value = payload
                with mock.patch("app.utils.ZLMediaKit._requests_get", return_value=response):
                    status, message = zlm.del_stream_proxy_status("live", "camera-1")

                self.assertEqual(status, expected_status)
                self.assertIsInstance(message, str)

    def test_zlm_delete_proxy_status_treats_json_and_transport_errors_as_unknown(self):
        from app.utils.ZLMediaKit import ZLMediaKit

        config = SimpleNamespace(mediaHttpHost="http://zlm", mediaSecret="secret")
        zlm = ZLMediaKit(config)

        response = mock.Mock(status_code=200)
        response.json.side_effect = ValueError("invalid json")
        with mock.patch("app.utils.ZLMediaKit._requests_get", return_value=response):
            self.assertEqual(
                zlm.del_stream_proxy_status("live", "camera-1")[0],
                "unknown",
            )

        with mock.patch(
            "app.utils.ZLMediaKit._requests_get",
            side_effect=ConnectionError("zlm unavailable"),
        ):
            self.assertEqual(
                zlm.del_stream_proxy_status("live", "camera-1")[0],
                "unknown",
            )

    def test_stop_forward_uses_real_zlm_delete_contract_and_fails_closed(self):
        from app.utils.ZLMediaKit import ZLMediaKit
        from app.views import ViewsBase

        config = SimpleNamespace(mediaHttpHost="http://zlm", mediaSecret="secret")
        zlm = ZLMediaKit(config)
        cases = (
            (200, {"code": 0, "data": {"flag": True}}, True),
            (200, {"code": 0, "data": {"flag": False}}, True),
            (503, {}, False),
            (200, {"code": -1, "data": {"flag": True}}, False),
            (200, {"code": 0, "data": {}}, False),
            (200, {"code": 0, "data": {"flag": 1}}, False),
        )

        for status_code, payload, expected_ok in cases:
            with self.subTest(status_code=status_code, payload=payload):
                stream = SimpleNamespace(
                    app="live",
                    name="camera-1",
                    forward_state=1,
                    pull_stream_type=1,
                    pull_stream_url="rtsp://camera",
                    save=mock.Mock(),
                )
                response = mock.Mock(status_code=status_code)
                response.json.return_value = payload
                with (
                    mock.patch.object(ViewsBase, "g_zlm", zlm),
                    mock.patch("app.utils.ZLMediaKit._requests_get", return_value=response),
                ):
                    ok, message = ViewsBase.stop_forward_for_stream(stream)

                self.assertIs(ok, expected_ok)
                self.assertIsInstance(message, str)
                if expected_ok:
                    self.assertEqual(stream.forward_state, 0)
                    stream.save.assert_called_once_with()
                else:
                    self.assertEqual(stream.forward_state, 1)
                    stream.save.assert_not_called()

    def test_stop_forward_real_zlm_chain_keeps_state_on_parse_and_transport_errors(self):
        from app.utils.ZLMediaKit import ZLMediaKit
        from app.views import ViewsBase

        config = SimpleNamespace(mediaHttpHost="http://zlm", mediaSecret="secret")
        zlm = ZLMediaKit(config)
        invalid_json_response = mock.Mock(status_code=200)
        invalid_json_response.json.side_effect = ValueError("invalid json")

        for behavior in (invalid_json_response, ConnectionError("zlm unavailable")):
            with self.subTest(behavior=repr(behavior)):
                stream = SimpleNamespace(
                    app="live",
                    name="camera-1",
                    forward_state=1,
                    pull_stream_type=1,
                    pull_stream_url="rtsp://camera",
                    save=mock.Mock(),
                )
                patch_kwargs = (
                    {"return_value": behavior}
                    if not isinstance(behavior, Exception)
                    else {"side_effect": behavior}
                )
                with (
                    mock.patch.object(ViewsBase, "g_zlm", zlm),
                    mock.patch("app.utils.ZLMediaKit._requests_get", **patch_kwargs),
                ):
                    ok, message = ViewsBase.stop_forward_for_stream(stream)

                self.assertFalse(ok)
                self.assertIsInstance(message, str)
                self.assertEqual(stream.forward_state, 1)
                stream.save.assert_not_called()

    def test_unknown_zlm_delete_does_not_stop_gb_provider(self):
        from app.utils.ZLMediaKit import ZLMediaKit
        from app.views import ViewsBase

        zlm = ZLMediaKit(SimpleNamespace(mediaHttpHost="http://zlm", mediaSecret="secret"))
        provider = mock.Mock()
        stream = SimpleNamespace(
            app="live",
            name="camera-1",
            forward_state=1,
            pull_stream_type=21,
            pull_stream_url="gb28181://device-1@channel-1",
            save=mock.Mock(),
        )
        response = mock.Mock(status_code=200)
        response.json.return_value = {"code": -1, "data": {"flag": True}}

        with (
            mock.patch.object(ViewsBase, "g_zlm", zlm),
            mock.patch.object(ViewsBase, "g_gb28181_provider", provider),
            mock.patch("app.utils.ZLMediaKit._requests_get", return_value=response),
        ):
            ok, _message = ViewsBase.stop_forward_for_stream(stream)

        self.assertFalse(ok)
        self.assertEqual(stream.forward_state, 1)
        stream.save.assert_not_called()
        provider.stop_play.assert_not_called()

    def test_legacy_delete_proxy_bool_only_reports_actual_removal(self):
        from app.utils.ZLMediaKit import ZLMediaKit

        config = SimpleNamespace(mediaHttpHost="http://zlm", mediaSecret="secret")
        zlm = ZLMediaKit(config)
        for flag, expected in ((True, True), (False, False)):
            with self.subTest(flag=flag):
                response = mock.Mock(status_code=200)
                response.json.return_value = {"code": 0, "data": {"flag": flag}}
                with mock.patch("app.utils.ZLMediaKit._requests_get", return_value=response):
                    self.assertIs(zlm.delStreamProxy("live", "camera-1"), expected)

    def test_unknown_probe_never_restarts_stream(self):
        from app.utils import TaskPlanService as task_plan_service
        from app.views import ViewsBase

        stream = SimpleNamespace(app="live", name="camera-1")
        queryset = mock.Mock()
        queryset.order_by.return_value = queryset
        queryset.iterator.return_value = [stream]

        for probe_behavior in (
            ConnectionError("zlm unavailable"),
            None,
            {"ret": False, "probe_ok": False},
        ):
            with self.subTest(probe_behavior=repr(probe_behavior)):
                zlm = mock.Mock()
                if isinstance(probe_behavior, Exception):
                    zlm.getMediaInfo.side_effect = probe_behavior
                else:
                    zlm.getMediaInfo.return_value = probe_behavior
                stop_forward = mock.Mock()
                start_forward = mock.Mock()

                with (
                    mock.patch("app.models.Stream.objects.filter", return_value=queryset),
                    mock.patch.object(ViewsBase, "g_zlm", zlm),
                    mock.patch.object(ViewsBase, "stop_forward_for_stream", stop_forward),
                    mock.patch.object(ViewsBase, "start_forward_for_stream", start_forward),
                ):
                    with self.assertRaisesRegex(RuntimeError, r"live/camera-1.*probe.*unknown"):
                        task_plan_service._scan_offline_streams()

                stop_forward.assert_not_called()
                start_forward.assert_not_called()

    def test_tick_records_unknown_scan_as_failure(self):
        from app.utils import TaskPlanService as task_plan_service

        now = datetime(2026, 7, 10, 12, 0)
        plan = SimpleNamespace(
            enabled=True,
            days_mask=127,
            schedule_type="interval",
            interval_seconds=60,
            last_run_at=None,
            task_type="scan_offline_streams",
            target_codes="",
            save=mock.Mock(),
        )
        queryset = mock.Mock()
        queryset.order_by.return_value = [plan]

        with (
            mock.patch.object(task_plan_service.TaskPlan.objects, "all", return_value=queryset),
            mock.patch.object(
                task_plan_service,
                "_scan_offline_streams",
                side_effect=task_plan_service.OfflineStreamScanError(
                    "live/camera-1 probe is unknown: zlm unavailable"
                ),
            ),
        ):
            try:
                task_plan_service.TaskPlanService().tick_once(now)
            except RuntimeError as exc:
                self.fail(f"tick_once leaked scan failure instead of recording it: {exc}")

        self.assertEqual(plan.last_result_code, 0)
        self.assertIn("probe is unknown", plan.last_result_msg)
        plan.save.assert_called_once()

    def test_unrelated_runtime_error_is_not_converted_to_scan_failure(self):
        from app.utils import TaskPlanService as task_plan_service

        plan = SimpleNamespace(task_type="scan_offline_streams", target_codes="")
        with mock.patch.object(
            task_plan_service,
            "_scan_offline_streams",
            side_effect=RuntimeError("unexpected programming error"),
        ):
            with self.assertRaisesRegex(RuntimeError, "unexpected programming error"):
                task_plan_service.TaskPlanService()._execute_plan(plan)

    def test_stop_failure_prevents_forward_restart(self):
        from app.utils import TaskPlanService as task_plan_service

        restart_forward = getattr(task_plan_service, "_restart_stream_forward", None)
        self.assertIsNotNone(restart_forward, "strict restart helper is required")
        stream = SimpleNamespace(app="live", name="camera-1")

        for stop_result in (RuntimeError("stop exploded"), (False, "stop rejected")):
            with self.subTest(stop_result=repr(stop_result)):
                stop_forward = mock.Mock()
                if isinstance(stop_result, Exception):
                    stop_forward.side_effect = stop_result
                else:
                    stop_forward.return_value = stop_result
                start_forward = mock.Mock(return_value=(True, "started"))

                ok, message = restart_forward(
                    stream,
                    stop_forward_for_stream=stop_forward,
                    start_forward_for_stream=start_forward,
                )

                self.assertFalse(ok)
                self.assertIn("stop", message.lower())
                start_forward.assert_not_called()

    def test_confirmed_offline_stream_is_restarted(self):
        from app.utils import TaskPlanService as task_plan_service
        from app.views import ViewsBase

        stream = SimpleNamespace(app="live", name="camera-1")
        queryset = mock.Mock()
        queryset.order_by.return_value = queryset
        queryset.iterator.return_value = [stream]
        zlm = SimpleNamespace(
            mediaServerState=True,
            getMediaInfo=mock.Mock(return_value={"ret": False, "probe_ok": True}),
        )
        stop_forward = mock.Mock(return_value=(True, "stopped"))
        start_forward = mock.Mock(return_value=(True, "started"))

        with (
            mock.patch("app.models.Stream.objects.filter", return_value=queryset),
            mock.patch.object(ViewsBase, "g_zlm", zlm),
            mock.patch.object(ViewsBase, "stop_forward_for_stream", stop_forward),
            mock.patch.object(ViewsBase, "start_forward_for_stream", start_forward),
        ):
            result = task_plan_service._scan_offline_streams()

        self.assertEqual(result, (1, 1))
        stop_forward.assert_called_once_with(stream)
        start_forward.assert_called_once_with(stream)
