import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

from django.test import TestCase


class _DummyConfig:
    code = "node-test-001"
    uploadDir_www = "/static/upload/"

    alarmOutboxEnabled = True

    alarmWebhookEnabled = True
    alarmWebhookUrls = ["http://example.com/webhook"]
    alarmWebhookSecret = ""
    alarmWebhookTimeoutSeconds = 3

    alarmOutboxMaxBatch = 50
    alarmOutboxRetentionHours = 72


class AlarmEventBusTest(TestCase):
    def test_dispatcher_start_resolves_publisher_before_starting_thread(self):
        from app.utils.AlarmSinkDispatcher import AlarmSinkDispatcher

        dispatcher = AlarmSinkDispatcher(_DummyConfig())
        thread = mock.Mock()

        with (
            mock.patch(
                "app.utils.AlarmSinkDispatcher._resolve_publish_alarm_event",
                create=True,
                side_effect=ImportError("publisher unavailable"),
            ),
            mock.patch("app.utils.AlarmSinkDispatcher.threading.Thread", return_value=thread),
        ):
            with self.assertRaisesRegex(ImportError, "publisher unavailable"):
                dispatcher.start()

        thread.start.assert_not_called()
        self.assertIsNone(dispatcher._thread)

    def test_failed_outbox_event_can_be_replayed_by_event_id(self):
        from app.models import AlarmEventOutbox

        row = AlarmEventOutbox.objects.create(
            event_id="evt-replay-1",
            sink_type="webhook",
            payload_json=json.dumps(
                {"schema": "beacon.event.v1", "event_id": "evt-replay-1", "event_type": "alarm.created"}
            ),
            status="failed",
            next_retry_at=None,
        )
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            response = self.client.post(
                "/open/ops/outbox/replay",
                data=json.dumps({"event_id": row.event_id}),
                content_type="application/json",
                REMOTE_ADDR="8.8.8.8",
                HTTP_X_BEACON_TOKEN="t1",
            )

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")
        self.assertIsNone(row.next_retry_at)

    def test_audio_alarm_dispatches_directly_when_outbox_disabled(self):
        from app.views import api as api_view

        alarm = SimpleNamespace(id=7, control_code="ctl-audio")
        payload = {"event": "audio-created"}
        dispatcher = mock.Mock()

        with (
            mock.patch.object(api_view.g_config, "alarmOutboxEnabled", False, create=True),
            mock.patch("app.utils.AlarmEventBus.build_alarm_created_event_for_alarm", return_value=payload),
            mock.patch("app.utils.BackgroundServices.get_alarm_sink_dispatcher", return_value=dispatcher),
        ):
            api_view._emit_alarm_created_event_best_effort(
                alarm=alarm,
                legacy_event="legacy",
                event_source="openapi",
                metadata_obj={"source": "test"},
            )

        dispatcher.enqueue.assert_called_once_with(payload)

    def test_audio_alarm_propagates_outbox_enqueue_failure(self):
        from app.utils import AlarmEventBus as event_bus
        from app.views import api as api_view

        enqueue_error_type = getattr(event_bus, "AlarmOutboxEnqueueError", None)
        self.assertIsNotNone(enqueue_error_type, "AlarmOutboxEnqueueError must be public")

        alarm = SimpleNamespace(id=17, control_code="ctl-audio-fail")
        payload = {"event_id": "evt-audio-fail"}
        enqueue_error = enqueue_error_type(event_id=payload["event_id"], sink_type="webhook")
        with (
            mock.patch.object(api_view.g_config, "alarmOutboxEnabled", True, create=True),
            mock.patch("app.utils.AlarmEventBus.build_alarm_created_event_for_alarm", return_value=payload),
            mock.patch("app.utils.AlarmEventBus.enqueue_alarm_event_outbox", side_effect=enqueue_error),
            self.assertLogs(api_view.logger.name, level="ERROR") as captured,
            self.assertRaises(enqueue_error_type),
        ):
            api_view._emit_alarm_created_event_best_effort(
                alarm=alarm,
                legacy_event="legacy",
                event_source="openapi",
                metadata_obj={"source": "test"},
            )

        diagnostic = "\n".join(captured.output)
        self.assertIn(payload["event_id"], diagnostic)
        self.assertIn(str(alarm.id), diagnostic)
        self.assertIn(alarm.control_code, diagnostic)

    def test_publish_webhook_all_empty_urls_returns_not_ok(self):
        from app.utils.AlarmSinks import publish_alarm_event_to_sink

        config = _DummyConfig()
        config.alarmWebhookEnabled = True
        config.alarmWebhookUrls = ["", "   ", "\n"]

        result = publish_alarm_event_to_sink(config, "webhook", {"schema": "beacon.event.v1", "event_id": "evt-empty"})

        self.assertEqual(result.get("ok"), False, msg=str(result))
        self.assertEqual(result.get("retriable"), True, msg=str(result))
        self.assertIn("webhook urls missing", str(result.get("error") or ""), msg=str(result))

    def test_build_alarm_created_event_contains_required_fields(self):
        from app.utils.AlarmEventBus import build_alarm_created_event

        config = _DummyConfig()
        now = datetime(2026, 2, 17, 12, 0, 0)

        payload = build_alarm_created_event(
            config,
            legacy_event="alarm_openAdd",
            event_source="openAdd",
            timestamp=now,
            alarm_id=123,
            control_code="ctrl-001",
            desc="test alarm",
            image_path="alarm/ctrl-001/20260217/img.jpg",
            video_path="alarm/ctrl-001/20260217/video.mp4",
            image_url="/static/upload/alarm/ctrl-001/20260217/img.jpg",
            video_url="/static/upload/alarm/ctrl-001/20260217/video.mp4",
            extra={
                "algorithm_code": "algo-1",
                "min_interval": 5,
            },
        )

        self.assertEqual(payload["schema"], "beacon.event.v1")
        self.assertTrue(payload["event_id"])
        self.assertEqual(payload["event_type"], "alarm.created")
        self.assertEqual(payload["event_source"], "openAdd")
        self.assertEqual(payload["timestamp"], now.isoformat())
        self.assertEqual(payload["node_code"], config.code)

        # Backward-compatible fields
        self.assertEqual(payload["event"], "alarm_openAdd")
        self.assertEqual(payload["alarm_id"], 123)
        self.assertEqual(payload["control_code"], "ctrl-001")
        self.assertEqual(payload["desc"], "test alarm")
        self.assertIn("data", payload)
        self.assertEqual(payload["data"]["alarm_id"], 123)
        self.assertEqual(payload["data"]["control_code"], "ctrl-001")
        self.assertEqual(payload["data"]["algorithm_code"], "algo-1")

    def test_build_alarm_created_event_for_alarm_preserves_upload_fields(self):
        from app.utils.AlarmEventBus import build_alarm_created_event_for_alarm

        config = _DummyConfig()
        alarm = SimpleNamespace(
            id=33,
            create_time=datetime(2026, 3, 15, 10, 30, 0),
            control_code="ctrl-upload",
            desc="upload alarm",
            alarm_type="detection",
            alarm_level=2,
            algorithm_code="alg-upload",
            object_code="person",
            recognition_region="0,0,1,1",
            region_index=0,
            class_thresh=0.6,
            overlap_thresh=0.4,
            min_interval=3,
            stream_code="stream-upload",
            stream_app="live",
            stream_name="cam-upload",
            stream_url="rtsp://example/upload",
            image_path="alarm/ctrl-upload/20260315/img.jpg",
            video_path="alarm/ctrl-upload/20260315/video.mp4",
        )

        payload = build_alarm_created_event_for_alarm(
            config,
            alarm=alarm,
            legacy_event="alarm_upload",
            event_source="uploadAlarm",
            metadata_obj={"source_device": "cam-upload-1"},
            extra_images=["alarm/ctrl-upload/20260315/extra.jpg"],
        )

        self.assertEqual(payload["event"], "alarm_upload")
        self.assertEqual(payload["event_source"], "uploadAlarm")
        self.assertEqual(payload["alarm_id"], 33)
        self.assertEqual(payload["image_url"], "/static/upload/alarm/ctrl-upload/20260315/img.jpg")
        self.assertEqual(payload["video_url"], "/static/upload/alarm/ctrl-upload/20260315/video.mp4")
        self.assertEqual(payload["data"]["alarm_type"], "detection")
        self.assertEqual(payload["data"]["alarm_level"], 2)
        self.assertEqual(payload["data"]["algorithm_code"], "alg-upload")
        self.assertEqual(payload["data"]["metadata"]["source_device"], "cam-upload-1")
        self.assertEqual(payload["data"]["extra_images"], ["alarm/ctrl-upload/20260315/extra.jpg"])

    def test_build_alarm_created_event_for_alarm_supports_audio_review_metadata(self):
        from app.utils.AlarmEventBus import build_alarm_created_event_for_alarm

        config = _DummyConfig()
        alarm = SimpleNamespace(
            id=71,
            create_time=datetime(2026, 3, 15, 11, 0, 0),
            control_code="MIC-02",
            desc="glass break detected",
            alarm_type="audio_event",
            alarm_level=1,
            algorithm_code="asr-edge",
            object_code="speech",
            recognition_region="",
            region_index=-1,
            class_thresh=0.5,
            overlap_thresh=0.5,
            min_interval=0,
            stream_code="audio-02",
            stream_app="audio",
            stream_name="lobby-mic",
            stream_url="",
            image_path="",
            video_path="",
        )

        payload = build_alarm_created_event_for_alarm(
            config,
            alarm=alarm,
            legacy_event="alarm_audio_detect",
            event_source="openAudioDetect",
            metadata_obj={
                "audio_event": {
                    "text": "glass break detected",
                    "language": "en-US",
                    "segments": [{"text": "glass break"}],
                    "source": "openapi_audio_detect",
                }
            },
        )

        self.assertEqual(payload["event"], "alarm_audio_detect")
        self.assertEqual(payload["event_source"], "openAudioDetect")
        self.assertEqual(payload["data"]["alarm_type"], "audio_event")
        self.assertEqual(payload["data"]["object_code"], "speech")
        self.assertEqual(payload["data"]["stream_name"], "lobby-mic")
        self.assertEqual(payload["data"]["metadata"]["audio_event"]["language"], "en-US")
        self.assertEqual(payload["data"]["metadata"]["audio_event"]["source"], "openapi_audio_detect")

    def test_enqueue_alarm_event_outbox_creates_row_per_enabled_sink(self):
        from app.models import AlarmEventOutbox
        from app.utils.AlarmEventBus import build_alarm_created_event, enqueue_alarm_event_outbox

        config = _DummyConfig()
        now = datetime(2026, 2, 17, 12, 0, 0)

        payload = build_alarm_created_event(
            config,
            legacy_event="alarm_upload",
            event_source="uploadAlarm",
            timestamp=now,
            alarm_id=1,
            control_code="ctrl-002",
            desc="upload alarm",
            image_path="",
            video_path="",
            image_url="",
            video_url="",
            extra=None,
        )

        created = enqueue_alarm_event_outbox(config, payload, alarm_id=1, control_code="ctrl-002")
        self.assertEqual(created, 1)
        self.assertEqual(
            enqueue_alarm_event_outbox(config, payload, alarm_id=1, control_code="ctrl-002"),
            0,
        )

        rows = list(AlarmEventOutbox.objects.all())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.sink_type, "webhook")
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.event_id, payload["event_id"])

        loaded = json.loads(row.payload_json)
        self.assertEqual(loaded["event_id"], payload["event_id"])
        self.assertEqual(loaded["event_type"], "alarm.created")

    def test_enqueue_alarm_event_outbox_exposes_database_failures(self):
        from django.db import DatabaseError, OperationalError

        from app.models import AlarmEventOutbox
        from app.utils import AlarmEventBus as event_bus

        enqueue_error_type = getattr(event_bus, "AlarmOutboxEnqueueError", None)
        self.assertIsNotNone(enqueue_error_type, "AlarmOutboxEnqueueError must be public")
        payload = {"event_id": "evt-db-fail", "event_type": "alarm.created"}

        for db_error_type in (OperationalError, DatabaseError):
            with self.subTest(db_error_type=db_error_type.__name__):
                cause = db_error_type("database unavailable")
                with (
                    patch.object(AlarmEventOutbox.objects, "get_or_create", side_effect=cause),
                    self.assertRaises(enqueue_error_type) as captured,
                ):
                    event_bus.enqueue_alarm_event_outbox(
                        _DummyConfig(), payload, alarm_id=23, control_code="ctrl-db-fail"
                    )
                self.assertIs(captured.exception.__cause__, cause)
                self.assertIn(payload["event_id"], str(captured.exception))
                self.assertIn("webhook", str(captured.exception))

        programming_error = ValueError("bad defaults")
        with (
            patch.object(AlarmEventOutbox.objects, "get_or_create", side_effect=programming_error),
            self.assertRaises(ValueError) as captured,
        ):
            event_bus.enqueue_alarm_event_outbox(
                _DummyConfig(), payload, alarm_id=23, control_code="ctrl-db-fail"
            )
        self.assertIs(captured.exception, programming_error)

    def test_outbox_dispatcher_terminal_fails_invalid_payload_without_publishing(self):
        from app.models import AlarmEventOutbox
        from app.utils.AlarmOutboxDispatcher import AlarmOutboxDispatcher

        config = _DummyConfig()
        invalid_payloads = ("{not-json", json.dumps([{"event_id": "evt-array"}]))

        for index, payload_json in enumerate(invalid_payloads):
            with self.subTest(payload_json=payload_json):
                outbox = AlarmEventOutbox.objects.create(
                    event_id=f"evt-poison-{index}",
                    sink_type="webhook",
                    payload_json=payload_json,
                    status="pending",
                )
                with patch("app.utils.AlarmSinks.publish_alarm_event_to_sink") as publisher:
                    processed = AlarmOutboxDispatcher(config).dispatch_once()

                self.assertEqual(processed, 1)
                publisher.assert_not_called()
                outbox.refresh_from_db()
                self.assertEqual(outbox.status, "failed")
                self.assertEqual(outbox.attempts, 1)
                self.assertIsNone(outbox.next_retry_at)
                self.assertIn("invalid payload", outbox.last_error.lower())

    def test_outbox_dispatcher_webhook_4xx_is_permanent_failure(self):
        from app.models import AlarmEventOutbox

        config = _DummyConfig()
        config.alarmWebhookEnabled = True
        config.alarmWebhookUrls = ["http://example.com/webhook"]

        outbox = AlarmEventOutbox.objects.create(
            event_id="evt-1",
            sink_type="webhook",
            schema="beacon.event.v1",
            event_type="alarm.created",
            event_source="openAdd",
            alarm_id=1,
            control_code="ctrl-1",
            payload_json=json.dumps({"schema": "beacon.event.v1", "event_id": "evt-1", "event_type": "alarm.created"}),
            status="pending",
        )

        class _Resp:
            status_code = 400

            def __init__(self):
                self.content = b"bad request"

        with patch("requests.post", return_value=_Resp()):
            from app.utils.AlarmOutboxDispatcher import AlarmOutboxDispatcher

            d = AlarmOutboxDispatcher(config)
            processed = d.dispatch_once()
            self.assertEqual(processed, 1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, "failed")
        self.assertEqual(outbox.attempts, 1)
        self.assertEqual(outbox.last_http_status, 400)
        self.assertIsNone(outbox.next_retry_at)

    def test_outbox_dispatcher_webhook_5xx_is_retryable(self):
        from app.models import AlarmEventOutbox

        config = _DummyConfig()
        config.alarmWebhookEnabled = True
        config.alarmWebhookUrls = ["http://example.com/webhook"]

        outbox = AlarmEventOutbox.objects.create(
            event_id="evt-2",
            sink_type="webhook",
            schema="beacon.event.v1",
            event_type="alarm.created",
            event_source="openAdd",
            alarm_id=2,
            control_code="ctrl-2",
            payload_json=json.dumps({"schema": "beacon.event.v1", "event_id": "evt-2", "event_type": "alarm.created"}),
            status="pending",
        )

        class _Resp:
            status_code = 500

            def __init__(self):
                self.content = b"server error"

        with patch("requests.post", return_value=_Resp()):
            from app.utils.AlarmOutboxDispatcher import AlarmOutboxDispatcher

            d = AlarmOutboxDispatcher(config)
            processed = d.dispatch_once()
            self.assertEqual(processed, 1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, "failed")
        self.assertEqual(outbox.attempts, 1)
        self.assertEqual(outbox.last_http_status, 500)
        self.assertIsNotNone(outbox.next_retry_at)

    def test_outbox_dispatcher_does_not_overwrite_newer_attempt(self):
        """
        Guard against stale-writer race:
        - worker A claims attempt=1 (status=sending)
        - worker B later re-claims attempt=2
        - worker A finishes late and must NOT overwrite attempt=2 state
        """
        from app.models import AlarmEventOutbox

        config = _DummyConfig()
        config.alarmOutboxEnabled = True
        config.alarmOutboxMaxBatch = 1

        outbox = AlarmEventOutbox.objects.create(
            event_id="evt-race-1",
            sink_type="webhook",
            schema="beacon.event.v1",
            event_type="alarm.created",
            event_source="openAdd",
            alarm_id=20,
            control_code="ctrl-race-1",
            payload_json=json.dumps({"schema": "beacon.event.v1", "event_id": "evt-race-1", "event_type": "alarm.created"}),
            status="pending",
        )

        def _publish_side_effect(_config, _sink_type, _event):
            AlarmEventOutbox.objects.filter(id=outbox.id).update(status="sending", attempts=2)
            return {"ok": True, "retriable": False, "http_status": 200, "error": ""}

        with patch("app.utils.AlarmSinks.publish_alarm_event_to_sink", side_effect=_publish_side_effect):
            from app.utils.AlarmOutboxDispatcher import AlarmOutboxDispatcher

            d = AlarmOutboxDispatcher(config)
            processed = d.dispatch_once()
            self.assertEqual(processed, 1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.attempts, 2)
        self.assertEqual(outbox.status, "sending")
        self.assertIsNone(outbox.sent_at)

    def test_outbox_dispatcher_uses_finish_now_for_sent_at(self):
        from app.models import AlarmEventOutbox

        config = _DummyConfig()
        config.alarmOutboxEnabled = True
        config.alarmOutboxMaxBatch = 1

        outbox = AlarmEventOutbox.objects.create(
            event_id="evt-now-sent-1",
            sink_type="webhook",
            schema="beacon.event.v1",
            event_type="alarm.created",
            event_source="openAdd",
            alarm_id=30,
            control_code="ctrl-now-sent-1",
            payload_json=json.dumps({"schema": "beacon.event.v1", "event_id": "evt-now-sent-1", "event_type": "alarm.created"}),
            status="pending",
        )

        # NOTE: Project uses USE_TZ=False (naive datetimes in SQLite tests).
        batch_now = datetime(2026, 2, 17, 12, 0, 0)
        claim_now = datetime(2026, 2, 17, 12, 0, 10)
        finish_now = datetime(2026, 2, 17, 12, 0, 20)

        with patch("app.utils.AlarmOutboxDispatcher.timezone.now", side_effect=[batch_now, claim_now, finish_now]):
            with patch(
                "app.utils.AlarmSinks.publish_alarm_event_to_sink",
                return_value={"ok": True, "retriable": False, "http_status": 200, "error": ""},
            ):
                from app.utils.AlarmOutboxDispatcher import AlarmOutboxDispatcher

                d = AlarmOutboxDispatcher(config)
                processed = d.dispatch_once()
                self.assertEqual(processed, 1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, "sent")
        self.assertEqual(outbox.sent_at, finish_now)
        self.assertEqual(outbox.update_time, finish_now)

    def test_outbox_dispatcher_uses_finish_now_for_next_retry_at(self):
        from app.models import AlarmEventOutbox

        config = _DummyConfig()
        config.alarmOutboxEnabled = True
        config.alarmOutboxMaxBatch = 1

        outbox = AlarmEventOutbox.objects.create(
            event_id="evt-now-retry-1",
            sink_type="webhook",
            schema="beacon.event.v1",
            event_type="alarm.created",
            event_source="openAdd",
            alarm_id=31,
            control_code="ctrl-now-retry-1",
            payload_json=json.dumps({"schema": "beacon.event.v1", "event_id": "evt-now-retry-1", "event_type": "alarm.created"}),
            status="pending",
        )

        # NOTE: Project uses USE_TZ=False (naive datetimes in SQLite tests).
        batch_now = datetime(2026, 2, 17, 12, 1, 0)
        claim_now = datetime(2026, 2, 17, 12, 1, 10)
        finish_now = datetime(2026, 2, 17, 12, 1, 20)

        with patch("app.utils.AlarmOutboxDispatcher.timezone.now", side_effect=[batch_now, claim_now, finish_now]):
            with patch(
                "app.utils.AlarmSinks.publish_alarm_event_to_sink",
                return_value={"ok": False, "retriable": True, "http_status": 0, "error": "transient"},
            ):
                from app.utils.AlarmOutboxDispatcher import AlarmOutboxDispatcher

                d = AlarmOutboxDispatcher(config)
                processed = d.dispatch_once()
                self.assertEqual(processed, 1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, "failed")
        self.assertEqual(outbox.next_retry_at, finish_now + timedelta(seconds=2))

    def test_outbox_dispatcher_reclaims_stuck_sending(self):
        from django.utils import timezone
        from app.models import AlarmEventOutbox

        config = _DummyConfig()
        config.alarmOutboxEnabled = True
        config.alarmOutboxMaxBatch = 1

        AlarmEventOutbox.objects.create(
            event_id="evt-pending-1",
            sink_type="webhook",
            schema="beacon.event.v1",
            event_type="alarm.created",
            event_source="openAdd",
            alarm_id=10,
            control_code="ctrl-pending-1",
            payload_json=json.dumps({"schema": "beacon.event.v1", "event_id": "evt-pending-1", "event_type": "alarm.created"}),
            status="pending",
        )

        stuck = AlarmEventOutbox.objects.create(
            event_id="evt-sending-stuck",
            sink_type="webhook",
            schema="beacon.event.v1",
            event_type="alarm.created",
            event_source="openAdd",
            alarm_id=11,
            control_code="ctrl-sending-stuck",
            payload_json=json.dumps({"schema": "beacon.event.v1", "event_id": "evt-sending-stuck", "event_type": "alarm.created"}),
            status="sending",
        )

        AlarmEventOutbox.objects.filter(id=stuck.id).update(update_time=timezone.now() - timedelta(hours=1))

        from app.utils.AlarmOutboxDispatcher import AlarmOutboxDispatcher

        d = AlarmOutboxDispatcher(config)
        processed = d.dispatch_once()
        self.assertEqual(processed, 1)

        stuck.refresh_from_db()
        self.assertEqual(stuck.status, "failed")
        self.assertIsNotNone(stuck.next_retry_at)
        self.assertIn("sending timeout reclaimed", stuck.last_error)

    def test_api_upload_alarm_creates_outbox_when_enabled(self):
        from django.test import Client
        from app.models import AlarmEventOutbox
        from app.views.ViewsBase import g_config

        # Enable the webhook sink + outbox.
        g_config.alarmOutboxEnabled = True
        g_config.alarmWebhookEnabled = True
        g_config.alarmWebhookUrls = ["http://example.com/webhook"]

        c = Client()
        res = c.post(
            "/open/alarm/upload",
            data=json.dumps(
                {
                    "control_code": "ctrl-api-001",
                    "desc": "api upload",
                }
            ),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=str(body))

        self.assertTrue(AlarmEventOutbox.objects.filter(sink_type="webhook").exists())
