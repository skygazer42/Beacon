import json
import os
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase


class CloudConsoleMultiTenantIsolationTest(TestCase):
    def setUp(self):
        os.environ["BEACON_DEPLOYMENT_MODE"] = "cloud"
        self.addCleanup(os.environ.pop, "BEACON_DEPLOYMENT_MODE", None)

    def _login_as(self, user: User):
        session = self.client.session
        session["user"] = {"id": user.id, "username": user.username}
        session.save()

    def test_edge_clusters_are_scoped_to_tenant(self):
        from app.models import CloudEdgeCluster, CloudProject, CloudRole, CloudTenant, CloudUserMembership

        t1 = CloudTenant.objects.create(name="t1", slug="t1", enabled=True)
        t2 = CloudTenant.objects.create(name="t2", slug="t2", enabled=True)
        p1 = CloudProject.objects.create(tenant=t1, name="default", enabled=True)
        p2 = CloudProject.objects.create(tenant=t2, name="default", enabled=True)

        c1 = CloudEdgeCluster.objects.create(project=p1, name="c1", enabled=True)
        CloudEdgeCluster.objects.create(project=p2, name="c2", enabled=True)

        u1 = User.objects.create_user(username="u1", password="pass12345")
        r1 = CloudRole.objects.create(
            tenant=t1,
            key="viewer",
            name="viewer",
            permissions_json='{"cloud.edge_clusters.view": true, "cloud.alarms.view": true}',
            enabled=True,
        )
        CloudUserMembership.objects.create(user=u1, tenant=t1, role=r1, enabled=True, is_default=True)

        self._login_as(u1)
        res = self.client.get("/api/app-shell/cloud/edge-clusters")
        self.assertEqual(res.status_code, 200)
        payload = json.loads(res.content.decode("utf-8"))
        rows = (payload.get("data") or {}).get("rows") or []
        self.assertEqual([row.get("name") for row in rows], ["c1"])
        self.assertEqual([row.get("id") for row in rows], [c1.id])

    def test_alarms_are_scoped_to_tenant(self):
        from app.models import CloudAlarmEvent, CloudEdgeCluster, CloudProject, CloudRole, CloudTenant, CloudUserMembership

        t1 = CloudTenant.objects.create(name="t1", slug="t1", enabled=True)
        t2 = CloudTenant.objects.create(name="t2", slug="t2", enabled=True)
        p1 = CloudProject.objects.create(tenant=t1, name="default", enabled=True)
        p2 = CloudProject.objects.create(tenant=t2, name="default", enabled=True)

        c1 = CloudEdgeCluster.objects.create(project=p1, name="c1", enabled=True)
        c2 = CloudEdgeCluster.objects.create(project=p2, name="c2", enabled=True)

        CloudAlarmEvent.objects.create(edge_cluster=c1, event_id="evt-1", desc="alarm-t1")
        CloudAlarmEvent.objects.create(edge_cluster=c2, event_id="evt-2", desc="alarm-t2")

        u1 = User.objects.create_user(username="u1", password="pass12345")
        r1 = CloudRole.objects.create(
            tenant=t1,
            key="viewer",
            name="viewer",
            permissions_json='{"cloud.alarms.view": true}',
            enabled=True,
        )
        CloudUserMembership.objects.create(user=u1, tenant=t1, role=r1, enabled=True, is_default=True)

        self._login_as(u1)
        res = self.client.get("/api/app-shell/cloud/alarms")
        self.assertEqual(res.status_code, 200)
        payload = json.loads(res.content.decode("utf-8"))
        rows = (payload.get("data") or {}).get("rows") or []
        self.assertEqual([row.get("desc") for row in rows], ["alarm-t1"])

    def test_remote_apis_reject_foreign_cluster_without_falling_back(self):
        from app.models import CloudEdgeCluster, CloudProject, CloudRole, CloudTenant, CloudUserMembership
        from app.utils.CloudRemotePermissions import (
            PERM_CLOUD_REMOTE_PLATFORM_VIEW,
            PERM_CLOUD_REMOTE_RECORDINGS_VIEW,
            PERM_CLOUD_REMOTE_STREAMS_VIEW,
        )

        own_tenant = CloudTenant.objects.create(name="own", slug="own", enabled=True)
        foreign_tenant = CloudTenant.objects.create(name="foreign", slug="foreign", enabled=True)
        own_project = CloudProject.objects.create(tenant=own_tenant, name="default", enabled=True)
        foreign_project = CloudProject.objects.create(tenant=foreign_tenant, name="default", enabled=True)
        CloudEdgeCluster.objects.create(
            project=own_project,
            name="own-edge",
            edge_admin_base_url="http://own-edge:9991",
            edge_openapi_token="own-token",
            enabled=True,
        )
        foreign_cluster = CloudEdgeCluster.objects.create(
            project=foreign_project,
            name="foreign-edge",
            edge_admin_base_url="http://foreign-edge:9991",
            edge_openapi_token="foreign-token",
            enabled=True,
        )
        user = User.objects.create_user(username="remote-own", password="pass12345")
        role = CloudRole.objects.create(
            tenant=own_tenant,
            key="remote-viewer",
            name="Remote Viewer",
            permissions_json=json.dumps(
                {
                    PERM_CLOUD_REMOTE_STREAMS_VIEW: True,
                    PERM_CLOUD_REMOTE_RECORDINGS_VIEW: True,
                    PERM_CLOUD_REMOTE_PLATFORM_VIEW: True,
                }
            ),
            enabled=True,
        )
        CloudUserMembership.objects.create(
            user=user,
            tenant=own_tenant,
            role=role,
            enabled=True,
            is_default=True,
        )
        self._login_as(user)

        endpoints = (
            f"/api/app-shell/cloud/remote/streams?cluster_id={foreign_cluster.id}",
            f"/api/app-shell/cloud/remote/stream/detail?cluster_id={foreign_cluster.id}&code=cam-1",
            f"/api/app-shell/cloud/remote/recordings?cluster_id={foreign_cluster.id}&stream_code=cam-1",
            f"/api/app-shell/cloud/remote/platform?cluster_id={foreign_cluster.id}",
            "/api/app-shell/cloud/remote/streams?cluster_id=not-a-number",
            "/api/app-shell/cloud/remote/stream/detail?cluster_id=not-a-number&code=cam-1",
            "/api/app-shell/cloud/remote/recordings?cluster_id=not-a-number&stream_code=cam-1",
            "/api/app-shell/cloud/remote/platform?cluster_id=not-a-number",
        )
        with (
            mock.patch(
                "app.views.AppShellView.CloudRemoteStreamsView._fetch_remote_streams",
                return_value=("", []),
            ) as fetch_streams,
            mock.patch("app.views.AppShellView.CloudRemoteStreamDetailView._build_cloud_edge_client") as build_detail_client,
            mock.patch(
                "app.views.AppShellView._fetch_remote_recording_rows",
                return_value=([], 0),
            ) as fetch_recordings,
            mock.patch(
                "app.views.AppShellView.CloudRemotePlatformView._fetch_remote_platform_data",
                return_value=("", [], [], {}),
            ) as fetch_platform,
        ):
            payloads = [json.loads(self.client.get(endpoint).content.decode("utf-8")) for endpoint in endpoints]

        self.assertTrue(all(payload.get("code") == 0 for payload in payloads), msg=payloads)
        self.assertTrue(all("无权" in str(payload.get("msg") or "") for payload in payloads), msg=payloads)
        self.assertTrue(
            all("foreign-edge" not in json.dumps(payload, ensure_ascii=False) for payload in payloads),
            msg=payloads,
        )
        fetch_streams.assert_not_called()
        build_detail_client.assert_not_called()
        fetch_recordings.assert_not_called()
        fetch_platform.assert_not_called()
