import json
import os
from datetime import datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone


class CloudOpenApiTest(TestCase):
    def setUp(self):
        os.environ["BEACON_DEPLOYMENT_MODE"] = "cloud"
        os.environ["BEACON_CLOUD_EDGE_TOKEN_PEPPER"] = "pepper-test-002"
        os.environ["BEACON_CLOUD_S3_BUCKET"] = "beacon-alarms"
        self.addCleanup(os.environ.pop, "BEACON_DEPLOYMENT_MODE", None)
        self.addCleanup(os.environ.pop, "BEACON_CLOUD_EDGE_TOKEN_PEPPER", None)
        self.addCleanup(os.environ.pop, "BEACON_CLOUD_S3_BUCKET", None)

        from app.models import CloudEdgeCluster, CloudProject, CloudTenant
        from app.utils.CloudEdgeAuth import hash_edge_token

        tenant = CloudTenant.objects.create(name="tenant-1", slug="tenant-1")
        project = CloudProject.objects.create(tenant=tenant, name="project-1")

        self.edge_token = "edge-token-plain-002"
        self.cluster = CloudEdgeCluster.objects.create(
            project=project,
            name="cluster-1",
            enabled=True,
            edge_token_hash=hash_edge_token(self.edge_token),
        )

    def test_presign_requires_token(self):
        res = self.client.post(
            "/open/cloud/v1/presign/image",
            data=json.dumps({"event_id": "evt-1", "content_type": "image/jpeg", "ext": ".jpg"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 401, msg=res.content)

    def test_presign_disabled_cluster_is_forbidden(self):
        self.cluster.enabled = False
        self.cluster.save(update_fields=["enabled"])

        res = self.client.post(
            "/open/cloud/v1/presign/image",
            data=json.dumps({"event_id": "evt-1", "content_type": "image/jpeg", "ext": ".jpg"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.edge_token}",
        )
        self.assertEqual(res.status_code, 403, msg=res.content)

    def test_presign_success_returns_object_key(self):
        with patch(
            "app.utils.CloudS3.presign_put_image",
            return_value={
                "url": "http://example.com/upload",
                "headers": {"Content-Type": "image/jpeg"},
                "expires_in_seconds": 900,
            },
        ):
            res = self.client.post(
                "/open/cloud/v1/presign/image",
                data=json.dumps({"event_id": "evt-1", "content_type": "image/jpeg", "ext": ".jpg"}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {self.edge_token}",
            )

        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)
        data = body.get("data") or {}
        self.assertEqual(data.get("bucket"), "beacon-alarms", msg=body)
        self.assertTrue(str(data.get("object_key") or "").endswith("/image.jpg"), msg=body)

    def test_ingest_is_idempotent(self):
        from app.models import CloudAlarmEvent

        event_id = "evt-ingest-1"
        payload = {
            "schema": "beacon.event.v1",
            "event_id": event_id,
            "event_type": "alarm.created",
            "event_source": "openAdd",
            "timestamp": "2026-02-20T12:34:56",
            "node_code": "node-1",
            "control_code": "C001",
            "desc": "hello",
            "data": {},
        }

        res1 = self.client.post(
            "/open/cloud/v1/events/alarm-created",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.edge_token}",
        )
        self.assertEqual(res1.status_code, 200, msg=res1.content)
        body1 = json.loads(res1.content.decode("utf-8"))
        self.assertEqual(body1.get("code"), 1000, msg=body1)

        res2 = self.client.post(
            "/open/cloud/v1/events/alarm-created",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.edge_token}",
        )
        self.assertEqual(res2.status_code, 200, msg=res2.content)
        body2 = json.loads(res2.content.decode("utf-8"))
        self.assertEqual(body2.get("code"), 1000, msg=body2)

        self.assertEqual(
            CloudAlarmEvent.objects.filter(edge_cluster=self.cluster, event_id=event_id).count(),
            1,
        )

    def test_ingest_accepts_timezone_aware_timestamp(self):
        from app.models import CloudAlarmEvent

        event_id = "evt-ingest-aware-1"
        payload = {
            "schema": "beacon.event.v1",
            "event_id": event_id,
            "event_type": "alarm.created",
            "event_source": "openAdd",
            "timestamp": "2026-02-20T12:34:56+00:00",
            "node_code": "node-1",
            "control_code": "C001",
            "desc": "hello-aware",
            "data": {},
        }

        res = self.client.post(
            "/open/cloud/v1/events/alarm-created",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.edge_token}",
        )
        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        row = CloudAlarmEvent.objects.get(edge_cluster=self.cluster, event_id=event_id)
        aware = datetime.fromisoformat(payload["timestamp"])
        expected = timezone.localtime(aware, timezone.get_current_timezone()).replace(tzinfo=None)
        self.assertEqual(row.timestamp, expected)
