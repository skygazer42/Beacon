import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CHART_DIR = ROOT / "deploy" / "cloud-saas-v1" / "chart"
HELM_BIN = os.environ.get("HELM_BIN", "helm")


class CloudSaaSV1HelmChartTest(unittest.TestCase):
    HELM_SECRET_ARGS = (
        "--set-string", "postgres.auth.password=test-database-password-123",
        "--set-string", "minio.rootPassword=test-minio-password-123456",
        "--set-string", "beaconCloud.secrets.openApiToken=test-open-api-token-1234567890123456",
        "--set-string", "beaconCloud.secrets.djangoSecretKey=test-django-secret-key-123456789012",
        "--set-string", "beaconCloud.secrets.edgeTokenPepper=00000000000000000000000000000000",
        "--set-string", "beaconCloud.secrets.bootstrapAdminPassword=test-admin-password-123456",
    )

    def setUp(self):
        if self._testMethodName.startswith("test_helm_") and shutil.which(HELM_BIN) is None:
            self.skipTest(f"helm binary not found: {HELM_BIN}")

    def helm(self, *args):
        return subprocess.run(
            [HELM_BIN, *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_chart_structure_files_exist(self):
        required = [
            CHART_DIR / "Chart.yaml",
            CHART_DIR / "values.yaml",
            CHART_DIR / "templates" / "_helpers.tpl",
            CHART_DIR / "templates" / "configmap.yaml",
            CHART_DIR / "templates" / "beacon-cloud-deployment.yaml",
            CHART_DIR / "templates" / "postgres-statefulset.yaml",
            CHART_DIR / "templates" / "minio-statefulset.yaml",
            CHART_DIR / "templates" / "minio-init-job.yaml",
            CHART_DIR / "templates" / "services.yaml",
        ]
        missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
        self.assertEqual(missing, [], msg=f"missing chart files: {missing}")

    def test_cloud_runtime_defaults_are_production_safe(self):
        dockerfile = (ROOT / "deploy/cloud-saas-v1/Dockerfile").read_text(encoding="utf-8")
        entrypoint = (ROOT / "deploy/cloud-saas-v1/scripts/entrypoint.sh").read_text(encoding="utf-8")
        compose = (ROOT / "deploy/cloud-saas-v1/compose.yml").read_text(encoding="utf-8")
        values = (CHART_DIR / "values.yaml").read_text(encoding="utf-8")
        deployment = (CHART_DIR / "templates/beacon-cloud-deployment.yaml").read_text(encoding="utf-8")

        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("exec gunicorn", entrypoint)
        self.assertNotIn("manage.py runserver", entrypoint)
        self.assertIn('BEACON_DJANGO_DEBUG: "0"', compose)
        self.assertNotIn('BEACON_DJANGO_ALLOWED_HOSTS: "*"', compose)
        self.assertNotIn("minio/minio:latest", compose)
        self.assertIn('djangoDebug: "0"', values)
        self.assertNotIn('djangoAllowedHosts: "*"', values)
        self.assertIn("replicaCount: 1", values)
        self.assertIn("runAsNonRoot: true", deployment)
        self.assertIn("key: beacon-cloud-db-url", deployment)

    def test_helm_lint_passes(self):
        result = self.helm("lint", str(CHART_DIR), *self.HELM_SECRET_ARGS)
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_helm_template_renders_expected_resources(self):
        result = self.helm(
            "template",
            "beacon-cloud",
            str(CHART_DIR),
            *self.HELM_SECRET_ARGS,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        rendered = result.stdout

        self.assertRegex(rendered, r"kind:\s+Deployment")
        self.assertRegex(rendered, r"kind:\s+StatefulSet")
        self.assertRegex(rendered, r"kind:\s+Job")
        self.assertRegex(rendered, r"kind:\s+Service")
        self.assertRegex(rendered, r"name:\s+.*beacon-cloud")
        self.assertRegex(rendered, r"name:\s+.*postgres")
        self.assertRegex(rendered, r"name:\s+.*minio")
        self.assertRegex(rendered, r"name:\s+.*minio-init")
        self.assertIn("replicas: 1", rendered)


if __name__ == "__main__":
    unittest.main()
