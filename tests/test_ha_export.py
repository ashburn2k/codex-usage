import unittest
from datetime import date as real_date
from unittest.mock import patch

import ha_export


SAMPLE_DATA = {
    "generated_at": "2026-06-01 10:00:00",
    "daily_by_model": [
        {
            "day": "2026-06-01",
            "model": "codex/custom",
            "input": 100,
            "output": 20,
            "cache_read": 300,
            "cache_creation": 0,
            "reasoning": 10,
            "turns": 2,
        },
        {
            "day": "2026-05-28",
            "model": "codex/custom",
            "input": 40,
            "output": 10,
            "cache_read": 50,
            "cache_creation": 0,
            "reasoning": 5,
            "turns": 1,
        },
        {
            "day": "2026-04-01",
            "model": "unknown",
            "input": 7,
            "output": 3,
            "cache_read": 0,
            "cache_creation": 0,
            "reasoning": 0,
            "turns": 1,
        },
    ],
    "hourly_by_model": [
        {
            "day": "2026-06-01",
            "hour": 9,
            "model": "codex/custom",
            "output": 20,
            "turns": 2,
        },
        {
            "day": "2026-05-28",
            "hour": 14,
            "model": "codex/custom",
            "output": 10,
            "turns": 1,
        },
    ],
    "sessions_all": [
        {
            "session_id": "today",
            "project": "Documents/codex",
            "last_date": "2026-06-01",
            "turns": 2,
            "input": 100,
            "output": 20,
            "cache_read": 300,
            "reasoning": 10,
        },
        {
            "session_id": "week",
            "project": "Documents/codex",
            "last_date": "2026-05-28",
            "turns": 1,
            "input": 40,
            "output": 10,
            "cache_read": 50,
            "reasoning": 5,
        },
        {
            "session_id": "old",
            "project": "old/project",
            "last_date": "2026-04-01",
            "turns": 1,
            "input": 7,
            "output": 3,
            "cache_read": 0,
            "reasoning": 0,
        },
    ],
}


class TestHomeAssistantExport(unittest.TestCase):
    @patch("ha_export.date")
    def test_totals_for_today(self, mock_date):
        mock_date.today.return_value = real_date(2026, 6, 1)
        mock_date.side_effect = lambda *args, **kwargs: real_date(*args, **kwargs)

        totals = ha_export.totals_for_range(SAMPLE_DATA, "Today", 1)

        self.assertEqual(totals["turns"], 2)
        self.assertEqual(totals["sessions"], 1)
        self.assertEqual(totals["projects"], 1)
        self.assertEqual(totals["total_tokens"], 430)

    @patch("ha_export.date")
    def test_build_payload_contains_expected_ranges(self, mock_date):
        mock_date.today.return_value = real_date(2026, 6, 1)
        mock_date.side_effect = lambda *args, **kwargs: real_date(*args, **kwargs)

        payload = ha_export.build_payload(SAMPLE_DATA)

        self.assertEqual(payload["source"], "codex-usage")
        self.assertEqual(payload["ranges"]["today"]["total_tokens"], 430)
        self.assertEqual(payload["ranges"]["seven_days"]["total_tokens"], 535)
        self.assertEqual(payload["ranges"]["all_time"]["total_tokens"], 545)
        self.assertEqual(payload["top_projects_30d"][0]["project"], "Documents/codex")
        self.assertEqual(payload["charts"]["range_label"], "30 days")
        self.assertEqual(payload["charts"]["daily_30d"][0]["day"], "2026-05-28")
        self.assertEqual(payload["charts"]["daily_30d"][1]["total_tokens"], 430)
        self.assertEqual(payload["charts"]["daily_by_model_30d"][0]["model"], "codex/custom")
        self.assertEqual(payload["charts"]["hourly_30d"]["day_count"], 2)
        self.assertEqual(payload["charts"]["models_30d"][0]["total_tokens"], 535)
        self.assertEqual(payload["charts"]["projects_30d"][0]["total_tokens"], 535)


if __name__ == "__main__":
    unittest.main()
