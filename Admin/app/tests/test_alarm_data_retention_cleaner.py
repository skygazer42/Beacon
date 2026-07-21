import os
import tempfile
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from app.models import Alarm, SystemConfig


class AlarmDataRetentionCleanerTest(TestCase):
    @staticmethod
    def _write_media(root, relative_path, content):
        absolute_path = os.path.join(root, *relative_path.split("/"))
        os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
        with open(absolute_path, "wb") as file_obj:
            file_obj.write(content)
        return absolute_path

    def _enable_one_day_retention(self):
        SystemConfig.objects.create(key="alarmDataAutoCleanEnabled", value="1")
        SystemConfig.objects.create(key="alarmDataRetentionDays", value="1")

    def _create_alarm(self, *, control_code, video_path, age):
        alarm = Alarm.objects.create(
            sort=0,
            control_code=control_code,
            desc=control_code,
            video_path=video_path,
            state=0,
        )
        Alarm.objects.filter(id=alarm.id).update(create_time=timezone.now() - age)
        return alarm

    def test_cleanup_alarm_data_deletes_old_records_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            upload_dir = tmp

            # Enable retention: keep 1 day.
            SystemConfig.objects.create(key="alarmDataAutoCleanEnabled", value="1", remark="报警数据自动清理开关")
            SystemConfig.objects.create(key="alarmDataRetentionDays", value="1", remark="报警数据保留天数")

            # Old alarm (should be deleted)
            old_rel_dir = "alarm/control001/20260101010101_12345678"
            old_video_rel = f"{old_rel_dir}/main.mp4"
            old_image_rel = f"{old_rel_dir}/main.jpg"
            os.makedirs(os.path.join(upload_dir, old_rel_dir), exist_ok=True)
            with open(os.path.join(upload_dir, old_video_rel), "wb") as f:
                f.write(b"demo")
            with open(os.path.join(upload_dir, old_image_rel), "wb") as f:
                f.write(b"demo")

            old_alarm = Alarm.objects.create(
                sort=0,
                control_code="control001",
                desc="old",
                detail_desc="",
                alarm_type="detection",
                alarm_level=1,
                algorithm_code="a",
                object_code="b",
                recognition_region="",
                class_thresh=0.5,
                overlap_thresh=0.5,
                min_interval=0,
                stream_code="s",
                stream_app="live",
                stream_name="cam",
                stream_url="",
                video_path=old_video_rel,
                image_path=old_image_rel,
                extra_images="",
                metadata="",
                draw_type=1,
                handled=False,
                state=0,
            )
            Alarm.objects.filter(id=old_alarm.id).update(create_time=timezone.now() - timedelta(days=3))

            # Recent alarm (should be kept)
            recent_rel_dir = "alarm/control001/20260226010101_87654321"
            recent_video_rel = f"{recent_rel_dir}/main.mp4"
            os.makedirs(os.path.join(upload_dir, recent_rel_dir), exist_ok=True)
            with open(os.path.join(upload_dir, recent_video_rel), "wb") as f:
                f.write(b"demo")

            recent_alarm = Alarm.objects.create(
                sort=0,
                control_code="control001",
                desc="recent",
                detail_desc="",
                alarm_type="detection",
                alarm_level=1,
                algorithm_code="a",
                object_code="b",
                recognition_region="",
                class_thresh=0.5,
                overlap_thresh=0.5,
                min_interval=0,
                stream_code="s",
                stream_app="live",
                stream_name="cam",
                stream_url="",
                video_path=recent_video_rel,
                image_path="",
                extra_images="",
                metadata="",
                draw_type=1,
                handled=False,
                state=0,
            )
            Alarm.objects.filter(id=recent_alarm.id).update(create_time=timezone.now() - timedelta(hours=2))

            from app.utils.AlarmDataCleaner import cleanup_alarm_data

            cfg = SimpleNamespace(uploadDir=upload_dir, storageRootPath=upload_dir)
            deleted_count, kept_count = cleanup_alarm_data(cfg)

            self.assertEqual(deleted_count, 1)
            self.assertEqual(kept_count, 1)

            self.assertFalse(Alarm.objects.filter(id=old_alarm.id).exists())
            self.assertTrue(Alarm.objects.filter(id=recent_alarm.id).exists())

            self.assertFalse(os.path.exists(os.path.join(upload_dir, old_rel_dir)))
            self.assertTrue(os.path.exists(os.path.join(upload_dir, recent_rel_dir)))

    def test_retention_cleanup_preserves_recent_file_in_shared_directory(self):
        self._enable_one_day_retention()
        with tempfile.TemporaryDirectory() as upload_root:
            shared_dir = "alarm/control-shared/20260711"
            old_rel = f"{shared_dir}/old.mp4"
            recent_rel = f"{shared_dir}/recent.mp4"
            old_path = self._write_media(upload_root, old_rel, b"old")
            recent_path = self._write_media(upload_root, recent_rel, b"recent")
            old_alarm = self._create_alarm(
                control_code="old-shared",
                video_path=old_rel,
                age=timedelta(days=3),
            )
            recent_alarm = self._create_alarm(
                control_code="recent-shared",
                video_path=recent_rel,
                age=timedelta(hours=2),
            )

            from app.utils.AlarmDataCleaner import cleanup_alarm_data

            config = SimpleNamespace(uploadDir=upload_root, storageRootPath=upload_root)
            deleted_count, remaining_count = cleanup_alarm_data(config)

            self.assertEqual((deleted_count, remaining_count), (1, 1))
            self.assertFalse(Alarm.objects.filter(id=old_alarm.id).exists())
            self.assertTrue(Alarm.objects.filter(id=recent_alarm.id).exists())
            self.assertFalse(os.path.exists(old_path))
            self.assertTrue(os.path.isfile(recent_path))

    def test_retention_cleanup_keeps_row_when_file_remove_fails(self):
        self._enable_one_day_retention()
        with tempfile.TemporaryDirectory() as upload_root:
            relative_path = "alarm/control-retention/20260711/old.mp4"
            absolute_path = self._write_media(upload_root, relative_path, b"retention")
            alarm = self._create_alarm(
                control_code="retention-remove-failure",
                video_path=relative_path,
                age=timedelta(days=3),
            )

            from app.utils.AlarmDataCleaner import cleanup_alarm_data

            config = SimpleNamespace(uploadDir=upload_root, storageRootPath=upload_root)
            with mock.patch(
                "app.utils.AlarmDataCleaner.os.remove",
                side_effect=OSError("remove failed"),
            ):
                deleted_count, remaining_count = cleanup_alarm_data(config)

            self.assertEqual((deleted_count, remaining_count), (0, 1))
            self.assertTrue(Alarm.objects.filter(id=alarm.id).exists())
            self.assertTrue(os.path.isfile(absolute_path))

    def test_quota_cleanup_deletes_only_old_file_needed_in_shared_directory(self):
        with tempfile.TemporaryDirectory() as upload_root:
            shared_dir = "alarm/control-quota/20260711"
            old_rel = f"{shared_dir}/old.mp4"
            recent_rel = f"{shared_dir}/recent.mp4"
            old_path = self._write_media(upload_root, old_rel, b"123456")
            recent_path = self._write_media(upload_root, recent_rel, b"abcd")
            old_alarm = self._create_alarm(
                control_code="quota-old",
                video_path=old_rel,
                age=timedelta(days=3),
            )
            recent_alarm = self._create_alarm(
                control_code="quota-recent",
                video_path=recent_rel,
                age=timedelta(hours=2),
            )

            from app.utils.StorageQuotaCleaner import cleanup_alarm_data_by_quota

            config = SimpleNamespace(uploadDir=upload_root, storageRootPath=upload_root)
            result = cleanup_alarm_data_by_quota(config, max_bytes=4)

            self.assertEqual(result["deleted_rows"], 1)
            self.assertEqual(result["after_bytes"], 4)
            self.assertFalse(Alarm.objects.filter(id=old_alarm.id).exists())
            self.assertTrue(Alarm.objects.filter(id=recent_alarm.id).exists())
            self.assertFalse(os.path.exists(old_path))
            self.assertTrue(os.path.isfile(recent_path))

    def test_quota_cleanup_counts_distinct_upload_and_storage_alarm_roots(self):
        with tempfile.TemporaryDirectory() as upload_root, tempfile.TemporaryDirectory() as storage_root:
            old_rel = "alarm/control-upload/20260711/old.mp4"
            recent_rel = "alarm/control-storage/20260711/recent.mp4"
            old_path = self._write_media(upload_root, old_rel, b"123456")
            recent_path = self._write_media(storage_root, recent_rel, b"abcd")
            old_alarm = self._create_alarm(
                control_code="quota-upload-old",
                video_path=old_rel,
                age=timedelta(days=3),
            )
            recent_alarm = self._create_alarm(
                control_code="quota-storage-recent",
                video_path=recent_rel,
                age=timedelta(hours=2),
            )

            from app.utils.StorageQuotaCleaner import cleanup_alarm_data_by_quota

            config = SimpleNamespace(
                uploadDir=upload_root,
                storageRootPath=storage_root,
                alarmStoragePath=os.path.join(storage_root, "alarm"),
            )
            result = cleanup_alarm_data_by_quota(config, max_bytes=4)

            self.assertEqual(result["before_bytes"], 10)
            self.assertEqual(result["after_bytes"], 4)
            self.assertEqual(result["deleted_rows"], 1)
            self.assertFalse(Alarm.objects.filter(id=old_alarm.id).exists())
            self.assertTrue(Alarm.objects.filter(id=recent_alarm.id).exists())
            self.assertFalse(os.path.exists(old_path))
            self.assertTrue(os.path.isfile(recent_path))

    def test_quota_cleanup_skips_rows_without_reclaimable_bytes(self):
        with tempfile.TemporaryDirectory() as upload_root:
            database_only_alarm = self._create_alarm(
                control_code="quota-database-only",
                video_path="",
                age=timedelta(days=5),
            )
            missing_file_alarm = self._create_alarm(
                control_code="quota-missing-file",
                video_path="alarm/control-missing/20260711/missing.mp4",
                age=timedelta(days=4),
            )
            backed_rel = "alarm/control-backed/20260711/backed.mp4"
            backed_path = self._write_media(upload_root, backed_rel, b"123456")
            backed_alarm = self._create_alarm(
                control_code="quota-file-backed",
                video_path=backed_rel,
                age=timedelta(days=3),
            )

            from app.utils.StorageQuotaCleaner import cleanup_alarm_data_by_quota

            config = SimpleNamespace(uploadDir=upload_root, storageRootPath=upload_root)
            result = cleanup_alarm_data_by_quota(config, max_bytes=1)

            self.assertEqual(result["before_bytes"], 6)
            self.assertEqual(result["after_bytes"], 0)
            self.assertEqual(result["deleted_rows"], 1)
            self.assertEqual(result["remaining_rows"], 2)
            self.assertTrue(Alarm.objects.filter(id=database_only_alarm.id).exists())
            self.assertTrue(Alarm.objects.filter(id=missing_file_alarm.id).exists())
            self.assertFalse(Alarm.objects.filter(id=backed_alarm.id).exists())
            self.assertFalse(os.path.exists(backed_path))

    def test_quota_cleanup_keeps_row_when_file_remove_fails(self):
        with tempfile.TemporaryDirectory() as upload_root:
            relative_path = "alarm/control-quota/20260711/old.mp4"
            absolute_path = self._write_media(upload_root, relative_path, b"quota")
            alarm = self._create_alarm(
                control_code="quota-remove-failure",
                video_path=relative_path,
                age=timedelta(days=3),
            )

            from app.utils.StorageQuotaCleaner import cleanup_alarm_data_by_quota

            config = SimpleNamespace(uploadDir=upload_root, storageRootPath=upload_root)
            with mock.patch(
                "app.utils.AlarmDataCleaner.os.remove",
                side_effect=OSError("remove failed"),
            ):
                result = cleanup_alarm_data_by_quota(config, max_bytes=1)

            self.assertEqual(result["deleted_rows"], 0)
            self.assertTrue(Alarm.objects.filter(id=alarm.id).exists())
            self.assertTrue(os.path.isfile(absolute_path))

    def test_quota_cleanup_keeps_row_when_file_disappears_before_remove(self):
        with tempfile.TemporaryDirectory() as upload_root:
            relative_path = "alarm/control-quota/20260711/disappeared.mp4"
            absolute_path = self._write_media(upload_root, relative_path, b"quota")
            alarm = self._create_alarm(
                control_code="quota-disappeared-file",
                video_path=relative_path,
                age=timedelta(days=3),
            )

            from app.utils.StorageQuotaCleaner import cleanup_alarm_data_by_quota

            real_remove = os.remove

            def disappear_before_remove(path):
                real_remove(path)
                raise FileNotFoundError(path)

            config = SimpleNamespace(uploadDir=upload_root, storageRootPath=upload_root)
            with mock.patch(
                "app.utils.AlarmDataCleaner.os.remove",
                side_effect=disappear_before_remove,
            ):
                result = cleanup_alarm_data_by_quota(config, max_bytes=1)

            self.assertEqual(result["deleted_rows"], 0)
            self.assertEqual(result["after_bytes"], 0)
            self.assertTrue(Alarm.objects.filter(id=alarm.id).exists())
            self.assertFalse(os.path.exists(absolute_path))
