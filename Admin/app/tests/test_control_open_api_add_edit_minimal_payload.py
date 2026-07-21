import json
from unittest import mock

from django.db import DatabaseError
from django.test import TestCase

from app.models import Alarm, Control, ControlLog
from app.utils.Security import validate_control_code


class ControlOpenApiAddEditMinimalPayloadTest(TestCase):
    def _assert_public_failure_is_redacted(self, value, secret):
        text = str(value or "")
        self.assertNotIn(secret, text)
        self.assertNotIn("\r", text)
        self.assertNotIn("\n", text)

    def _assert_warning_args_are_line_safe(self, warning):
        self.assertTrue(warning.called)
        for warning_call in warning.call_args_list:
            for value in warning_call.args[1:]:
                text = str(value)
                self.assertNotIn("\r", text)
                self.assertNotIn("\n", text)

    def _create_alarm_for_control(self, control_code):
        return Alarm.objects.create(
            sort=0,
            control_code=control_code,
            desc="control cleanup alarm",
            state=0,
        )

    def _create_control_for_delete(self, code):
        return Control.objects.create(
            user_id=0,
            sort=0,
            code=code,
            stream_app="live",
            stream_name="cam-delete",
            stream_video="video",
            stream_audio="audio",
            algorithm_code="alg-1",
            object_code="person",
            polygon="",
            min_interval=1,
            class_thresh=0.5,
            overlap_thresh=0.5,
            remark="",
            patrol_enabled=False,
            push_stream=False,
        )

    def _delete_control(
        self,
        code,
        analyzer_result,
        *,
        alarm_cleanup_result=(True, "关联告警清理成功"),
    ):
        cancel_kwargs = (
            {"side_effect": analyzer_result}
            if isinstance(analyzer_result, Exception)
            else {"return_value": analyzer_result}
        )
        with mock.patch(
            "app.views.ControlView.g_analyzer.control_cancel", **cancel_kwargs
        ), mock.patch(
            "app.views.ControlView._remove_control_related_alarms",
            return_value=alarm_cleanup_result,
        ) as remove_alarms, mock.patch(
            "app.views.ControlView.logger.warning"
        ) as warning:
            response = self.client.post("/control/openDel", data={"code": code})
        self.assertEqual(response.status_code, 200, msg=response.content)
        return json.loads(response.content.decode("utf-8")), remove_alarms, warning

    def test_control_code_validation_rejects_path_traversal(self):
        self.assertEqual(validate_control_code("abc_DEF-123"), "abc_DEF-123")
        for value in ("../x", "..\\x", "a/b", "a\\b", "a:b", ".hidden"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_control_code(value)

    def test_post_add_control_allows_minimal_payload_without_session(self):
        """
        Cluster / machine callers should be able to create a Control via /api/postAddControl
        without relying on a logged-in web session, and without sending all optional fields.
        """
        res = self.client.post(
            "/api/postAddControl",
            data={
                "controlCode": "ctrl-new-1",
                "streamApp": "live",
                "streamName": "cam-1",
                "streamVideo": "video",
                "streamAudio": "audio",
                "algorithmCode": "alg-1",
                "objectCode": "person",
                # intentionally omit: polygon/pushStream/minInterval/classThresh/overlapThresh/remark...
            },
        )
        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        control = Control.objects.get(code="ctrl-new-1")
        self.assertEqual(control.user_id, 0)
        self.assertEqual(control.stream_app, "live")
        self.assertEqual(control.stream_name, "cam-1")
        self.assertEqual(control.algorithm_code, "alg-1")
        self.assertEqual(control.object_code, "person")
        self.assertEqual(control.polygon, "")
        self.assertEqual(control.remark, "")
        self.assertEqual(control.min_interval, 180)
        self.assertEqual(control.class_thresh, 0.5)
        self.assertEqual(control.overlap_thresh, 0.5)
        self.assertTrue(control.push_stream)

    def test_post_edit_control_allows_partial_update(self):
        """
        Cluster / machine callers should be able to partially update a Control (PATCH-like)
        by only sending the fields they want to change.
        """
        Control.objects.create(
            user_id=0,
            sort=0,
            code="ctrl-edit-1",
            stream_app="live",
            stream_name="cam-1",
            stream_video="video",
            stream_audio="audio",
            algorithm_code="alg-1",
            object_code="person",
            polygon="0,0,1,0,1,1,0,1",
            min_interval=1,
            class_thresh=0.6,
            overlap_thresh=0.7,
            remark="old",
            patrol_enabled=False,
            push_stream=True,
            push_stream_app="analyzer",
            push_stream_name="ctrl-edit-1",
            state=0,
        )

        res = self.client.post(
            "/api/postEditControl",
            data={
                "controlCode": "ctrl-edit-1",
                "remark": "new-remark",
            },
        )

        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        updated = Control.objects.get(code="ctrl-edit-1")
        self.assertEqual(updated.remark, "new-remark")
        # Keep existing values when params are omitted.
        self.assertTrue(updated.push_stream)
        self.assertEqual(updated.min_interval, 1)
        self.assertEqual(updated.class_thresh, 0.6)
        self.assertEqual(updated.overlap_thresh, 0.7)

    def test_post_add_control_persists_push_video_fps_with_range_clamp(self):
        res = self.client.post(
            "/api/postAddControl",
            data={
                "controlCode": "ctrl-fps-add-1",
                "streamApp": "live",
                "streamName": "cam-fps-1",
                "streamVideo": "video",
                "streamAudio": "audio",
                "algorithmCode": "alg-1",
                "objectCode": "person",
                "pushVideoFps": "75",
            },
        )
        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        control = Control.objects.get(code="ctrl-fps-add-1")
        self.assertEqual(control.push_video_fps, 60)

    def test_post_edit_control_updates_push_video_fps_with_range_clamp(self):
        Control.objects.create(
            user_id=0,
            sort=0,
            code="ctrl-fps-edit-1",
            stream_app="live",
            stream_name="cam-1",
            stream_video="video",
            stream_audio="audio",
            algorithm_code="alg-1",
            object_code="person",
            polygon="0,0,1,0,1,1,0,1",
            min_interval=1,
            class_thresh=0.6,
            overlap_thresh=0.7,
            remark="old",
            patrol_enabled=False,
            push_stream=True,
            push_stream_app="analyzer",
            push_stream_name="ctrl-fps-edit-1",
            push_video_fps=25,
            state=0,
        )

        res = self.client.post(
            "/api/postEditControl",
            data={
                "controlCode": "ctrl-fps-edit-1",
                "pushVideoFps": "10",
            },
        )

        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        updated = Control.objects.get(code="ctrl-fps-edit-1")
        self.assertEqual(updated.push_video_fps, 13)

    def test_delete_keeps_control_when_analyzer_cancel_is_not_confirmed(self):
        failure_results = (
            RuntimeError("analyzer offline"),
            (False, "cancel rejected"),
            (False, "prefix there is no such control suffix"),
            (False, "the control does not exist"),
            (False, "There is no such control"),
            (False, " there is no such control "),
            (False, "there is no\nsuch control"),
            (False, "there is  no such control"),
        )
        for index, result in enumerate(failure_results):
            with self.subTest(result=result):
                code = f"ctrl-delete-failure-{index}"
                self._create_control_for_delete(code)
                body, remove_alarms, warning = self._delete_control(code, result)

                self.assertEqual(body.get("code"), 0, msg=body)
                self.assertTrue(Control.objects.filter(code=code).exists())
                remove_alarms.assert_not_called()
                warning.assert_called_once()

    def test_delete_keeps_control_when_analyzer_cancel_response_is_malformed(self):
        malformed_results = (
            None,
            (True,),
            {"code": 1000, "msg": "success"},
            (1, "success"),
            (True, 1000),
            [True, "success"],
            (True, "success", "extra"),
        )
        for index, result in enumerate(malformed_results):
            with self.subTest(result=result):
                code = f"ctrl-delete-malformed-{index}"
                self._create_control_for_delete(code)
                body, remove_alarms, warning = self._delete_control(code, result)

                self.assertEqual(body.get("code"), 0, msg=body)
                self.assertTrue(Control.objects.filter(code=code).exists())
                remove_alarms.assert_not_called()
                warning.assert_called_once()

    def test_delete_accepts_confirmed_or_idempotent_analyzer_cancel(self):
        successful_results = (
            (False, "there is no such control"),
            (True, "control is running, cancel success"),
        )
        for index, result in enumerate(successful_results):
            with self.subTest(result=result):
                code = f"ctrl-delete-success-{index}"
                self._create_control_for_delete(code)
                body, remove_alarms, warning = self._delete_control(code, result)

                self.assertEqual(body.get("code"), 1000, msg=body)
                self.assertFalse(Control.objects.filter(code=code).exists())
                remove_alarms.assert_called_once_with(code)
                warning.assert_not_called()

    def test_delete_keeps_control_when_related_alarm_cleanup_fails(self):
        cleanup_results = (
            {"side_effect": (True, False)},
            {"side_effect": (True, OSError("storage unavailable"))},
        )
        for index, cleanup_result in enumerate(cleanup_results):
            with self.subTest(cleanup_result=cleanup_result):
                code = f"ctrl-delete-alarm-failure-{index}"
                self._create_control_for_delete(code)
                alarms = [self._create_alarm_for_control(code) for _unused in range(3)]
                with mock.patch(
                    "app.views.ControlView.g_analyzer.control_cancel",
                    return_value=(True, "cancel success"),
                ), mock.patch(
                    "app.views.ControlView.f_removeAlarmAndStorage",
                    **cleanup_result,
                ) as remove_alarm, mock.patch.object(
                    Control,
                    "delete",
                    autospec=True,
                    return_value=(1, {"app.Control": 1}),
                ) as delete_control, mock.patch(
                    "app.views.ControlView.logger.warning"
                ) as warning:
                    response = self.client.post("/control/openDel", data={"code": code})

                body = json.loads(response.content.decode("utf-8"))
                self.assertEqual(body.get("code"), 0, msg=body)
                self.assertTrue(Control.objects.filter(code=code).exists())
                self.assertEqual(
                    remove_alarm.call_args_list,
                    [
                        mock.call(alarm_id=alarms[0].id),
                        mock.call(alarm_id=alarms[1].id),
                    ],
                )
                delete_control.assert_not_called()
                warning.assert_called_once()
                control_log = ControlLog.objects.get(control_code=code, action="delete")
                self.assertEqual(control_log.result_code, 0)
                self.assertIn("关联告警清理", control_log.result_msg)

    def test_delete_removes_control_after_all_related_alarms_are_cleaned(self):
        code = "ctrl-delete-alarm-success"
        self._create_control_for_delete(code)
        alarms = [self._create_alarm_for_control(code) for _unused in range(2)]

        def remove_alarm_row(*, alarm_id):
            Alarm.objects.filter(id=alarm_id).delete()
            return True

        with mock.patch(
            "app.views.ControlView.g_analyzer.control_cancel",
            return_value=(True, "cancel success"),
        ), mock.patch(
            "app.views.ControlView.f_removeAlarmAndStorage",
            side_effect=remove_alarm_row,
        ) as remove_alarm:
            response = self.client.post("/control/openDel", data={"code": code})

        body = json.loads(response.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)
        self.assertFalse(Control.objects.filter(code=code).exists())
        self.assertEqual(
            remove_alarm.call_args_list,
            [
                mock.call(alarm_id=alarms[0].id),
                mock.call(alarm_id=alarms[1].id),
            ],
        )

    def test_delete_keeps_control_when_alarm_cleanup_raises_unexpectedly(self):
        code = "ctrl-delete-cleanup-exception"
        self._create_control_for_delete(code)
        with mock.patch(
            "app.views.ControlView.g_analyzer.control_cancel",
            return_value=(True, "cancel success"),
        ), mock.patch(
            "app.views.ControlView._remove_control_related_alarms",
            side_effect=RuntimeError("cleanup crashed"),
        ), mock.patch.object(
            Control,
            "delete",
            autospec=True,
        ) as delete_control, mock.patch(
            "app.views.ControlView.logger.warning"
        ) as warning:
            response = self.client.post("/control/openDel", data={"code": code})

        body = json.loads(response.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 0, msg=body)
        self.assertTrue(Control.objects.filter(code=code).exists())
        delete_control.assert_not_called()
        warning.assert_called_once()

    def test_delete_reports_failure_when_control_row_was_not_deleted(self):
        code = "ctrl-delete-row-remains"
        self._create_control_for_delete(code)
        with mock.patch(
            "app.views.ControlView.g_analyzer.control_cancel",
            return_value=(True, "cancel success"),
        ), mock.patch(
            "app.views.ControlView._remove_control_related_alarms",
            return_value=(True, "关联告警清理成功0条"),
        ), mock.patch.object(
            Control,
            "delete",
            autospec=True,
            return_value=(1, {"app.Control": 1}),
        ) as delete_control, mock.patch(
            "app.views.ControlView.logger.warning"
        ) as warning:
            response = self.client.post("/control/openDel", data={"code": code})

        body = json.loads(response.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 0, msg=body)
        self.assertTrue(Control.objects.filter(code=code).exists())
        delete_control.assert_called_once()
        warning.assert_called_once()

    def test_delete_keeps_control_when_related_alarm_query_fails(self):
        secret = "ALARM_DB_SECRET"
        query_failures = (
            ("query", DatabaseError(f"{secret}\r\ndatabase unavailable")),
            ("iteration", RuntimeError(f"{secret}\r\nquery iteration failed")),
        )
        for index, (failure_stage, error) in enumerate(query_failures):
            with self.subTest(failure_stage=failure_stage):
                code = f"ctrl-delete-alarm-query-failure-{index}"
                self._create_control_for_delete(code)
                alarm_ids = mock.MagicMock()
                alarm_ids.__iter__.side_effect = error

                with mock.patch(
                    "app.views.ControlView.g_analyzer.control_cancel",
                    return_value=(True, "cancel success"),
                ), mock.patch(
                    "app.views.ControlView.Alarm.objects.filter"
                ) as filter_alarms, mock.patch.object(
                    Control,
                    "delete",
                    autospec=True,
                    return_value=(1, {"app.Control": 1}),
                ) as delete_control, mock.patch(
                    "app.views.ControlView.logger.warning"
                ) as warning:
                    if failure_stage == "query":
                        filter_alarms.side_effect = error
                    else:
                        filter_alarms.return_value.order_by.return_value.values_list.return_value = alarm_ids
                    response = self.client.post("/control/openDel", data={"code": code})

                body = json.loads(response.content.decode("utf-8"))
                self.assertEqual(body.get("code"), 0, msg=body)
                self.assertTrue(Control.objects.filter(code=code).exists())
                delete_control.assert_not_called()
                self._assert_public_failure_is_redacted(body.get("msg"), secret)
                self._assert_warning_args_are_line_safe(warning)
                control_log = ControlLog.objects.get(control_code=code, action="delete")
                self.assertEqual(control_log.result_code, 0)
                self._assert_public_failure_is_redacted(control_log.result_msg, secret)

    def test_delete_keeps_control_for_malformed_alarm_cleanup_results(self):
        malformed_results = (
            None,
            (True,),
            (1, "success"),
            (True, 1000),
            [True, "success"],
            (True, "success", "extra"),
        )
        for index, result in enumerate(malformed_results):
            with self.subTest(result=result):
                code = f"ctrl-delete-cleanup-malformed-{index}"
                self._create_control_for_delete(code)
                with mock.patch(
                    "app.views.ControlView.g_analyzer.control_cancel",
                    return_value=(True, "cancel success"),
                ), mock.patch(
                    "app.views.ControlView._remove_control_related_alarms",
                    return_value=result,
                ) as remove_alarms, mock.patch.object(
                    Control,
                    "delete",
                    autospec=True,
                ) as delete_control, mock.patch(
                    "app.views.ControlView.logger.warning"
                ) as warning:
                    response = self.client.post("/control/openDel", data={"code": code})

                body = json.loads(response.content.decode("utf-8"))
                self.assertEqual(body.get("code"), 0, msg=body)
                self.assertTrue(Control.objects.filter(code=code).exists())
                remove_alarms.assert_called_once_with(code)
                delete_control.assert_not_called()
                warning.assert_called_once()

    def test_delete_rolls_back_control_when_confirmation_query_fails(self):
        secret = "CONTROL_CONFIRM_SECRET"
        code = "ctrl-delete-confirm-query-failure"
        self._create_control_for_delete(code)
        with mock.patch(
            "app.views.ControlView.g_analyzer.control_cancel",
            return_value=(True, "cancel success"),
        ), mock.patch(
            "app.views.ControlView._remove_control_related_alarms",
            return_value=(True, "关联告警清理成功0条"),
        ), mock.patch.object(
            Control.objects,
            "filter",
            side_effect=DatabaseError(f"{secret}\r\nconfirmation failed"),
        ), mock.patch(
            "app.views.ControlView.logger.warning"
        ) as warning:
            response = self.client.post("/control/openDel", data={"code": code})

        body = json.loads(response.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 0, msg=body)
        self.assertTrue(Control.objects.filter(code=code).exists())
        self._assert_public_failure_is_redacted(body.get("msg"), secret)
        control_log = ControlLog.objects.get(control_code=code, action="delete")
        self._assert_public_failure_is_redacted(control_log.result_msg, secret)
        self._assert_warning_args_are_line_safe(warning)

    def test_delete_rejects_late_alarm_created_during_cleanup(self):
        code = "ctrl-delete-late-alarm"
        self._create_control_for_delete(code)
        original_alarm = self._create_alarm_for_control(code)
        late_alarms = []

        def remove_and_inject_late_alarm(*, alarm_id):
            Alarm.objects.filter(id=alarm_id).delete()
            late_alarms.append(self._create_alarm_for_control(code))
            return True

        with mock.patch(
            "app.views.ControlView.g_analyzer.control_cancel",
            return_value=(True, "cancel success"),
        ), mock.patch(
            "app.views.ControlView.f_removeAlarmAndStorage",
            side_effect=remove_and_inject_late_alarm,
        ), mock.patch(
            "app.views.ControlView.logger.warning"
        ) as warning:
            response = self.client.post("/control/openDel", data={"code": code})

        body = json.loads(response.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 0, msg=body)
        self.assertTrue(Control.objects.filter(code=code).exists())
        self.assertFalse(Alarm.objects.filter(id=original_alarm.id).exists())
        self.assertEqual(len(late_alarms), 1)
        self.assertTrue(Alarm.objects.filter(id=late_alarms[0].id).exists())
        warning.assert_called_once()
        control_log = ControlLog.objects.get(control_code=code, action="delete")
        self.assertEqual(control_log.result_code, 0)

    def test_delete_redacts_analyzer_failure_details(self):
        secret = "ANALYZER_SECRET"
        failures = (
            RuntimeError(f"{secret}\r\ntransport failed"),
            (False, f"{secret}\r\nrequest rejected"),
        )
        for index, failure in enumerate(failures):
            with self.subTest(failure=failure):
                code = f"ctrl-delete-analyzer-secret-{index}"
                self._create_control_for_delete(code)
                body, remove_alarms, warning = self._delete_control(code, failure)

                self.assertEqual(body.get("code"), 0, msg=body)
                self.assertTrue(Control.objects.filter(code=code).exists())
                remove_alarms.assert_not_called()
                self._assert_public_failure_is_redacted(body.get("msg"), secret)
                control_log = ControlLog.objects.get(control_code=code, action="delete")
                self._assert_public_failure_is_redacted(control_log.result_msg, secret)
                self._assert_warning_args_are_line_safe(warning)
