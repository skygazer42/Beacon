import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "deploy" / "cloud-saas-v1" / "scripts" / "minio_init.sh"


class MinioInitScriptTest(unittest.TestCase):
    def _run(self, alias_status: int):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            calls = tmp_path / "mc-calls"
            mc = tmp_path / "mc"
            mc.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$MC_CALLS\"\n"
                "if [ \"$1\" = alias ]; then exit \"$MC_ALIAS_STATUS\"; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            mc.chmod(0o755)
            sleep = tmp_path / "sleep"
            sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            sleep.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{tmp}{os.pathsep}{env.get('PATH', '')}",
                    "MC_ALIAS_STATUS": str(alias_status),
                    "MC_CALLS": str(calls),
                    "MINIO_ENDPOINT": "http://minio.example:9000",
                    "MINIO_ROOT_USER": "test-user",
                    "MINIO_ROOT_PASSWORD": "test-password",
                    "BEACON_CLOUD_S3_BUCKET": "test-bucket",
                }
            )
            result = subprocess.run(
                ["/bin/sh", str(SCRIPT)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            call_text = calls.read_text(encoding="utf-8") if calls.exists() else ""
            return result, call_text

    def test_creates_bucket_idempotently_after_alias_connects(self):
        result, calls = self._run(alias_status=0)

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertIn("alias set beacon http://minio.example:9000 test-user test-password", calls)
        self.assertIn("mb --ignore-existing beacon/test-bucket", calls)
        self.assertIn("bucket ready: test-bucket", result.stdout)

    def test_fails_closed_when_minio_never_becomes_available(self):
        result, calls = self._run(alias_status=1)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls.count("alias set beacon"), 60)
        self.assertNotIn("mb ", calls)
        self.assertIn("minio unavailable after 60 attempts", result.stderr)


if __name__ == "__main__":
    unittest.main()
