import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase


class ConfigModuleHelpersTest(SimpleTestCase):
    def test_analyzer_localdeps_prefers_gpu_onnxruntime(self):
        import runtime_paths

        with tempfile.TemporaryDirectory() as root_dir:
            localdeps = os.path.join(root_dir, "third_party", "localdeps")
            os.makedirs(os.path.join(localdeps, "sysroot"))
            os.makedirs(os.path.join(localdeps, "src", "onnxruntime-linux-x64-1.17.3"))
            gpu_dir = os.path.join(localdeps, "src", "onnxruntime-linux-x64-gpu-1.18.1")
            os.makedirs(gpu_dir)

            with mock.patch.dict(os.environ, {}, clear=True):
                layout = runtime_paths.resolve_analyzer_localdeps_layout(root_dir)

        self.assertEqual(layout["onnxruntime_dir"], gpu_dir)

    def test_cloud_connection_can_load_from_config_json(self):
        from app.utils import Config as ConfigModule

        with mock.patch.object(
            ConfigModule,
            "_load_config_data",
            return_value={
                "cloudEnabled": True,
                "cloudBaseUrl": "https://cloud.example.com",
                "cloudEdgeToken": "edge-token",
            },
        ), mock.patch.dict(os.environ, {}, clear=True):
            cfg = ConfigModule.Config()

        self.assertTrue(cfg.cloudEnabled)
        self.assertEqual(cfg.cloudBaseUrl, "https://cloud.example.com")
        self.assertEqual(cfg.cloudEdgeToken, "edge-token")

    def test_runtime_secrets_prefer_environment(self):
        from app.utils import Config as ConfigModule

        with mock.patch.object(ConfigModule, "_load_config_data", return_value={}), mock.patch.dict(
            os.environ,
            {
                "BEACON_MEDIA_SECRET": "media-from-env",
                "BEACON_LICENSE_KEY": "license-from-env",
            },
            clear=True,
        ):
            cfg = ConfigModule.Config()

        self.assertEqual(cfg.mediaSecret, "media-from-env")
        self.assertEqual(cfg.licenseKey, "license-from-env")

    def test_config_bool_from_env_prefers_env_then_json(self):
        from app.utils import Config as ConfigModule

        self.assertTrue(
            ConfigModule._config_bool_from_env(
                {"flag": False},
                env_key="BEACON_FLAG",
                json_key="flag",
                default=False,
                environ={"BEACON_FLAG": "yes"},
            )
        )
        self.assertTrue(
            ConfigModule._config_bool_from_env(
                {"flag": True},
                env_key="BEACON_FLAG",
                json_key="flag",
                default=False,
                environ={},
            )
        )
        self.assertFalse(
            ConfigModule._config_bool_from_env(
                {"flag": False},
                env_key="BEACON_FLAG",
                json_key="flag",
                default=True,
                environ={"BEACON_FLAG": ""},
            )
        )

    def test_resolve_config_dir_falls_back_for_windows_path_on_non_windows(self):
        from app.utils import Config as ConfigModule

        with self.assertLogs(ConfigModule.logger, level="WARNING") as logs:
            resolved = ConfigModule._resolve_config_dir(
                raw_value=r"C:\\beacon\\upload",
                base_dir_parent="/srv/beacon",
                default_relative="Admin/static/upload",
                json_key="uploadDir",
                platform_name="posix",
            )

        self.assertEqual(resolved, os.path.normpath("/srv/beacon/Admin/static/upload"))
        self.assertTrue(any("windows path" in line.lower() for line in logs.output))

    def test_config_license_type_prefers_env_override(self):
        from app.utils import Config as ConfigModule

        with mock.patch.dict(os.environ, {"BEACON_LICENSE_TYPE": "pool"}, clear=False):
            cfg = ConfigModule.Config()

        self.assertEqual(cfg.license_type, "pool")
        self.assertEqual(cfg.licenseType, "pool")
        cfg.openApiToken = "legacy-token"
        self.assertEqual(cfg.open_api_token, "legacy-token")
        cfg.open_api_token = "snake-token"
        self.assertEqual(cfg.openApiToken, "snake-token")
        cfg.upload_dir_www = "/media/"
        self.assertEqual(cfg.uploadDir_www, "/media/")

        with mock.patch.object(cfg, "licenseType", "dongle", create=True):
            self.assertEqual(cfg.license_type, "dongle")
            self.assertEqual(cfg.licenseType, "dongle")
        self.assertEqual(cfg.license_type, "pool")
        self.assertEqual(cfg.licenseType, "pool")

        with mock.patch.object(cfg, "uploadDir_www", "/patched/", create=True):
            self.assertEqual(cfg.upload_dir_www, "/patched/")
            self.assertEqual(cfg.uploadDir_www, "/patched/")
        self.assertEqual(cfg.upload_dir_www, "/media/")
        self.assertEqual(cfg.uploadDir_www, "/media/")

    def test_file_service_root_follows_upload_dir_override_when_config_uses_same_default_root(self):
        from app.utils import Config as ConfigModule

        config_data = {
            "uploadDir": "Admin/static/upload",
            "fileServiceEnabled": True,
            "fileServiceRootDir": "Admin/static/upload",
        }

        with tempfile.TemporaryDirectory() as upload_root:
            with mock.patch.object(ConfigModule, "_load_config_data", return_value=config_data):
                with mock.patch.dict(
                    os.environ,
                    {
                        "BEACON_UPLOAD_DIR": upload_root,
                        "BEACON_FILE_SERVICE_ROOT_DIR": "",
                    },
                    clear=False,
                ):
                    cfg = ConfigModule.Config()

        self.assertEqual(cfg.upload_dir, os.path.normpath(upload_root))
        self.assertEqual(cfg.storage_root_path, os.path.normpath(upload_root))
        self.assertEqual(cfg.file_service_root_dir, os.path.normpath(upload_root))

    def test_config_network_hosts_prefer_service_env_overrides(self):
        from app.utils import Config as ConfigModule

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_ADMIN_HOST": "admin",
                "BEACON_ANALYZER_HOST": "analyzer",
                "BEACON_MEDIA_HOST": "mediasever",
            },
            clear=False,
        ):
            cfg = ConfigModule.Config()

        self.assertEqual(cfg.adminHost, "http://admin:9991")
        self.assertEqual(cfg.analyzerHost, "http://analyzer:9993")
        self.assertEqual(cfg.mediaHttpHost, "http://mediasever:9992")
        self.assertEqual(cfg.mediaWsHost, "ws://mediasever:9992")
        self.assertEqual(cfg.mediaRtspHost, "rtsp://mediasever:9994")
        self.assertEqual(cfg.mediaRtmpHost, "rtmp://mediasever:9995")
