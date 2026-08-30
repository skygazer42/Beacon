import io
import json
import os
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

from tools import beacon_backup


class BeaconBackupTest(unittest.TestCase):
    def _create_source_tree(self, base: Path) -> Path:
        root = base / "source"
        (root / "Admin").mkdir(parents=True)
        (root / "data" / "upload" / "alarm").mkdir(parents=True)
        (root / "data" / "models").mkdir(parents=True)
        (root / "PROJECT_VERSION").write_text("v9.8.7\n", encoding="utf-8")
        (root / "config.json").write_text(
            json.dumps(
                {
                    "uploadDir": "data/upload",
                    "modelDir": "data/models",
                    "mediaSecret": "test-only-secret",
                }
            ),
            encoding="utf-8",
        )
        (root / "settings.json").write_text('{"siteName":"Backup Test"}', encoding="utf-8")
        (root / "data" / "upload" / "alarm" / "frame.jpg").write_bytes(b"jpeg-data")
        (root / "data" / "models" / "detector.onnx").write_bytes(b"model-data")

        with sqlite3.connect(root / "Admin" / "Admin.sqlite3") as database:
            database.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            database.execute("INSERT INTO sample(value) VALUES (?)", ("preserved",))
        return root

    @staticmethod
    def _rewrite_member(source: Path, destination: Path, member_name: str, replacement: bytes) -> None:
        with tarfile.open(source, "r:*") as input_archive, tarfile.open(destination, "w:gz") as output_archive:
            for member in input_archive.getmembers():
                extracted = input_archive.extractfile(member)
                payload = extracted.read() if extracted is not None else b""
                if member.name == member_name:
                    payload = replacement
                    member.size = len(payload)
                output_archive.addfile(member, io.BytesIO(payload))

    def test_create_verify_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = self._create_source_tree(base)
            archive = base / "backup.tar.gz"

            created = beacon_backup.create_backup(
                root_dir=root,
                output_path=archive,
                environ={},
            )
            verified = beacon_backup.verify_backup(archive)
            restored = base / "restored"
            report = beacon_backup.restore_backup(archive_path=archive, destination=restored)

            self.assertEqual(created["project_version"], "v9.8.7")
            self.assertEqual(verified["status"], "ok")
            self.assertEqual(report["status"], "restored")
            self.assertEqual((restored / "config.json").read_text(encoding="utf-8"), (root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual((restored / "settings.json").read_text(encoding="utf-8"), '{"siteName":"Backup Test"}')
            self.assertEqual((restored / "data/upload/alarm/frame.jpg").read_bytes(), b"jpeg-data")
            self.assertEqual((restored / "data/models/detector.onnx").read_bytes(), b"model-data")
            with sqlite3.connect(restored / "Admin/Admin.sqlite3") as database:
                self.assertEqual(database.execute("SELECT value FROM sample").fetchone()[0], "preserved")

            with tarfile.open(archive, "r:*") as bundle:
                manifest = json.load(bundle.extractfile(beacon_backup.MANIFEST_NAME))
            manifest_text = json.dumps(manifest)
            self.assertNotIn(str(root), manifest_text)
            self.assertEqual(manifest["authenticity"], "external-signature-required")

    def test_online_sqlite_snapshot_contains_committed_wal_data(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = self._create_source_tree(base)
            database_path = root / "Admin/Admin.sqlite3"
            writer = sqlite3.connect(database_path)
            try:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("INSERT INTO sample(value) VALUES (?)", ("from-wal",))
                writer.commit()
                archive = base / "online.tar.gz"
                beacon_backup.create_backup(root_dir=root, output_path=archive, environ={})
            finally:
                writer.close()

            restored = base / "online-restored"
            beacon_backup.restore_backup(archive_path=archive, destination=restored)
            with sqlite3.connect(restored / "Admin/Admin.sqlite3") as database:
                values = [row[0] for row in database.execute("SELECT value FROM sample ORDER BY id")]
            self.assertEqual(values, ["preserved", "from-wal"])

    def test_verify_rejects_payload_tampering(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = self._create_source_tree(base)
            archive = base / "backup.tar.gz"
            tampered = base / "tampered.tar.gz"
            beacon_backup.create_backup(root_dir=root, output_path=archive, environ={})
            self._rewrite_member(
                archive,
                tampered,
                "payload/upload/alarm/frame.jpg",
                b"changed!!",
            )

            with self.assertRaisesRegex(beacon_backup.BackupError, "checksum mismatch"):
                beacon_backup.verify_backup(tampered)

    def test_verify_rejects_path_traversal_member(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive_path = Path(temporary_dir) / "unsafe.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                payload = b"escape"
                member = tarfile.TarInfo("../escape.txt")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))

            with self.assertRaisesRegex(beacon_backup.BackupError, "unsafe archive member"):
                beacon_backup.verify_backup(archive_path)
            self.assertFalse((Path(temporary_dir).parent / "escape.txt").exists())

    def test_verify_rejects_windows_drive_member(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive_path = Path(temporary_dir) / "unsafe-drive.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                payload = b"escape"
                member = tarfile.TarInfo("C:/escape.txt")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))

            with self.assertRaisesRegex(beacon_backup.BackupError, "invalid archive member"):
                beacon_backup.verify_backup(archive_path)

    def test_restore_refuses_existing_destination(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = self._create_source_tree(base)
            archive = base / "backup.tar.gz"
            beacon_backup.create_backup(root_dir=root, output_path=archive, environ={})
            destination = base / "existing"
            destination.mkdir()

            with self.assertRaisesRegex(beacon_backup.BackupError, "already exists"):
                beacon_backup.restore_backup(archive_path=archive, destination=destination)

    def test_empty_configured_directories_use_safe_defaults(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = self._create_source_tree(base)
            (root / "Admin/static/upload").mkdir(parents=True)
            (root / "Analyzer/models").mkdir(parents=True)
            (root / "Admin/static/upload/default-upload.txt").write_text(
                "default upload", encoding="utf-8"
            )
            (root / "Analyzer/models/default-model.bin").write_bytes(b"default model")
            (root / "config.json").write_text(
                json.dumps({"uploadDir": "", "modelDir": ""}), encoding="utf-8"
            )
            archive = base / "backup.tar.gz"

            beacon_backup.create_backup(root_dir=root, output_path=archive, environ={})

            with tarfile.open(archive, "r:*") as bundle:
                names = set(bundle.getnames())
            self.assertIn("payload/upload/default-upload.txt", names)
            self.assertIn("payload/models/default-model.bin", names)
            self.assertNotIn("payload/upload/alarm/frame.jpg", names)
            self.assertNotIn("payload/models/detector.onnx", names)

    def test_noncanonical_archive_path_is_rejected(self):
        with self.assertRaisesRegex(beacon_backup.BackupError, "non-canonical"):
            beacon_backup._safe_relative_path("payload//file.txt", field="test path")

    @unittest.skipIf(os.name == "nt", "symlink creation may require elevated Windows privileges")
    def test_create_rejects_symlinks_in_file_roots(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = self._create_source_tree(base)
            outside = base / "outside.txt"
            outside.write_text("must not be captured", encoding="utf-8")
            (root / "data/upload/leak.txt").symlink_to(outside)

            with self.assertRaisesRegex(beacon_backup.BackupError, "symlink"):
                beacon_backup.create_backup(
                    root_dir=root,
                    output_path=base / "backup.tar.gz",
                    environ={},
                )

    @unittest.skipIf(os.name == "nt", "symlink creation may require elevated Windows privileges")
    def test_create_rejects_configured_directory_symlink(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = self._create_source_tree(base)
            upload_link = root / "upload-link"
            upload_link.symlink_to(root / "data/upload", target_is_directory=True)
            (root / "config.json").write_text(
                json.dumps({"uploadDir": "upload-link", "modelDir": "data/models"}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(beacon_backup.BackupError, "not a symlink"):
                beacon_backup.create_backup(
                    root_dir=root,
                    output_path=base / "backup.tar.gz",
                    environ={},
                )

    @unittest.skipIf(os.name == "nt", "symlink creation may require elevated Windows privileges")
    def test_restore_refuses_dangling_destination_symlink(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = self._create_source_tree(base)
            archive = base / "backup.tar.gz"
            beacon_backup.create_backup(root_dir=root, output_path=archive, environ={})
            destination = base / "restore-link"
            destination.symlink_to(base / "missing-target", target_is_directory=True)

            with self.assertRaisesRegex(beacon_backup.BackupError, "already exists"):
                beacon_backup.restore_backup(archive_path=archive, destination=destination)
            self.assertFalse((base / "missing-target").exists())


if __name__ == "__main__":
    unittest.main()
