import json
import os
import tempfile
from contextlib import contextmanager
from unittest import mock

from django.db import DatabaseError
from django.test import TestCase

from app.models import Alarm
from app.views import ViewsBase


class AlarmWorkflowApiTest(TestCase):
    @contextmanager
    def _configured_storage(self, upload_root, storage_root=None):
        with mock.patch.object(ViewsBase.g_config, "uploadDir", upload_root), mock.patch.object(
            ViewsBase.g_config,
            "storageRootPath",
            storage_root or upload_root,
        ):
            yield

    @staticmethod
    def _write_media(root, relative_path, content=b"alarm-media"):
        absolute_path = os.path.join(root, *relative_path.split("/"))
        os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
        with open(absolute_path, "wb") as file_obj:
            file_obj.write(content)
        return absolute_path

    def _login(self, username="operator1"):
        session = self.client.session
        session["user"] = {
            "id": 1,
            "username": username,
            "email": f"{username}@example.com",
        }
        session.save()

    def _create_alarm(self, *, desc="workflow alarm", **overrides):
        values = {
            "sort": 0,
            "control_code": "ctrl-workflow",
            "desc": desc,
            "detail_desc": f"{desc} detail",
            "alarm_type": "intrusion",
            "algorithm_code": "alg-workflow",
            "stream_code": "stream-workflow",
            "stream_app": "live",
            "stream_name": "cam-workflow",
            "state": 0,
            "handled": False,
        }
        values.update(overrides)
        return Alarm.objects.create(**values)

    def _post_transition(self, alarm_id, transition):
        res = self.client.post(
            "/alarm/workflow",
            data={"alarm_ids_str": str(alarm_id), "transition": transition},
        )
        self.assertEqual(res.status_code, 200, msg=res.content)
        return json.loads(res.content.decode("utf-8"))

    def test_acknowledge_transition_marks_alarm_as_acknowledged(self):
        self._login("triage-a")
        alarm = self._create_alarm(desc="ack me")

        payload = self._post_transition(alarm.id, "acknowledge")
        self.assertEqual(payload.get("code"), 1000, msg=str(payload))

        alarm.refresh_from_db()
        self.assertEqual(alarm.workflow_status, "acknowledged")
        self.assertEqual(alarm.workflow_updated_by, "triage-a")
        self.assertIsNotNone(alarm.workflow_updated_at)
        self.assertFalse(alarm.handled)

    def test_false_positive_transition_closes_alarm_as_false_positive(self):
        self._login("triage-b")
        alarm = self._create_alarm(desc="false positive")
        self._post_transition(alarm.id, "acknowledge")

        payload = self._post_transition(alarm.id, "false_positive")
        self.assertEqual(payload.get("code"), 1000, msg=str(payload))

        alarm.refresh_from_db()
        self.assertEqual(alarm.workflow_status, "false_positive")
        self.assertTrue(alarm.handled)
        self.assertEqual(alarm.handled_by, "triage-b")
        self.assertIsNotNone(alarm.handled_time)

    def test_closed_transition_marks_alarm_closed(self):
        self._login("triage-c")
        alarm = self._create_alarm(desc="close me")
        self._post_transition(alarm.id, "acknowledge")

        payload = self._post_transition(alarm.id, "closed")
        self.assertEqual(payload.get("code"), 1000, msg=str(payload))

        alarm.refresh_from_db()
        self.assertEqual(alarm.workflow_status, "closed")
        self.assertTrue(alarm.handled)
        self.assertEqual(alarm.handled_by, "triage-c")

    def test_reopened_transition_reopens_closed_alarm(self):
        self._login("triage-d")
        alarm = self._create_alarm(desc="reopen me")
        self._post_transition(alarm.id, "acknowledge")
        self._post_transition(alarm.id, "closed")

        payload = self._post_transition(alarm.id, "reopen")
        self.assertEqual(payload.get("code"), 1000, msg=str(payload))

        alarm.refresh_from_db()
        self.assertEqual(alarm.workflow_status, "acknowledged")
        self.assertFalse(alarm.handled)
        self.assertIsNone(alarm.handled_time)
        self.assertEqual(alarm.handled_by, "")
        self.assertEqual(alarm.workflow_updated_by, "triage-d")

    def test_invalid_transition_returns_error_without_mutating_alarm(self):
        self._login("triage-e")
        alarm = self._create_alarm(desc="invalid transition")

        payload = self._post_transition(alarm.id, "reopen")
        self.assertEqual(payload.get("code"), 0, msg=str(payload))
        self.assertIn("invalid workflow transition", payload.get("msg", ""))

        alarm.refresh_from_db()
        self.assertEqual(alarm.workflow_status, "new")
        self.assertFalse(alarm.handled)

    def test_alarm_cleanup_deletes_only_referenced_files_in_shared_directory(self):
        with tempfile.TemporaryDirectory() as upload_root:
            relative_dir = "alarm/ctrl-workflow/20260710"
            first_image = self._write_media(upload_root, f"{relative_dir}/first.jpg")
            first_video = self._write_media(upload_root, f"{relative_dir}/first.mp4")
            first_extra = self._write_media(upload_root, f"{relative_dir}/first-extra.jpg")
            second_image = self._write_media(upload_root, f"{relative_dir}/second.jpg")

            first_alarm = self._create_alarm(
                image_path=f"{relative_dir}/first.jpg",
                video_path=f"{relative_dir}/first.mp4",
                extra_images=json.dumps([f"{relative_dir}/first-extra.jpg"]),
            )
            second_alarm = self._create_alarm(
                image_path=f"{relative_dir}/second.jpg",
            )

            with self._configured_storage(upload_root):
                result = ViewsBase.f_remove_alarm_and_storage(first_alarm.id)

            self.assertTrue(result)
            self.assertFalse(Alarm.objects.filter(id=first_alarm.id).exists())
            self.assertFalse(os.path.exists(first_image))
            self.assertFalse(os.path.exists(first_video))
            self.assertFalse(os.path.exists(first_extra))
            self.assertTrue(os.path.isfile(second_image))
            self.assertTrue(Alarm.objects.filter(id=second_alarm.id).exists())

    def test_alarm_cleanup_keeps_alarm_on_remove_failure_and_can_retry(self):
        with tempfile.TemporaryDirectory() as upload_root:
            relative_path = "alarm/ctrl-workflow/20260710/retry.jpg"
            absolute_path = self._write_media(upload_root, relative_path, b"retry")
            alarm = self._create_alarm(image_path=relative_path)

            with self._configured_storage(upload_root):
                with mock.patch(
                    "app.utils.AlarmDataCleaner.os.remove",
                    side_effect=OSError("denied"),
                ):
                    first_result = ViewsBase.f_remove_alarm_and_storage(alarm.id)
                second_result = ViewsBase.f_remove_alarm_and_storage(alarm.id)

            self.assertFalse(first_result)
            self.assertTrue(second_result)
            self.assertFalse(Alarm.objects.filter(id=alarm.id).exists())
            self.assertFalse(os.path.exists(absolute_path))

    def test_alarm_cleanup_confirms_database_row_was_deleted(self):
        with tempfile.TemporaryDirectory() as upload_root:
            alarm = self._create_alarm()
            with self._configured_storage(upload_root), mock.patch.object(
                Alarm,
                "delete",
                autospec=True,
                return_value=(1, {"app.Alarm": 1}),
            ):
                result = ViewsBase.f_remove_alarm_and_storage(alarm.id)

            self.assertFalse(result)
            self.assertTrue(Alarm.objects.filter(id=alarm.id).exists())

    def test_alarm_cleanup_rolls_back_when_confirmation_query_fails(self):
        secret = "ALARM_CONFIRM_SECRET"
        alarm = self._create_alarm()
        with tempfile.TemporaryDirectory() as upload_root, self._configured_storage(
            upload_root
        ), mock.patch.object(
            Alarm.objects,
            "filter",
            side_effect=DatabaseError(f"{secret}\r\nconfirmation failed"),
        ), mock.patch(
            "app.utils.AlarmDataCleaner.logger.warning"
        ) as warning:
            result = ViewsBase.f_remove_alarm_and_storage(alarm.id)

        self.assertFalse(result)
        self.assertTrue(Alarm.objects.filter(id=alarm.id).exists())
        self.assertTrue(warning.called)
        for warning_call in warning.call_args_list:
            for value in warning_call.args[1:]:
                self.assertNotIn("\r", str(value))
                self.assertNotIn("\n", str(value))

    def test_alarm_cleanup_escapes_file_failure_log_and_keeps_row(self):
        secret = "ALARM_FILE_SECRET"
        with tempfile.TemporaryDirectory() as upload_root:
            relative_path = "alarm/ctrl-workflow/20260711/log-failure.jpg"
            absolute_path = self._write_media(upload_root, relative_path)
            alarm = self._create_alarm(image_path=relative_path)

            with self._configured_storage(upload_root), mock.patch(
                "app.utils.AlarmDataCleaner.os.remove",
                side_effect=OSError(f"{secret}\r\nremove failed"),
            ), mock.patch(
                "app.utils.AlarmDataCleaner.logger.warning"
            ) as warning:
                result = ViewsBase.f_remove_alarm_and_storage(alarm.id)

            self.assertFalse(result)
            self.assertTrue(Alarm.objects.filter(id=alarm.id).exists())
            self.assertTrue(os.path.isfile(absolute_path))
            self.assertTrue(warning.called)
            for warning_call in warning.call_args_list:
                for value in warning_call.args[1:]:
                    self.assertNotIn("\r", str(value))
                    self.assertNotIn("\n", str(value))

    def test_alarm_cleanup_supports_video_only_and_database_only_alarms(self):
        with tempfile.TemporaryDirectory() as upload_root:
            relative_video = "alarm/ctrl-workflow/20260710/video-only.mp4"
            absolute_video = self._write_media(upload_root, relative_video, b"video")
            video_alarm = self._create_alarm(video_path=relative_video)
            database_only_alarm = self._create_alarm()

            with self._configured_storage(upload_root):
                video_result = ViewsBase.f_remove_alarm_and_storage(video_alarm.id)
                database_only_result = ViewsBase.f_remove_alarm_and_storage(database_only_alarm.id)

            self.assertTrue(video_result)
            self.assertTrue(database_only_result)
            self.assertFalse(os.path.exists(absolute_video))
            self.assertFalse(Alarm.objects.filter(id=video_alarm.id).exists())
            self.assertFalse(Alarm.objects.filter(id=database_only_alarm.id).exists())

    def test_alarm_cleanup_database_only_does_not_require_storage_root(self):
        alarm = self._create_alarm()
        with mock.patch.object(ViewsBase.g_config, "uploadDir", ""), mock.patch.object(
            ViewsBase.g_config,
            "storageRootPath",
            "",
        ):
            result = ViewsBase.f_remove_alarm_and_storage(alarm.id)

        self.assertTrue(result)
        self.assertFalse(Alarm.objects.filter(id=alarm.id).exists())

    def test_alarm_cleanup_rejects_malformed_or_unsafe_media_paths(self):
        cases = (
            {"extra_images": "not-json"},
            {"extra_images": json.dumps({"path": "alarm/a.jpg"})},
            {"extra_images": json.dumps([123])},
            {"extra_images": json.dumps(["../outside.jpg"])},
            {"image_path": "../outside.jpg"},
        )
        with tempfile.TemporaryDirectory() as upload_root, self._configured_storage(upload_root):
            for index, values in enumerate(cases):
                with self.subTest(values=values):
                    alarm = self._create_alarm(desc=f"unsafe-{index}", **values)
                    result = ViewsBase.f_remove_alarm_and_storage(alarm.id)

                    self.assertFalse(result)
                    self.assertTrue(Alarm.objects.filter(id=alarm.id).exists())

    def test_alarm_cleanup_uses_unique_configured_storage_root(self):
        relative_path = "alarm/ctrl-workflow/20260710/stored.jpg"
        with tempfile.TemporaryDirectory() as upload_root, tempfile.TemporaryDirectory() as storage_root:
            storage_path = self._write_media(storage_root, relative_path, b"stored")
            stored_alarm = self._create_alarm(image_path=relative_path)

            with self._configured_storage(upload_root, storage_root):
                stored_result = ViewsBase.f_remove_alarm_and_storage(stored_alarm.id)
                self.assertTrue(stored_result)
                self.assertFalse(os.path.exists(storage_path))
                self.assertFalse(Alarm.objects.filter(id=stored_alarm.id).exists())

                duplicate_upload_path = os.path.join(upload_root, *relative_path.split("/"))
                duplicate_storage_path = os.path.join(storage_root, *relative_path.split("/"))
                self._write_media(upload_root, relative_path, b"duplicate")
                self._write_media(storage_root, relative_path, b"duplicate")
                duplicate_alarm = self._create_alarm(image_path=relative_path)
                duplicate_result = ViewsBase.f_remove_alarm_and_storage(duplicate_alarm.id)

            self.assertFalse(duplicate_result)
            self.assertTrue(Alarm.objects.filter(id=duplicate_alarm.id).exists())
            self.assertTrue(os.path.isfile(duplicate_upload_path))
            self.assertTrue(os.path.isfile(duplicate_storage_path))

    def test_manual_alarm_delete_reports_partial_failure(self):
        self._login("delete-operator")
        with mock.patch(
            "app.views.api.f_removeAlarmAndStorage",
            side_effect=(True, False),
        ):
            response = self.client.post(
                "/api/postHandleAlarm",
                data={"handle": "delete", "alarm_ids_str": "101,102"},
            )

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 0, msg=payload)
        self.assertIn("删除成功1条", payload.get("msg", ""))
        self.assertIn("删除失败1条", payload.get("msg", ""))

    def test_manual_alarm_delete_ignores_empty_items_between_ids(self):
        self._login("delete-gap-operator")
        with mock.patch(
            "app.views.api.f_removeAlarmAndStorage",
            side_effect=(True, False),
        ) as remove_alarm:
            response = self.client.post(
                "/api/postHandleAlarm",
                data={"handle": "delete", "alarm_ids_str": "101,,102"},
            )

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 0, msg=payload)
        self.assertIn("删除成功1条", payload.get("msg", ""))
        self.assertIn("删除失败1条", payload.get("msg", ""))
        self.assertEqual(remove_alarm.call_args_list, [mock.call(101), mock.call(102)])

    def test_manual_alarm_delete_rejects_empty_id_list_without_cleanup(self):
        self._login("delete-empty-operator")
        with mock.patch(
            "app.views.api.f_removeAlarmAndStorage",
            return_value=True,
        ) as remove_alarm:
            response = self.client.post(
                "/api/postHandleAlarm",
                data={"handle": "delete", "alarm_ids_str": " , , "},
            )

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 0, msg=payload)
        self.assertIn("列表为空", payload.get("msg", ""))
        remove_alarm.assert_not_called()

    def test_manual_alarm_delete_rejects_non_numeric_ids_without_cleanup(self):
        self._login("delete-invalid-operator")
        with mock.patch(
            "app.views.api.f_removeAlarmAndStorage",
            return_value=True,
        ) as remove_alarm:
            response = self.client.post(
                "/api/postHandleAlarm",
                data={"handle": "delete", "alarm_ids_str": "101,bad"},
            )

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 0, msg=payload)
        self.assertIn("格式错误", payload.get("msg", ""))
        remove_alarm.assert_not_called()

    def test_manual_alarm_delete_counts_helper_exception_and_escapes_log_lines(self):
        self._login("delete-exception-operator")
        with mock.patch(
            "app.views.api.f_removeAlarmAndStorage",
            side_effect=(True, RuntimeError("storage failed\r\nforged log line")),
        ) as remove_alarm, mock.patch(
            "app.views.api.logger.warning"
        ) as warning:
            response = self.client.post(
                "/api/postHandleAlarm",
                data={"handle": "delete", "alarm_ids_str": "101,102"},
            )

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 0, msg=payload)
        self.assertIn("删除成功1条", payload.get("msg", ""))
        self.assertIn("删除失败1条", payload.get("msg", ""))
        self.assertEqual(remove_alarm.call_args_list, [mock.call(101), mock.call(102)])
        warning.assert_called_once()
        dynamic_log_args = warning.call_args.args[1:]
        self.assertTrue(dynamic_log_args)
        for value in dynamic_log_args:
            self.assertNotIn("\r", value)
            self.assertNotIn("\n", value)
        self.assertIn("\\r\\n", dynamic_log_args[-1])
