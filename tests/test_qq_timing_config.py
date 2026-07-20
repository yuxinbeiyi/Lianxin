import unittest
from unittest.mock import patch

import config


class QQTimingConfigTests(unittest.TestCase):
    def test_recommended_defaults(self):
        with patch.object(config, "_load_full_config", return_value={}):
            with patch.object(config, "_save_full_config"):
                timing = config.get_qq_timing_config()

        self.assertEqual((0.5, 1.0), (
            timing["think_delay_min"], timing["think_delay_max"]
        ))
        self.assertEqual((900, 1100), (
            timing["type_speed_min"], timing["type_speed_max"]
        ))
        self.assertEqual(0.0, timing["min_reply_interval"])
        self.assertEqual((0.0, 1.0), (
            timing["global_send_interval_min"],
            timing["global_send_interval_max"],
        ))
        self.assertEqual(30, timing["daily_limit_other"])
        self.assertEqual(15, timing["cross_session_context_limit"])
        self.assertNotIn("daily_limit_owner", timing)

    def test_legacy_defaults_migrate_without_overwriting_custom_values(self):
        full = {
            "qq_bridge": {
                "timing": {
                    "think_delay_min": 2.0,
                    "think_delay_max": 5.0,
                    "type_speed_min": 65,
                    "type_speed_max": 90,
                    "segment_interval_min": 2.0,
                    "segment_interval_max": 4.0,
                    "global_send_interval_min": 5.0,
                    "global_send_interval_max": 10.0,
                    "min_reply_interval": 3.0,
                    "daily_limit_owner": 120,
                    "daily_limit_other": 30,
                    "cross_session_context_limit": 6,
                }
            }
        }
        with patch.object(config, "_load_full_config", return_value=full):
            with patch.object(config, "_save_full_config") as save:
                timing = config.get_qq_timing_config()

        self.assertEqual(2.0, timing["think_delay_min"])
        self.assertEqual(5.0, timing["think_delay_max"])
        self.assertEqual((0.1, 0.4), (
            timing["segment_interval_min"], timing["segment_interval_max"]
        ))
        self.assertNotIn("daily_limit_owner", timing)
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
