from django.test import SimpleTestCase

from app.views.ControlView import _stable_process_index


class StableProcessIndexTest(SimpleTestCase):
    def test_legacy_shard_mapping_is_stable_across_upgrades(self):
        cases = (
            ("control-alpha", 7, 0),
            ("control-beta", 7, 3),
            ("", 7, 4),
            ("控制-01", 11, 8),
        )

        for control_code, process_count, expected in cases:
            with self.subTest(control_code=control_code, process_count=process_count):
                self.assertEqual(
                    _stable_process_index(control_code, process_count),
                    expected,
                )

    def test_single_or_invalid_process_count_uses_process_zero(self):
        for process_count in (None, "invalid", -1, 0, 1):
            with self.subTest(process_count=process_count):
                self.assertEqual(_stable_process_index("control-alpha", process_count), 0)
