from unittest import mock

from django.test import SimpleTestCase

from app.utils.PostgresAdvisoryLock import (
    MAX_POSTGRES_BIGINT,
    PostgresAdvisoryLock,
    validate_advisory_lock_id,
)


class PostgresAdvisoryLockTest(SimpleTestCase):
    def test_lock_uses_parameterized_sql_and_dedicated_autocommit_connection(self):
        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(True,), (1,), (True,)]
        connection = mock.Mock()
        connection.cursor.return_value = cursor
        connect = mock.Mock(return_value=connection)

        lock = PostgresAdvisoryLock(
            "postgresql://beacon:secret@database/beacon",
            42,
            application_name="beacon-test",
            connect_factory=connect,
        )
        with lock:
            self.assertTrue(lock.try_acquire())
            lock.keepalive()

        connect.assert_called_once_with(
            "postgresql://beacon:secret@database/beacon",
            connect_timeout=10,
            application_name="beacon-test",
        )
        self.assertTrue(connection.autocommit)
        self.assertEqual(
            cursor.execute.call_args_list,
            [
                mock.call("SELECT pg_try_advisory_lock(%s)", (42,)),
                mock.call("SELECT 1"),
                mock.call("SELECT pg_advisory_unlock(%s)", (42,)),
            ],
        )
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_wait_acquire_is_bounded(self):
        lock = mock.Mock()
        lock.try_acquire.side_effect = [False, False, True]
        monotonic = mock.Mock(side_effect=[0.0, 0.0, 1.0])
        sleep = mock.Mock()

        acquired = PostgresAdvisoryLock.wait_acquire(
            lock,
            5,
            poll_interval_seconds=1,
            monotonic=monotonic,
            sleep=sleep,
        )

        self.assertTrue(acquired)
        self.assertEqual(sleep.call_count, 2)

    def test_lock_id_validation_rejects_boolean_and_out_of_range(self):
        for value in (True, MAX_POSTGRES_BIGINT + 1, "not-an-integer"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_advisory_lock_id(value)
