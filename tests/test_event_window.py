import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.event_window import (  # noqa: E402
    DEFAULT_EVENT_PAGE_LIMIT,
    MAX_EVENT_PAGE_LIMIT,
    parse_window,
    window_response,
)


class EventWindowTests(unittest.TestCase):
    def test_tail_returns_last_limit_events(self):
        start, end = parse_window({"tail": ["1"], "limit": ["160"]}, 1000)
        self.assertEqual((start, end), (840, 1000))

    def test_before_is_strictly_before_position(self):
        start, end = parse_window({"before": ["500"], "limit": ["200"]}, 1000)
        self.assertEqual((start, end), (300, 500))

    def test_since_starts_at_unread_position(self):
        start, end = parse_window({"since": ["800"]}, 1000)
        self.assertEqual((start, end), (800, 1000))

    def test_adjacent_before_pages_do_not_overlap(self):
        first_start, first_end = parse_window({"tail": ["1"], "limit": ["200"]}, 1000)
        second_start, second_end = parse_window(
            {"before": [str(first_start)], "limit": ["200"]}, 1000)
        self.assertEqual((second_start, second_end), (first_start - 200, first_start))
        self.assertEqual(first_start, 800)
        self.assertEqual(second_end, first_start)

    def test_limit_is_clamped_to_safe_ceiling(self):
        _, end = parse_window({"since": ["0"], "limit": ["9999"]}, 1000)
        self.assertEqual(end, 1000)
        start, end = parse_window({"tail": ["1"], "limit": ["9999"]}, 1000)
        self.assertEqual(end - start, MAX_EVENT_PAGE_LIMIT)
        self.assertEqual(end - start, 200)

    def test_limit_defaults_to_80(self):
        start, end = parse_window({"tail": ["1"]}, 1000)
        self.assertEqual(end - start, DEFAULT_EVENT_PAGE_LIMIT)

    def test_invalid_inputs_fall_back_safely(self):
        start, end = parse_window({}, 1000)
        self.assertEqual((start, end), (0, 1000))
        start, end = parse_window({"before": ["abc"], "limit": ["xyz"]}, 1000)
        self.assertEqual((start, end), (920, 1000))
        start, end = parse_window({"since": ["-5"]}, 100)
        self.assertEqual((start, end), (0, 100))
        start, end = parse_window({"since": ["999999"]}, 100)
        self.assertEqual((start, end), (100, 100))

    def test_window_response_contract(self):
        payload = window_response(
            [{"seq": 840}, {"seq": 841}], 840, 842, 1000,
            scope_id="task-1", scope_key="taskId")
        self.assertEqual(payload["taskId"], "task-1")
        self.assertEqual(payload["eventStart"], 840)
        self.assertEqual(payload["eventEnd"], 842)
        self.assertEqual(payload["eventTotal"], 1000)
        self.assertTrue(payload["eventHasMore"])
        self.assertEqual(payload["nextCursor"], 842)

    def test_window_response_first_page_has_no_more(self):
        payload = window_response([], 0, 0, 0, scope_id="run-1")
        self.assertFalse(payload["eventHasMore"])
        self.assertEqual(payload["nextCursor"], 0)


if __name__ == "__main__":
    unittest.main()
