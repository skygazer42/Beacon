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
    TEST_IMAGE_DIGEST = "sha256:" + "1" * 64
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
            CHART_DIR / "templates" / "background-worker-deployment.yaml",
            CHART_DIR / "templates" / "initialize-job.yaml",
            CHART_DIR / "templates" / "pod-disruption-budget.yaml",
            CHART_DIR / "templates" / "runtime-pvc.yaml",
            CHART_DIR / "templates" / "postgres-statefulset.yaml",
            CHART_DIR / "templates" / "minio-statefulset.yaml",
            CHART_DIR / "templates" / "network-policy.yaml",
            CHART_DIR / "templates" / "services.yaml",
        ]
        missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
        self.assertEqual(missing, [], msg=f"missing chart files: {missing}")

    def test_cloud_runtime_defaults_are_production_safe(self):
        dockerfile = (ROOT / "deploy/cloud-saas-v1/Dockerfile").read_text(encoding="utf-8")
        entrypoint = (ROOT / "deploy/cloud-saas-v1/scripts/entrypoint.sh").read_text(encoding="utf-8")
        compose = (ROOT / "deploy/cloud-saas-v1/compose.yml").read_text(encoding="utf-8")
        monitoring_compose = (ROOT / "deploy/cloud-saas-v1/compose.monitoring.yml").read_text(encoding="utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        values = (CHART_DIR / "values.yaml").read_text(encoding="utf-8")
        deployment = (CHART_DIR / "templates/beacon-cloud-deployment.yaml").read_text(encoding="utf-8")
        worker_deployment = (CHART_DIR / "templates/background-worker-deployment.yaml").read_text(encoding="utf-8")
        initialize_job = (CHART_DIR / "templates/initialize-job.yaml").read_text(encoding="utf-8")
        helpers = (CHART_DIR / "templates/_helpers.tpl").read_text(encoding="utf-8")

        self.assertIn("USER 10001:10001", dockerfile)
        self.assertRegex(dockerfile.splitlines()[0], r"^FROM python:3\.12-alpine3\.23@sha256:[a-f0-9]{64} AS python-base$")
        self.assertRegex(dockerfile, r"(?m)^FROM ghcr\.io/astral-sh/uv:0\.12\.7@sha256:[a-f0-9]{64} AS uv$")
        self.assertIn("RUN apk upgrade --no-cache", dockerfile)
        self.assertIn("--mount=type=cache,target=/root/.cache/uv,sharing=locked", dockerfile)
        self.assertIn("--system --require-hashes --no-build", dockerfile)
        self.assertIn("python -m pip uninstall --yes pip", dockerfile)
        self.assertIn("requirements-cloud.lock", dockerfile)
        self.assertIn("BEACON_ROOT_DIR=/app/data", dockerfile)
        self.assertIn("BEACON_CONFIG_PATH=/app/config.json", dockerfile)
        self.assertIn(
            "COPY --chown=beacon:beacon --chmod=0444 deploy/cloud-saas-v1/config.cloud.json /app/config.json",
            dockerfile,
        )
        self.assertNotIn("COPY --chown=beacon:beacon config.json /app/config.json", dockerfile)
        self.assertIn('org.opencontainers.image.licenses="MIT"', dockerfile)
        self.assertIn("LICENSE THIRD_PARTY_NOTICES.md /licenses/Beacon/", dockerfile)
        self.assertIn("python /app/Admin/manage.py collectstatic --noinput", dockerfile)
        for ignored_runtime_artifact in ("Admin/staticfiles", "Admin/build", "Admin/dist"):
            self.assertIn(ignored_runtime_artifact, dockerignore)
        self.assertIn("exec gunicorn", entrypoint)
        self.assertIn("--no-control-socket", entrypoint)
        self.assertNotIn("manage.py runserver", entrypoint)
        self.assertNotIn("manage.py migrate", entrypoint)
        self.assertNotIn("beacon_cloud_bootstrap", entrypoint)
        self.assertIn("wait_for_migrations.py", entrypoint)
        self.assertIn('${BEACON_GUNICORN_WORKERS:-2}', entrypoint)
        self.assertIn('BEACON_DJANGO_DEBUG: "0"', compose)
        self.assertNotIn('BEACON_DJANGO_ALLOWED_HOSTS: "*"', compose)
        self.assertNotIn("minio/minio:latest", compose)
        self.assertIn('${BEACON_BIND_ADDRESS:-127.0.0.1}:${BEACON_ADMIN_PORT:-9991}:8000', compose)
        self.assertIn('${BEACON_BIND_ADDRESS:-127.0.0.1}:${BEACON_MINIO_API_PORT:-9000}:9000', compose)
        self.assertGreaterEqual(len(re.findall(r"(?m)^\s*image: .*@sha256:[a-f0-9]{64}$", compose)), 4)
        self.assertIn("edge-simulator:\n", compose)
        self.assertIn("beacon-init:\n", compose)
        self.assertIn("beacon-background-worker:\n", compose)
        self.assertIn("BEACON_BACKGROUND_ROLE: web", compose)
        self.assertIn("BEACON_BACKGROUND_ROLE: worker", compose)
        self.assertIn("BEACON_BACKGROUND_ROLE: init", compose)
        self.assertIn('${BEACON_BOOTSTRAP_ADMIN_USERNAME:-admin}', compose)
        self.assertNotIn("cloud_staticfiles", compose)
        self.assertIn("- demo:/demo:ro", compose)
        self.assertIn("mc mb --ignore-existing", (ROOT / "deploy/cloud-saas-v1/scripts/minio_init.sh").read_text(encoding="utf-8"))
        self.assertNotIn("|| true", (ROOT / "deploy/cloud-saas-v1/scripts/minio_init.sh").read_text(encoding="utf-8"))
        self.assertEqual(len(re.findall(r"(?m)^\s*image: .*@sha256:[a-f0-9]{64}$", monitoring_compose)), 2)
        self.assertIn("read_only: true", monitoring_compose)
        self.assertIn('user: "472:472"', monitoring_compose)
        self.assertIn('${BEACON_BIND_ADDRESS:-127.0.0.1}:${BEACON_PROMETHEUS_PORT:-9090}:9090', monitoring_compose)
        self.assertIn('${BEACON_BIND_ADDRESS:-127.0.0.1}:${BEACON_GRAFANA_PORT:-3000}:3000', monitoring_compose)
        self.assertIn("http://127.0.0.1:9090/-/ready", monitoring_compose)
        self.assertIn("http://127.0.0.1:3000/api/health", monitoring_compose)
        self.assertEqual(monitoring_compose.count("healthcheck:"), 2)
        self.assertIn('djangoDebug: "0"', values)
        self.assertNotIn('djangoAllowedHosts: "*"', values)
        self.assertGreaterEqual(values.count("replicaCount: 2"), 2)
        self.assertIn("demoVolume:\n  # Development-only", values)
        self.assertIn("- ReadWriteMany", values)
        self.assertIn("enabled: false", values)
        self.assertIn("strategy:\n    type: RollingUpdate", deployment)
        self.assertIn("maxUnavailable: 0", deployment)
        self.assertIn("runAsNonRoot: true", deployment)
        self.assertIn("readOnlyRootFilesystem: true", deployment)
        self.assertIn("type: RuntimeDefault", deployment)
        self.assertIn("BEACON_REQUIRE_OPEN_API_TOKEN", helpers)
        self.assertIn("health_probe.py", deployment)
        self.assertNotIn("path: /login", deployment)
        self.assertIn("key: beacon-cloud-db-url", helpers)
        self.assertIn('"role" "web"', deployment)
        self.assertNotIn("BEACON_BOOTSTRAP_ADMIN_PASSWORD", deployment)
        self.assertIn("background_worker_entrypoint.sh", worker_deployment)
        self.assertIn('"role" "worker"', worker_deployment)
        self.assertIn("health_probe.py", worker_deployment)
        self.assertIn("- worker", worker_deployment)
        self.assertIn("kind: Job", initialize_job)
        self.assertIn("initialize.sh", initialize_job)
        self.assertIn('"role" "init"', initialize_job)
        self.assertIn("name: minio-bucket-init", initialize_job)
        self.assertIn("persistentVolumeClaim:", deployment)

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

        self.assertEqual(len(re.findall(r"(?m)^kind:\s+Deployment$", rendered)), 2)
        self.assertRegex(rendered, r"kind:\s+StatefulSet")
        self.assertRegex(rendered, r"kind:\s+Job")
        self.assertRegex(rendered, r"kind:\s+Service")
        self.assertRegex(rendered, r"kind:\s+PersistentVolumeClaim")
        self.assertRegex(rendered, r"name:\s+.*beacon-cloud")
        self.assertRegex(rendered, r"name:\s+.*postgres")
        self.assertRegex(rendered, r"name:\s+.*minio")
        self.assertIn("initContainers:", rendered)
        self.assertIn("name: minio-bucket-init", rendered)
        self.assertEqual(len(re.findall(r"(?m)^  replicas: 2$", rendered)), 2)
        self.assertIn("name: beacon-cloud-background-worker", rendered)
        self.assertIn("name: beacon-cloud-init-1", rendered)
        self.assertIn("name: beacon-cloud-runtime", rendered)
        self.assertGreaterEqual(rendered.count("claimName: beacon-cloud-runtime"), 3)
        self.assertIn("- ReadWriteMany", rendered)
        self.assertEqual(len(re.findall(r"(?m)^kind:\s+PodDisruptionBudget$", rendered)), 2)
        self.assertIn("value: \"web\"", rendered)
        self.assertIn("value: \"worker\"", rendered)
        self.assertIn("value: \"init\"", rendered)
        self.assertEqual(rendered.count("key: beacon-bootstrap-admin-password"), 1)
        self.assertNotIn("name: app-staticfiles", rendered)
        self.assertIn("readOnlyRootFilesystem: true", rendered)
        self.assertIn("seccompProfile:", rendered)
        self.assertEqual(len(re.findall(r"kind:\s+NetworkPolicy", rendered)), 3)
        self.assertIn("name: beacon-cloud-beacon-ingress", rendered)
        self.assertIn("name: beacon-cloud-postgres-ingress", rendered)
        self.assertIn("name: beacon-cloud-minio-ingress", rendered)
        self.assertIn("startupProbe:", rendered)
        self.assertIn("readinessProbe:", rendered)
        self.assertIn("livenessProbe:", rendered)
        self.assertIn("/app/deploy/cloud-saas-v1/scripts/health_probe.py", rendered)
        self.assertIn("/app/deploy/cloud-saas-v1/scripts/background_worker_entrypoint.sh", rendered)
        self.assertIn("/app/deploy/cloud-saas-v1/scripts/initialize.sh", rendered)
        self.assertIn("path: /minio/health/live", rendered)
        self.assertIn("path: /minio/health/ready", rendered)
        self.assertIn("value: /var/lib/postgresql/data/pgdata", rendered)
        self.assertIn('pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"', rendered)
        self.assertIn("mc mb --ignore-existing", rendered)
        self.assertNotIn('mc mb -p "local/', rendered)
        self.assertGreaterEqual(len(re.findall(r"image: .*@sha256:[a-f0-9]{64}", rendered)), 4)
        self.assertIn("Authorization: Bearer $BEACON_OPEN_API_TOKEN", rendered)
        self.assertIn("/readyz", rendered)

    def test_helm_template_supports_externally_managed_secret(self):
        result = self.helm(
            "template",
            "beacon-cloud",
            str(CHART_DIR),
            "--set-string",
            "beaconCloud.secrets.existingSecret=beacon-production-secrets",
            "--set-string",
            f"beaconCloud.image.digest={self.TEST_IMAGE_DIGEST}",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        rendered = result.stdout

        self.assertNotRegex(rendered, r"(?m)^kind:\s+Secret$")
        self.assertIn("name: beacon-production-secrets", rendered)
        self.assertNotIn("test-open-api-token", rendered)
        self.assertIn(f"beacon-cloud-saas-v1:v1.0.0@{self.TEST_IMAGE_DIGEST}", rendered)

    def test_helm_template_rejects_external_secret_without_application_digest(self):
        result = self.helm(
            "template",
            "beacon-cloud",
            str(CHART_DIR),
            "--set-string",
            "beaconCloud.secrets.existingSecret=beacon-production-secrets",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("beaconCloud.image.digest is required", result.stderr or result.stdout)

    def test_helm_template_rejects_malformed_image_digest(self):
        result = self.helm(
            "template",
            "beacon-cloud",
            str(CHART_DIR),
            *self.HELM_SECRET_ARGS,
            "--set-string",
            "postgres.image.digest=sha256:not-a-digest",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("postgres.image.digest must match", result.stderr or result.stdout)

    def test_helm_template_requires_redundant_production_replicas(self):
        cases = (
            ("beaconCloud.replicaCount=1", "at least 2 Web replicas"),
            ("backgroundWorker.replicaCount=1", "at least 2 background Worker replicas"),
        )
        for setting, expected_error in cases:
            with self.subTest(setting=setting):
                result = self.helm(
                    "template",
                    "beacon-cloud",
                    str(CHART_DIR),
                    "--set-string",
                    "beaconCloud.secrets.existingSecret=beacon-production-secrets",
                    "--set-string",
                    f"beaconCloud.image.digest={self.TEST_IMAGE_DIGEST}",
                    "--set",
                    setting,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr or result.stdout)

    def test_helm_template_rejects_ephemeral_storage_for_multiple_web_replicas(self):
        result = self.helm(
            "template",
            "beacon-cloud",
            str(CHART_DIR),
            *self.HELM_SECRET_ARGS,
            "--set",
            "beaconCloud.runtimeStorage.persistence.enabled=false",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("multiple Web replicas require", result.stderr or result.stdout)

    def test_helm_template_uses_existing_runtime_claim_without_creating_it(self):
        result = self.helm(
            "template",
            "beacon-cloud",
            str(CHART_DIR),
            *self.HELM_SECRET_ARGS,
            "--set-string",
            "beaconCloud.runtimeStorage.persistence.existingClaim=beacon-rwx-data",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        rendered = result.stdout
        self.assertGreaterEqual(rendered.count("claimName: beacon-rwx-data"), 3)
        self.assertNotRegex(rendered, r"(?ms)kind:\s+PersistentVolumeClaim.*?name:\s+beacon-rwx-data")

    def test_helm_template_rejects_unsafe_django_settings(self):
        cases = (
            ("beaconCloud.env.djangoDebug=1", "djangoDebug must be 0"),
            (
                "beaconCloud.env.djangoAllowedHosts=*",
                "djangoAllowedHosts must be non-empty and must not contain a wildcard",
            ),
        )
        for setting, expected_error in cases:
            with self.subTest(setting=setting):
                result = self.helm(
                    "template",
                    "beacon-cloud",
                    str(CHART_DIR),
                    *self.HELM_SECRET_ARGS,
                    "--set-string",
                    setting,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr or result.stdout)

    def test_helm_template_requires_external_secret_for_external_services(self):
        result = self.helm(
            "template",
            "beacon-cloud",
            str(CHART_DIR),
            *self.HELM_SECRET_ARGS,
            "--set",
            "postgres.enabled=false",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("existingSecret is required", result.stderr or result.stdout)

    def test_helm_template_supports_external_postgres_and_object_storage(self):
        result = self.helm(
            "template",
            "beacon-cloud",
            str(CHART_DIR),
            "--set-string",
            "beaconCloud.secrets.existingSecret=beacon-production-secrets",
            "--set-string",
            f"beaconCloud.image.digest={self.TEST_IMAGE_DIGEST}",
            "--set",
            "postgres.enabled=false",
            "--set",
            "minio.enabled=false",
            "--set-string",
            "minio.externalEndpointURL=https://s3.example.test",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        rendered = result.stdout

        self.assertNotIn("component: postgres", rendered)
        self.assertNotIn("component: minio", rendered)
        self.assertNotIn("name: minio-bucket-init", rendered)
        self.assertNotIn("name: BEACON_PG_HOST", rendered)
        self.assertIn('value: "https://s3.example.test"', rendered)
        self.assertEqual(len(re.findall(r"kind:\s+NetworkPolicy", rendered)), 1)

    def test_helm_template_hardens_enabled_edge_simulator(self):
        result = self.helm(
            "template",
            "beacon-cloud",
            str(CHART_DIR),
            *self.HELM_SECRET_ARGS,
            "--set",
            "edgeSimulator.enabled=true",
            "--set",
            "demoVolume.enabled=true",
            "--set-string",
            "beaconCloud.env.bootstrapEdgeTokenFile=/demo/edge-token",
            "--set-string",
            f"edgeSimulator.image.digest={self.TEST_IMAGE_DIGEST}",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        rendered = result.stdout

        self.assertIn("name: beacon-cloud-edge-simulator", rendered)
        self.assertIn("activeDeadlineSeconds: 600", rendered)
        self.assertIn("automountServiceAccountToken: false", rendered)
        self.assertIn("readOnlyRootFilesystem: true", rendered)
        self.assertIn("value: \"/demo/edge-token\"", rendered)

    def test_helm_template_rejects_edge_simulator_without_shared_volume(self):
        result = self.helm(
            "template",
            "beacon-cloud",
            str(CHART_DIR),
            *self.HELM_SECRET_ARGS,
            "--set",
            "edgeSimulator.enabled=true",
            "--set",
            "demoVolume.enabled=false",
            "--set-string",
            "beaconCloud.env.bootstrapEdgeTokenFile=/demo/edge-token",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("demoVolume.enabled must be true", result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
