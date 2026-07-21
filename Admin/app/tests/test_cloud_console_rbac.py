import json
import os
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from app.models import CloudEdgeCluster, CloudProject, CloudRole, CloudTenant, CloudUserMembership
from app.utils.CloudRemotePermissions import PERM_CLOUD_REMOTE_STREAMS_VIEW


class CloudConsoleRbacTest(TestCase):
    def setUp(self):
        os.environ["BEACON_DEPLOYMENT_MODE"] = "cloud"
        self.addCleanup(os.environ.pop, "BEACON_DEPLOYMENT_MODE", None)

    def _login_as(self, user: User):
        session = self.client.session
        session["user"] = {"id": user.id, "username": user.username}
        session.save()

    def test_management_apis_reject_unknown_actions(self):
        admin = User.objects.create_superuser(username="cloud-admin", password="pass12345")
        self._login_as(admin)

        for path in (
            "/api/app-shell/cloud/edge-clusters/action",
            "/api/app-shell/cloud/iam/action",
        ):
            with self.subTest(path=path):
                response = self.client.post(path, data={"action": "unknown"})
                payload = json.loads(response.content.decode("utf-8"))
                self.assertEqual(payload.get("code"), 0, msg=payload)

    def test_alarms_requires_permission(self):
        from app.models import CloudProject, CloudRole, CloudTenant, CloudUserMembership

        t1 = CloudTenant.objects.create(name="t1", slug="t1", enabled=True)
        CloudProject.objects.create(tenant=t1, name="default", enabled=True)

        u1 = User.objects.create_user(username="u1", password="pass12345")
        r1 = CloudRole.objects.create(tenant=t1, key="no", name="no", permissions_json="{}", enabled=True)
        CloudUserMembership.objects.create(user=u1, tenant=t1, role=r1, enabled=True, is_default=True)

        self._login_as(u1)
        res = self.client.get("/cloud/alarms")
        self.assertEqual(res.status_code, 403)
        self.assertIn("权限", res.content.decode("utf-8"))

    def test_resource_scope_limits_visible_clusters_and_alarms(self):
        from app.models import CloudAlarmEvent, CloudEdgeCluster, CloudProject, CloudRole, CloudTenant, CloudUserMembership

        t1 = CloudTenant.objects.create(name="t1", slug="t1", enabled=True)
        p1 = CloudProject.objects.create(tenant=t1, name="default", enabled=True)

        c1 = CloudEdgeCluster.objects.create(project=p1, name="c1", enabled=True)
        c2 = CloudEdgeCluster.objects.create(project=p1, name="c2", enabled=True)

        CloudAlarmEvent.objects.create(edge_cluster=c1, event_id="evt-1", desc="alarm-c1")
        CloudAlarmEvent.objects.create(edge_cluster=c2, event_id="evt-2", desc="alarm-c2")

        u1 = User.objects.create_user(username="u1", password="pass12345")
        r1 = CloudRole.objects.create(
            tenant=t1,
            key="viewer",
            name="viewer",
            permissions_json='{"cloud.alarms.view": true, "cloud.edge_clusters.view": true}',
            enabled=True,
        )
        CloudUserMembership.objects.create(
            user=u1,
            tenant=t1,
            role=r1,
            enabled=True,
            is_default=True,
            resource_scope_json='{"edge_cluster_ids": [%d]}' % c1.id,
        )

        self._login_as(u1)
        res = self.client.get("/api/app-shell/cloud/alarms")
        self.assertEqual(res.status_code, 200)
        payload = json.loads(res.content.decode("utf-8"))
        rows = (payload.get("data") or {}).get("rows") or []
        self.assertEqual([row.get("desc") for row in rows], ["alarm-c1"])

    def test_remote_streams_respect_membership_cluster_scope(self):
        tenant = CloudTenant.objects.create(name="remote-tenant", slug="remote-tenant", enabled=True)
        project = CloudProject.objects.create(tenant=tenant, name="default", enabled=True)
        allowed_cluster = CloudEdgeCluster.objects.create(
            project=project,
            name="allowed-edge",
            edge_admin_base_url="http://edge.example:9991",
            edge_openapi_token="token-a",
            node_code="node-a",
            enabled=True,
        )
        hidden_cluster = CloudEdgeCluster.objects.create(project=project, name="hidden-edge", enabled=True)
        user = User.objects.create_user(username="remote-viewer", password="pass12345")
        role = CloudRole.objects.create(
            tenant=tenant,
            key="remote-viewer",
            name="Remote Viewer",
            permissions_json=json.dumps({PERM_CLOUD_REMOTE_STREAMS_VIEW: True}),
            enabled=True,
        )
        CloudUserMembership.objects.create(
            user=user,
            tenant=tenant,
            role=role,
            enabled=True,
            is_default=True,
            resource_scope_json=json.dumps({"edge_cluster_ids": [allowed_cluster.id]}),
        )
        self._login_as(user)

        with mock.patch(
            "app.views.AppShellView.CloudRemoteStreamsView._fetch_remote_streams",
            return_value=("", [{"code": "cam-001", "nickname": "North Gate"}]),
        ) as fetch_streams:
            response = self.client.get("/api/app-shell/cloud/remote/streams")
            denied_response = self.client.get(
                f"/api/app-shell/cloud/remote/streams?cluster_id={hidden_cluster.id}"
            )
            default_detail_response = self.client.get(
                "/api/app-shell/cloud/remote/stream/detail?cluster_id=0"
            )

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)
        data = payload["data"]
        self.assertTrue(data["access_ok"])
        self.assertEqual(data["selected_cluster_id"], allowed_cluster.id)
        self.assertEqual([row["id"] for row in data["clusters"]], [allowed_cluster.id])
        self.assertEqual(data["rows"][0]["code"], "cam-001")

        denied_payload = json.loads(denied_response.content.decode("utf-8"))
        self.assertEqual(denied_payload.get("code"), 0, msg=denied_payload)
        self.assertIn("无权", denied_payload.get("msg") or "")
        fetch_streams.assert_called_once_with(allowed_cluster)

        default_detail_payload = json.loads(default_detail_response.content.decode("utf-8"))
        self.assertEqual(default_detail_payload.get("code"), 1000, msg=default_detail_payload)
        self.assertEqual(
            (default_detail_payload.get("data") or {}).get("cluster", {}).get("id"),
            allowed_cluster.id,
        )
