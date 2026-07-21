import asyncio
import json
from datetime import datetime
from unittest import mock

from django.test import TransactionTestCase

from app.models import Alarm, AlarmSound, Control
from app.ws import alarm_poll_websocket


class AlarmWebSocketTest(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        sound = AlarmSound.objects.create(name="Custom", file_path="/static/sounds/custom.mp3")
        Control.objects.create(
            user_id=1,
            sort=0,
            code="CTRL_WS",
            stream_app="live",
            stream_name="cam01",
            stream_video="video",
            stream_audio="audio",
            algorithm_code="on_yolov8n_80",
            object_code="person",
            polygon="0.1,0.1,0.9,0.1,0.9,0.9,0.1,0.9",
            min_interval=1,
            class_thresh=0.5,
            overlap_thresh=0.5,
            remark="t",
            push_stream=False,
            push_stream_app=None,
            push_stream_name=None,
            state=0,
            alarm_sound_id=sound.id,
        )

        self.alarm1 = Alarm.objects.create(
            sort=0,
            control_code="CTRL_WS",
            algorithm_code="ALG_WS_A",
            desc="a1",
            video_path="alarm/a1.mp4",
            state=0,
        )
        Alarm.objects.filter(id=self.alarm1.id).update(create_time=datetime(2026, 3, 9, 10, 0, 0))

    def _run_alarm_ws(self, *, query_string="", user=None, stop_after=1, after_initial=None):
        async def _scenario():
            sent = []
            receive_queue = asyncio.Queue()
            await receive_queue.put({"type": "websocket.connect"})

            async def receive():
                return await receive_queue.get()

            async def send(message):
                sent.append(message)
                if after_initial and len(sent) == 2:
                    after_initial()

            scope = {
                "type": "websocket",
                "path": "/ws/alarm/poll",
                "query_string": str(query_string or "").encode("utf-8"),
                "headers": [],
            }
            with mock.patch("app.ws._get_scope_session_user", return_value=user):
                task = asyncio.create_task(alarm_poll_websocket(scope, receive, send))
                try:
                    deadline = asyncio.get_running_loop().time() + 3
                    while len(sent) < int(stop_after) and not task.done():
                        if asyncio.get_running_loop().time() > deadline:
                            break
                        await asyncio.sleep(0.01)
                finally:
                    if not task.done():
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
            return sent

        return asyncio.run(_scenario())

    def test_anonymous_websocket_connect_is_rejected(self):
        sent = self._run_alarm_ws(user=None, stop_after=1)
        self.assertEqual(sent, [{"type": "websocket.close", "code": 4401}])

    def test_authenticated_websocket_connect_sends_initial_summary(self):
        sent = self._run_alarm_ws(
            query_string=f"after_id={self.alarm1.id - 1}&interval_ms=250",
            user={"id": 1, "username": "admin"},
            stop_after=2,
        )
        self.assertEqual(sent[0], {"type": "websocket.accept"})
        payload = json.loads(sent[1].get("text") or "{}")
        self.assertEqual(payload.get("type"), "alarm.poll")
        data = payload.get("data") or {}
        self.assertEqual(int(data.get("new_count") or 0), 1)
        self.assertEqual(int(data.get("newest_id") or 0), self.alarm1.id)
        self.assertEqual(data.get("sound_url"), "/static/sounds/custom.mp3")

    def test_authenticated_websocket_pushes_incremental_update(self):
        created = {}

        def _create_alarm():
            alarm2 = Alarm.objects.create(
                sort=0,
                control_code="CTRL_WS",
                algorithm_code="ALG_WS_B",
                desc="a2",
                video_path="alarm/a2.mp4",
                state=0,
            )
            Alarm.objects.filter(id=alarm2.id).update(create_time=datetime(2026, 3, 9, 10, 5, 0))
            created["id"] = alarm2.id

        sent = self._run_alarm_ws(
            query_string=f"after_id={self.alarm1.id}&interval_ms=250",
            user={"id": 1, "username": "admin"},
            stop_after=3,
            after_initial=_create_alarm,
        )
        initial = json.loads(sent[1].get("text") or "{}")
        self.assertEqual(int((initial.get("data") or {}).get("new_count") or 0), 0)

        pushed = json.loads(sent[2].get("text") or "{}")
        data = pushed.get("data") or {}
        self.assertEqual(int(data.get("new_count") or 0), 1)
        self.assertEqual(int(data.get("newest_id") or 0), created["id"])
