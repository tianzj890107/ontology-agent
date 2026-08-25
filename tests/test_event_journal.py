import json
import sys
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

import open_claude.event_journal as journal  # noqa: E402


def _write_lines(path, count, prefix="e", start=0):
    with open(path, "w", encoding="utf-8") as fh:
        for index in range(start, start + count):
            fh.write(json.dumps(
                {"seq": index, "type": "thinking", "text": f"{prefix}{index}"},
                ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")


class EventJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "events.jsonl")
        self.lock = threading.RLock()

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_line_and_count(self):
        for index in range(10):
            journal.append_line(self.path, {"seq": index, "type": "t"}, lock=self.lock)
        self.assertEqual(journal.count_valid_lines(self.path, lock=self.lock), 10)
        self.assertEqual(journal.last_valid_seq(self.path, lock=self.lock), 9)

    def test_tail_reads_only_last_events(self):
        _write_lines(self.path, 500)
        tail = journal.tail_events(self.path, 3, lock=self.lock)
        self.assertEqual([event["seq"] for event in tail], [497, 498, 499])

    def test_truncated_last_line_is_ignored(self):
        _write_lines(self.path, 10)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write('{"seq": 10, "type": "partial"')
        self.assertEqual(journal.count_valid_lines(self.path, lock=self.lock), 10)
        self.assertEqual(journal.last_valid_seq(self.path, lock=self.lock), 9)
        tail = journal.tail_events(self.path, 3, lock=self.lock)
        self.assertEqual([event["seq"] for event in tail], [7, 8, 9])
        earlier = journal.read_range(self.path, 0, 5, lock=self.lock)
        self.assertEqual([event["seq"] for event in earlier], [0, 1, 2, 3, 4])

    def test_read_range_uses_absolute_positions(self):
        _write_lines(self.path, 1000)
        window = journal.read_range(self.path, 400, 460, lock=self.lock)
        self.assertEqual(len(window), 60)
        self.assertEqual(window[0]["seq"], 400)
        self.assertEqual(window[-1]["seq"], 459)
        empty = journal.read_range(self.path, 500, 500, lock=self.lock)
        self.assertEqual(empty, [])

    def test_read_range_ending_at_eof_does_not_rebuild_index(self):
        # tail/since reads use ``end == total``, i.e. the window ends exactly
        # at journal EOF; that must complete from the existing index instead
        # of triggering a full rebuild (which would parse the whole journal).
        _write_lines(self.path, 10_000)
        journal.rebuild_index(self.path, lock=self.lock)
        with patch.object(journal, "rebuild_index") as mocked:
            window = journal.read_range(self.path, 9_000, 10_000, lock=self.lock)
            mocked.assert_not_called()
        self.assertEqual(len(window), 1000)
        self.assertEqual(window[0]["seq"], 9_000)
        self.assertEqual(window[-1]["seq"], 9_999)
        with patch.object(journal, "rebuild_index") as mocked:
            delta = journal.read_range(self.path, 9_990, 10_000, lock=self.lock)
            mocked.assert_not_called()
        self.assertEqual([event["seq"] for event in delta], list(range(9_990, 10_000)))

    def test_seed_is_idempotent(self):
        events = [{"seq": 0, "type": "user", "text": "a"},
                  {"seq": 1, "type": "assistant", "text": "b"}]
        self.assertTrue(journal.seed(self.path, events, lock=self.lock))
        self.assertFalse(journal.seed(self.path, events, lock=self.lock))
        self.assertEqual(journal.count_valid_lines(self.path, lock=self.lock), 2)

    def test_index_rebuild_is_idempotent(self):
        _write_lines(self.path, 300)
        journal.rebuild_index(self.path, lock=self.lock)
        first = journal.read_range(self.path, 100, 120, lock=self.lock)
        journal.rebuild_index(self.path, lock=self.lock)
        second = journal.read_range(self.path, 100, 120, lock=self.lock)
        self.assertEqual([event["seq"] for event in first],
                         [event["seq"] for event in second])

    def test_tail_does_not_parse_whole_journal(self):
        # 430k simulated events: the tail page must parse only the tail lines,
        # never construct 430k JSON objects.
        _write_lines(self.path, 430_000)
        parsed = {"count": 0}

        def counting_loads(raw):
            parsed["count"] += 1
            return json.loads(raw)

        with patch.object(journal, "_parse_line", side_effect=counting_loads):
            tail = journal.tail_events(self.path, 160, lock=self.lock)
        self.assertEqual(len(tail), 160)
        self.assertEqual(tail[0]["seq"], 430_000 - 160)
        self.assertLess(parsed["count"], 500)

    def test_events_do_not_mix_across_paths(self):
        other = os.path.join(self.tmp.name, "other.jsonl")
        _write_lines(self.path, 5)
        journal.append_line(other, {"seq": 0, "type": "other"}, lock=self.lock)
        self.assertEqual([event["seq"] for event in
                          journal.read_all_valid(self.path, lock=self.lock)], [0, 1, 2, 3, 4])
        self.assertEqual([event["seq"] for event in
                          journal.read_all_valid(other, lock=self.lock)], [0])


if __name__ == "__main__":
    unittest.main()
