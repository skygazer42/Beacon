import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path


class RtspSimulatorExtractTest(unittest.TestCase):
    def test_verify_archive_sha256_rejects_modified_content(self):
        from tools import rtsp_simulator

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "mediamtx.tar.gz"
            archive_path.write_bytes(b"trusted fixture")
            expected = hashlib.sha256(b"trusted fixture").hexdigest()

            rtsp_simulator._verify_archive_sha256(archive_path, expected)
            archive_path.write_bytes(b"modified fixture")

            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                rtsp_simulator._verify_archive_sha256(archive_path, expected)

    def test_extract_tar_safely_skips_path_traversal_members(self):
        from tools import rtsp_simulator

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "mediamtx.tar.gz"
            target_dir = Path(tmp) / "extract"

            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w:gz") as tf:
                safe_info = tarfile.TarInfo("mediamtx")
                safe_bytes = b"#!/bin/sh\nexit 0\n"
                safe_info.size = len(safe_bytes)
                tf.addfile(safe_info, io.BytesIO(safe_bytes))

                bad_info = tarfile.TarInfo("../escape.txt")
                bad_bytes = b"bad"
                bad_info.size = len(bad_bytes)
                tf.addfile(bad_info, io.BytesIO(bad_bytes))

            archive_path.write_bytes(payload.getvalue())
            extracted = rtsp_simulator._extract_tar_safely(archive_path, target_dir)

            self.assertEqual(extracted, 1)
            self.assertTrue((target_dir / "mediamtx").exists())
            self.assertFalse((Path(tmp) / "escape.txt").exists())

    def test_extract_tar_safely_extracts_nested_regular_files_and_skips_links(self):
        from tools import rtsp_simulator

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "mediamtx.tar.gz"
            target_dir = Path(tmp) / "extract"

            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w:gz") as tf:
                nested_info = tarfile.TarInfo("bin/mediamtx")
                nested_bytes = b"#!/bin/sh\nexit 0\n"
                nested_info.mode = 0o755
                nested_info.size = len(nested_bytes)
                tf.addfile(nested_info, io.BytesIO(nested_bytes))

                link_info = tarfile.TarInfo("bin/mediamtx-link")
                link_info.type = tarfile.SYMTYPE
                link_info.linkname = "mediamtx"
                tf.addfile(link_info)

            archive_path.write_bytes(payload.getvalue())
            extracted = rtsp_simulator._extract_tar_safely(archive_path, target_dir)

            extracted_path = target_dir / "bin" / "mediamtx"
            self.assertEqual(extracted, 1)
            self.assertEqual(extracted_path.read_bytes(), nested_bytes)
            self.assertEqual(extracted_path.stat().st_mode & 0o777, 0o755)
            self.assertFalse((target_dir / "bin" / "mediamtx-link").exists())


if __name__ == "__main__":
    unittest.main()
