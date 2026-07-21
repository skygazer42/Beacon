import os

from django.http import HttpResponse
from django.test import RequestFactory, TestCase


class CloudEdgeAuthTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        os.environ["BEACON_DEPLOYMENT_MODE"] = "cloud"
        os.environ["BEACON_CLOUD_EDGE_TOKEN_PEPPER"] = "pepper-test-001"
        self.addCleanup(os.environ.pop, "BEACON_DEPLOYMENT_MODE", None)
        self.addCleanup(os.environ.pop, "BEACON_CLOUD_EDGE_TOKEN_PEPPER", None)

        from app.middleware import SimpleMiddleware
        from app.models import CloudEdgeCluster, CloudProject, CloudTenant
        from app.utils.CloudEdgeAuth import hash_edge_token

        tenant = CloudTenant.objects.create(name="tenant-1", slug="tenant-1")
        project = CloudProject.objects.create(tenant=tenant, name="project-1")

        self.edge_token = "edge-token-plain-001"
        token_hash = hash_edge_token(self.edge_token)
        self.cluster = CloudEdgeCluster.objects.create(
            project=project,
            name="cluster-1",
            enabled=True,
            edge_token_hash=token_hash,
        )

        self.middleware = SimpleMiddleware(lambda req: HttpResponse("ok"))

    def _make_request(self, *, token: str = "", path: str = "/open/cloud/v1/presign/image"):
        req = self.factory.post(path, data="{}", content_type="application/json")
        req.session = {}
        if token:
            req.META["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return req

    def test_missing_authorization_is_unauthorized(self):
        req = self._make_request(token="")
        res = self.middleware.process_request(req)
        self.assertIsNotNone(res)
        self.assertEqual(getattr(res, "status_code", None), 401)

    def test_wrong_token_is_unauthorized(self):
        req = self._make_request(token="wrong-token")
        res = self.middleware.process_request(req)
        self.assertIsNotNone(res)
        self.assertEqual(getattr(res, "status_code", None), 401)

    def test_correct_token_is_allowed_and_sets_cluster(self):
        req = self._make_request(token=self.edge_token)
        res = self.middleware.process_request(req)
        self.assertIsNone(res)
        self.assertEqual(getattr(getattr(req, "cloud_edge_cluster", None), "id", None), self.cluster.id)

    def test_disabled_cluster_is_forbidden(self):
        self.cluster.enabled = False
        self.cluster.save(update_fields=["enabled"])

        req = self._make_request(token=self.edge_token)
        res = self.middleware.process_request(req)
        self.assertIsNotNone(res)
        self.assertEqual(getattr(res, "status_code", None), 403)

