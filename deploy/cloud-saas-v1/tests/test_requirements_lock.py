import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "deploy/cloud-saas-v1/scripts/verify_requirements_lock.py"
SPEC = importlib.util.spec_from_file_location("beacon_verify_requirements_lock", MODULE_PATH)
VERIFY_LOCK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY_LOCK)


class RequirementsLockTest(unittest.TestCase):
    def test_repository_cloud_lock_is_current_and_hashed(self):
        VERIFY_LOCK.verify_requirements_lock(
            ROOT / "Admin/requirements-cloud.txt",
            ROOT / "Admin/requirements-cloud.lock",
        )

    def test_rejects_stale_direct_pin(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            direct = root / "requirements.txt"
            lock = root / "requirements.lock"
            direct.write_text("Django==5.2.17\n", encoding="utf-8")
            lock.write_text(
                "django==5.2.16 \\" + "\n    --hash=sha256:" + "a" * 64 + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(VERIFY_LOCK.LockValidationError, "version mismatch"):
                VERIFY_LOCK.verify_requirements_lock(direct, lock)

    def test_rejects_missing_hash_or_unsafe_option(self):
        cases = (
            "django==5.2.17\n",
            "--index-url https://packages.example.test/simple\n"
            + "django==5.2.17 \\"
            + "\n    --hash=sha256:"
            + "a" * 64
            + "\n",
        )
        for payload in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                direct = root / "requirements.txt"
                lock = root / "requirements.lock"
                direct.write_text("Django==5.2.17\n", encoding="utf-8")
                lock.write_text(payload, encoding="utf-8")
                with self.assertRaises(VERIFY_LOCK.LockValidationError):
                    VERIFY_LOCK.verify_requirements_lock(direct, lock)


if __name__ == "__main__":
    unittest.main()
