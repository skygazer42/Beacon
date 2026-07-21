import json
import os
from datetime import timedelta
from typing import Optional
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from app.models import AlgorithmModel, LicenseLease, LicenseState


class LicenseLeaseApiTest(TestCase):
    def setUp(self):
        super().setUp()
        self._env_backup = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env_backup)
        super().tearDown()

    def _post_json(self, path: str, payload: dict, *, token: Optional[str] = None):
        headers = {}
        if token:
            headers["HTTP_X_BEACON_TOKEN"] = token
        return self.client.post(path, data=json.dumps(payload), content_type="application/json", **headers)

    def _get(self, path: str, *, token: Optional[str] = None):
        headers = {}
        if token:
            headers["HTTP_X_BEACON_TOKEN"] = token
        return self.client.get(path, **headers)

    def _seed_algorithm_and_license(
        self,
        *,
        algorithm_code: str = "alg-1",
        package: str = "core",
        packages_json: str = '["core"]',
        package_limits_json: str = "{}",
        max_active_controls: int = 10,
        max_nodes: int = 10,
        valid: bool = True,
        not_before=None,
        not_after=None,
        edition: str = "",
        thread_priority_policy: Optional[dict] = None,
    ):
        AlgorithmModel.objects.create(
            sort=0,
            code=algorithm_code,
            name=algorithm_code,
            object_count=0,
            object_str="",
            state=1,
            license_package=package,
        )
        if not_before is None:
            not_before = timezone.now() - timedelta(minutes=5)
        if not_after is None:
            not_after = timezone.now() + timedelta(days=1)
        license_payload = {"license_id": "TEST"}
        if edition:
            license_payload["edition"] = edition
        if thread_priority_policy is not None:
            license_payload["thread_priority_policy"] = thread_priority_policy
        return LicenseState.objects.create(
            license_json=json.dumps(license_payload, ensure_ascii=False),
            license_id="TEST",
            cluster_id="cluster-1",
            not_before=not_before,
            not_after=not_after,
            max_active_controls=max_active_controls,
            max_nodes=max_nodes,
            packages_json=packages_json,
            package_limits_json=package_limits_json,
            valid=valid,
        )

    def test_app_shell_reports_license_usage_and_active_leases(self):
        session = self.client.session
        session["user"] = {"id": 1, "username": "license-admin"}
        session.save()
        LicenseState.objects.create(
            license_json='{"license_id":"LIC-1"}',
            license_id="LIC-1",
            customer="City Lab",
            cluster_id="cluster-a",
            max_active_controls=8,
            max_nodes=3,
            packages_json='["core","ppe"]',
            package_limits_json='{"ppe":{"max_active_controls":2}}',
            valid=True,
        )
        LicenseLease.objects.create(
            lease_id="lease-001",
            node_id="node-a",
            stream_code="cam-001",
            control_code="ctrl-001",
            algorithm_code="alg-001",
            package="ppe",
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        with (
            mock.patch(
                "app.views.AppShellView.api_view.g_license.check",
                return_value={
                    "ok": True,
                    "type": "pool",
                    "extra": {"license_id": "LIC-1", "cluster_id": "cluster-a"},
                },
            ),
            mock.patch("app.views.AppShellView.g_config.licenseType", "pool"),
        ):
            response = self.client.get("/api/app-shell/license")

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)
        self.assertEqual(payload["data"]["state"]["license_id"], "LIC-1")
        self.assertEqual(payload["data"]["usage"]["package_usage"]["ppe"], 1)
        self.assertEqual(payload["data"]["leases"][0]["lease_id"], "lease-001")
        self.assertEqual(payload["data"]["info"]["type"], "pool")

    def test_algorithm_form_persists_license_package(self):
        session = self.client.session
        session["user"] = {"id": 1, "username": "license-admin"}
        session.save()

        response = self.client.post(
            "/algorithm/add",
            data={
                "handle": "add",
                "code": "alg_api_package_1",
                "name": "ALG API PACKAGE 1",
                "algorithm_type": "0",
                "basic_source": "api",
                "api_url": "http://example.com/infer",
                "object_str": "",
                "max_control_count": "0",
                "model_concurrency": "1",
                "remark": "",
                "license_package": "ppe",
            },
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        algorithm = AlgorithmModel.objects.get(code="alg_api_package_1")
        self.assertEqual(algorithm.license_package, "ppe")

    def test_license_lease_ttl_seconds_clamps_and_defaults_invalid_values(self):
        from app.views import api as api_view

        self.assertEqual(api_view._license_lease_ttl_seconds("bad"), 120)
        self.assertEqual(api_view._license_lease_ttl_seconds("1"), 30)
        self.assertEqual(api_view._license_lease_ttl_seconds("9999"), 600)

    def test_acquire_requires_token_when_configured(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"

        resp = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_acquire_fails_without_valid_license(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"

        resp = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 0)
        self.assertEqual(data.get("msg"), "license_invalid")

    def test_acquire_ok_creates_lease(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"

        self._seed_algorithm_and_license(max_active_controls=2, max_nodes=1)

        resp = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "stream-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 1000)
        self.assertEqual(data.get("msg"), "success")
        self.assertTrue(data.get("data", {}).get("lease_id"))
        lease = LicenseLease.objects.filter(lease_id=data.get("data", {}).get("lease_id")).first()
        self.assertIsNotNone(lease)
        self.assertEqual(getattr(lease, "stream_code", ""), "stream-1")

    def test_acquire_includes_thread_priority_for_first_n_active_streams(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license(
            edition="ordinary",
            thread_priority_policy={"enabled": True, "first_n_active_streams": 2, "nice_value": -4},
            max_active_controls=10,
            max_nodes=10,
        )

        first = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "stream-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        first_data = json.loads(first.content.decode("utf-8"))
        self.assertEqual(first_data.get("code"), 1000)
        self.assertEqual(
            first_data.get("data", {}).get("thread_priority"),
            {"enabled": True, "stream_rank": 1, "first_n_active_streams": 2, "nice_value": -4},
        )

        second = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "stream-2", "control_code": "ctrl-2", "algorithm_code": "alg-1"},
            token="test-token",
        )
        second_data = json.loads(second.content.decode("utf-8"))
        self.assertEqual(second_data.get("code"), 1000)
        self.assertEqual(
            second_data.get("data", {}).get("thread_priority"),
            {"enabled": True, "stream_rank": 2, "first_n_active_streams": 2, "nice_value": -4},
        )

        third = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "stream-3", "control_code": "ctrl-3", "algorithm_code": "alg-1"},
            token="test-token",
        )
        third_data = json.loads(third.content.decode("utf-8"))
        self.assertEqual(third_data.get("code"), 1000)
        self.assertEqual(
            third_data.get("data", {}).get("thread_priority"),
            {"enabled": False, "stream_rank": 3, "first_n_active_streams": 2, "nice_value": 0},
        )

    def test_acquire_respects_not_before(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license(
            not_before=timezone.now() + timedelta(hours=1),
            not_after=timezone.now() + timedelta(days=1),
        )

        resp = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 0)
        self.assertEqual(data.get("msg"), "license_not_active")

    def test_renew_revalidates_license_state(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license()

        acquire = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        data = json.loads(acquire.content.decode("utf-8"))
        lease_id = data.get("data", {}).get("lease_id")
        self.assertTrue(lease_id)

        # Newest state becomes invalid -> renew must fail.
        LicenseState.objects.create(valid=False)

        renew = self._post_json(
            "/open/license/lease/renew",
            {"lease_id": lease_id, "ttl_seconds": 120},
            token="test-token",
        )
        self.assertEqual(renew.status_code, 200)
        renew_data = json.loads(renew.content.decode("utf-8"))
        self.assertEqual(renew_data.get("code"), 0)
        self.assertEqual(renew_data.get("msg"), "license_invalid")

    def test_renew_denies_when_package_removed(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license(packages_json='["core"]')

        acquire = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        data = json.loads(acquire.content.decode("utf-8"))
        lease_id = data.get("data", {}).get("lease_id")
        self.assertTrue(lease_id)

        # Latest state removes 'core' package -> renew must be denied.
        LicenseState.objects.create(
            valid=True,
            not_before=timezone.now() - timedelta(minutes=1),
            not_after=timezone.now() + timedelta(days=1),
            packages_json='["other"]',
        )

        renew = self._post_json(
            "/open/license/lease/renew",
            {"lease_id": lease_id, "ttl_seconds": 120},
            token="test-token",
        )
        self.assertEqual(renew.status_code, 200)
        renew_data = json.loads(renew.content.decode("utf-8"))
        self.assertEqual(renew_data.get("code"), 0)
        self.assertEqual(renew_data.get("msg"), "license_package_denied")

    def test_renew_denies_when_latest_state_is_not_yet_active(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license()

        acquire = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        data = json.loads(acquire.content.decode("utf-8"))
        lease_id = data.get("data", {}).get("lease_id")
        self.assertTrue(lease_id)

        LicenseState.objects.create(
            valid=True,
            not_before=timezone.now() + timedelta(minutes=5),
            not_after=timezone.now() + timedelta(days=1),
            packages_json='["core"]',
        )

        renew = self._post_json(
            "/open/license/lease/renew",
            {"lease_id": lease_id, "ttl_seconds": 120},
            token="test-token",
        )
        self.assertEqual(renew.status_code, 200)
        renew_data = json.loads(renew.content.decode("utf-8"))
        self.assertEqual(renew_data.get("code"), 0)
        self.assertEqual(renew_data.get("msg"), "license_not_active")

    def test_release_is_idempotent(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license()

        acquire = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        data = json.loads(acquire.content.decode("utf-8"))
        lease_id = data.get("data", {}).get("lease_id")
        self.assertTrue(lease_id)

        release1 = self._post_json("/open/license/lease/release", {"lease_id": lease_id}, token="test-token")
        self.assertEqual(release1.status_code, 200)
        rel1_data = json.loads(release1.content.decode("utf-8"))
        self.assertEqual(rel1_data.get("code"), 1000)

        lease = LicenseLease.objects.filter(lease_id=lease_id).first()
        self.assertIsNotNone(lease)
        self.assertIsNotNone(getattr(lease, "released_at"))

        release2 = self._post_json("/open/license/lease/release", {"lease_id": lease_id}, token="test-token")
        self.assertEqual(release2.status_code, 200)
        rel2_data = json.loads(release2.content.decode("utf-8"))
        self.assertEqual(rel2_data.get("code"), 1000)

    def test_renew_recomputes_thread_priority_after_release(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license(
            edition="ordinary",
            thread_priority_policy={"enabled": True, "first_n_active_streams": 1, "nice_value": -3},
            max_active_controls=10,
            max_nodes=10,
        )

        first = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "stream-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        first_data = json.loads(first.content.decode("utf-8"))
        self.assertEqual(first_data.get("code"), 1000)
        first_lease_id = first_data.get("data", {}).get("lease_id")

        second = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "stream-2", "control_code": "ctrl-2", "algorithm_code": "alg-1"},
            token="test-token",
        )
        second_data = json.loads(second.content.decode("utf-8"))
        self.assertEqual(second_data.get("code"), 1000)
        second_lease_id = second_data.get("data", {}).get("lease_id")
        self.assertEqual(
            second_data.get("data", {}).get("thread_priority"),
            {"enabled": False, "stream_rank": 2, "first_n_active_streams": 1, "nice_value": 0},
        )

        release = self._post_json("/open/license/lease/release", {"lease_id": first_lease_id}, token="test-token")
        release_data = json.loads(release.content.decode("utf-8"))
        self.assertEqual(release_data.get("code"), 1000)

        renew = self._post_json(
            "/open/license/lease/renew",
            {"lease_id": second_lease_id, "ttl_seconds": 120},
            token="test-token",
        )
        renew_data = json.loads(renew.content.decode("utf-8"))
        self.assertEqual(renew_data.get("code"), 1000)
        self.assertEqual(
            renew_data.get("data", {}).get("thread_priority"),
            {"enabled": True, "stream_rank": 1, "first_n_active_streams": 1, "nice_value": -3},
        )

    def test_idempotent_acquire_stream_change_recomputes_thread_priority_rank(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license(
            edition="ordinary",
            thread_priority_policy={"enabled": True, "first_n_active_streams": 1, "nice_value": -3},
            max_active_controls=10,
            max_nodes=10,
        )

        first = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "stream-1", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        first_data = json.loads(first.content.decode("utf-8"))
        self.assertEqual(first_data.get("code"), 1000)
        first_lease_id = first_data.get("data", {}).get("lease_id")

        second = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "stream-2", "control_code": "ctrl-2", "algorithm_code": "alg-1"},
            token="test-token",
        )
        second_data = json.loads(second.content.decode("utf-8"))
        self.assertEqual(second_data.get("code"), 1000)
        second_lease_id = second_data.get("data", {}).get("lease_id")

        switched = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "stream-3", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        switched_data = json.loads(switched.content.decode("utf-8"))
        self.assertEqual(switched_data.get("code"), 1000)
        self.assertEqual(switched_data.get("data", {}).get("lease_id"), first_lease_id)
        self.assertEqual(
            switched_data.get("data", {}).get("thread_priority"),
            {"enabled": False, "stream_rank": 2, "first_n_active_streams": 1, "nice_value": 0},
        )

        lease = LicenseLease.objects.filter(lease_id=first_lease_id, released_at__isnull=True).first()
        self.assertIsNotNone(lease)
        self.assertEqual(getattr(lease, "stream_code", ""), "stream-3")

        renew = self._post_json(
            "/open/license/lease/renew",
            {"lease_id": second_lease_id, "ttl_seconds": 120},
            token="test-token",
        )
        renew_data = json.loads(renew.content.decode("utf-8"))
        self.assertEqual(renew_data.get("code"), 1000)
        self.assertEqual(
            renew_data.get("data", {}).get("thread_priority"),
            {"enabled": True, "stream_rank": 1, "first_n_active_streams": 1, "nice_value": -3},
        )

    def test_usage_counts_active_controls_and_nodes(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license(max_active_controls=10, max_nodes=2)

        for i in range(2):
            resp = self._post_json(
                "/open/license/lease/acquire",
                {"node_id": "node-1", "stream_code": "stream-a", "control_code": f"ctrl-{i}", "algorithm_code": "alg-1"},
                token="test-token",
            )
            data = json.loads(resp.content.decode("utf-8"))
            self.assertEqual(data.get("code"), 1000)

        resp = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-2", "stream_code": "stream-b", "control_code": "ctrl-2", "algorithm_code": "alg-1"},
            token="test-token",
        )
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 1000)

        usage = self._get("/open/license/usage", token="test-token")
        self.assertEqual(usage.status_code, 200)
        usage_data = json.loads(usage.content.decode("utf-8"))
        self.assertEqual(usage_data.get("code"), 1000)
        self.assertEqual(usage_data.get("data", {}).get("active_controls"), 3)
        self.assertEqual(usage_data.get("data", {}).get("active_streams"), 2)
        self.assertEqual(usage_data.get("data", {}).get("active_nodes"), 2)

    def test_same_camera_multiple_controls_share_one_license_seat(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license(max_active_controls=1, max_nodes=10)

        ok1 = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-001", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        ok1_data = json.loads(ok1.content.decode("utf-8"))
        self.assertEqual(ok1_data.get("code"), 1000)

        ok2 = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-001", "control_code": "ctrl-2", "algorithm_code": "alg-1"},
            token="test-token",
        )
        ok2_data = json.loads(ok2.content.decode("utf-8"))
        self.assertEqual(ok2_data.get("code"), 1000)

        usage = self._get("/open/license/usage", token="test-token")
        usage_data = json.loads(usage.content.decode("utf-8"))
        self.assertEqual(usage_data.get("data", {}).get("active_controls"), 2)
        self.assertEqual(usage_data.get("data", {}).get("active_streams"), 1)

    def test_different_cameras_still_consume_separate_license_seats(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license(max_active_controls=1, max_nodes=10)

        ok1 = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-001", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        ok1_data = json.loads(ok1.content.decode("utf-8"))
        self.assertEqual(ok1_data.get("code"), 1000)

        denied = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-002", "control_code": "ctrl-2", "algorithm_code": "alg-1"},
            token="test-token",
        )
        denied_data = json.loads(denied.content.decode("utf-8"))
        self.assertEqual(denied_data.get("code"), 0)
        self.assertEqual(denied_data.get("msg"), "license_over_quota_controls")

    def test_acquire_denies_when_package_over_quota(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"

        self._seed_algorithm_and_license(
            algorithm_code="alg-ppe",
            package="ppe",
            packages_json='["core","ppe"]',
            package_limits_json='{"ppe":{"max_active_controls":1}}',
            max_active_controls=10,
            max_nodes=10,
        )

        ok1 = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-ppe", "control_code": "ctrl-1", "algorithm_code": "alg-ppe"},
            token="test-token",
        )
        ok1_data = json.loads(ok1.content.decode("utf-8"))
        self.assertEqual(ok1_data.get("code"), 1000)

        denied = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-ppe-2", "control_code": "ctrl-2", "algorithm_code": "alg-ppe"},
            token="test-token",
        )
        denied_data = json.loads(denied.content.decode("utf-8"))
        self.assertEqual(denied_data.get("code"), 0)
        self.assertEqual(denied_data.get("msg"), "license_over_quota_package")

    def test_same_camera_same_package_shares_package_quota(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"

        self._seed_algorithm_and_license(
            algorithm_code="alg-ppe",
            package="ppe",
            packages_json='["core","ppe"]',
            package_limits_json='{"ppe":{"max_active_controls":1}}',
            max_active_controls=10,
            max_nodes=10,
        )

        ok1 = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-001", "control_code": "ctrl-1", "algorithm_code": "alg-ppe"},
            token="test-token",
        )
        ok1_data = json.loads(ok1.content.decode("utf-8"))
        self.assertEqual(ok1_data.get("code"), 1000)

        ok2 = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-001", "control_code": "ctrl-2", "algorithm_code": "alg-ppe"},
            token="test-token",
        )
        ok2_data = json.loads(ok2.content.decode("utf-8"))
        self.assertEqual(ok2_data.get("code"), 1000)

    def test_idempotent_acquire_package_change_does_not_bypass_quota(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"

        self._seed_algorithm_and_license(
            algorithm_code="alg-core",
            package="core",
            packages_json='["core","ppe"]',
            package_limits_json='{"ppe":{"max_active_controls":1}}',
            max_active_controls=10,
            max_nodes=10,
        )
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-ppe",
            name="alg-ppe",
            object_count=0,
            object_str="",
            state=1,
            license_package="ppe",
        )

        # Fill ppe quota with ctrl-1
        ok1 = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-001", "control_code": "ctrl-1", "algorithm_code": "alg-ppe"},
            token="test-token",
        )
        ok1_data = json.loads(ok1.content.decode("utf-8"))
        self.assertEqual(ok1_data.get("code"), 1000)

        # ctrl-2 starts with core (ok)
        ok2 = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-002", "control_code": "ctrl-2", "algorithm_code": "alg-core"},
            token="test-token",
        )
        ok2_data = json.loads(ok2.content.decode("utf-8"))
        self.assertEqual(ok2_data.get("code"), 1000)

        # idempotent acquire tries to switch ctrl-2 from core -> ppe, but ppe is full
        denied = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-002", "control_code": "ctrl-2", "algorithm_code": "alg-ppe"},
            token="test-token",
        )
        denied_data = json.loads(denied.content.decode("utf-8"))
        self.assertEqual(denied_data.get("code"), 0)
        self.assertEqual(denied_data.get("msg"), "license_over_quota_package")

    def test_idempotent_acquire_stream_change_does_not_bypass_control_quota(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license(max_active_controls=1, max_nodes=10)

        first = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-001", "control_code": "ctrl-1", "algorithm_code": "alg-1"},
            token="test-token",
        )
        first_data = json.loads(first.content.decode("utf-8"))
        self.assertEqual(first_data.get("code"), 1000)

        shared = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-001", "control_code": "ctrl-2", "algorithm_code": "alg-1"},
            token="test-token",
        )
        shared_data = json.loads(shared.content.decode("utf-8"))
        self.assertEqual(shared_data.get("code"), 1000)

        denied = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-002", "control_code": "ctrl-2", "algorithm_code": "alg-1"},
            token="test-token",
        )
        denied_data = json.loads(denied.content.decode("utf-8"))
        self.assertEqual(denied_data.get("code"), 0)
        self.assertEqual(denied_data.get("msg"), "license_over_quota_controls")

        lease = LicenseLease.objects.filter(node_id="node-1", control_code="ctrl-2", released_at__isnull=True).first()
        self.assertIsNotNone(lease)
        self.assertEqual(getattr(lease, "stream_code", ""), "cam-001")

    def test_usage_includes_package_limits_and_usage(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"

        self._seed_algorithm_and_license(
            algorithm_code="alg-ppe",
            package="ppe",
            packages_json='["core","ppe"]',
            package_limits_json='{"ppe":{"max_active_controls":2}}',
            max_active_controls=10,
            max_nodes=10,
        )

        resp = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "stream_code": "cam-001", "control_code": "ctrl-1", "algorithm_code": "alg-ppe"},
            token="test-token",
        )
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 1000)

        usage = self._get("/open/license/usage", token="test-token")
        self.assertEqual(usage.status_code, 200)
        usage_data = json.loads(usage.content.decode("utf-8"))
        self.assertEqual(usage_data.get("code"), 1000)

        limits = usage_data.get("data", {}).get("package_limits")
        self.assertEqual(limits, {"ppe": {"max_active_controls": 2}})

        usage_by_pkg = usage_data.get("data", {}).get("package_usage")
        self.assertEqual(usage_by_pkg.get("ppe"), 1)

    def test_usage_includes_edition_and_thread_priority_policy(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"
        self._seed_algorithm_and_license(
            edition="ordinary",
            thread_priority_policy={"enabled": True, "first_n_active_streams": 2, "nice_value": -6},
            max_active_controls=10,
            max_nodes=10,
        )

        usage = self._get("/open/license/usage", token="test-token")
        usage_data = json.loads(usage.content.decode("utf-8"))
        self.assertEqual(usage_data.get("code"), 1000)
        self.assertEqual(usage_data.get("data", {}).get("edition"), "ordinary")
        self.assertEqual(
            usage_data.get("data", {}).get("thread_priority_policy"),
            {"enabled": True, "first_n_active_streams": 2, "nice_value": -6},
        )

    def test_acquire_builtin_algorithm_without_db_row_uses_builtin_package_mapping(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"

        # 仅创建 license 状态，不创建 AlgorithmModel 行：LM 需要能识别 Analyzer 内置算法的 SKU 包
        LicenseState.objects.create(
            license_json='{"license_id":"TEST"}',
            license_id="TEST",
            cluster_id="cluster-1",
            not_before=timezone.now() - timedelta(minutes=5),
            not_after=timezone.now() + timedelta(days=1),
            max_active_controls=10,
            max_nodes=10,
            packages_json='["core","ppe"]',
            package_limits_json="{}",
            valid=True,
        )

        resp = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "control_code": "ctrl-1", "algorithm_code": "ov_yolov11n_safehat"},
            token="test-token",
        )
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 1000)

        lease = LicenseLease.objects.filter(control_code="ctrl-1").first()
        self.assertIsNotNone(lease)
        self.assertEqual(getattr(lease, "package"), "ppe")

    def test_acquire_builtin_algorithm_denied_when_package_not_in_license_packages(self):
        os.environ["BEACON_OPEN_API_TOKEN"] = "test-token"

        LicenseState.objects.create(
            license_json='{"license_id":"TEST"}',
            license_id="TEST",
            cluster_id="cluster-1",
            not_before=timezone.now() - timedelta(minutes=5),
            not_after=timezone.now() + timedelta(days=1),
            max_active_controls=10,
            max_nodes=10,
            packages_json='["core"]',
            package_limits_json="{}",
            valid=True,
        )

        resp = self._post_json(
            "/open/license/lease/acquire",
            {"node_id": "node-1", "control_code": "ctrl-1", "algorithm_code": "ov_yolov11n_safehat"},
            token="test-token",
        )
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 0)
        self.assertEqual(data.get("msg"), "license_package_denied")
