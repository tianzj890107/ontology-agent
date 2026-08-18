import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPEN_CLAUDE = ROOT / "open-claude"
sys.path.insert(0, str(OPEN_CLAUDE))

from open_claude.lifecycle import LazyService, LifecycleTracker  # noqa: E402


class LifecycleTests(unittest.TestCase):
    def test_concurrent_lazy_load_initializes_once(self):
        calls = 0
        calls_lock = threading.Lock()

        def factory():
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.03)
            return object()

        service = LazyService("test", factory)
        values = []
        threads = [threading.Thread(target=lambda: values.append(service.get())) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1)
        self.assertEqual(calls, 1)
        self.assertEqual(service.status, "READY")
        self.assertEqual(len({id(value) for value in values}), 1)

    def test_failed_lazy_load_can_retry(self):
        calls = 0

        def factory():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary")
            return "ready"

        service = LazyService("retryable", factory)
        with self.assertRaises(RuntimeError):
            service.get()
        self.assertEqual(service.status, "FAILED")
        self.assertEqual(service.retry(), "ready")
        self.assertEqual(service.status, "READY")

    def test_stage_snapshot_distinguishes_core_and_on_demand(self):
        tracker = LifecycleTracker("test")
        tracker.mark("core_ready")
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot["core"], "ready")
        self.assertEqual(snapshot["full"], "on_demand")
        self.assertIn("core_ready", snapshot["stages"])

    def test_web_server_import_does_not_load_agent_runtime(self):
        code = """
import sys
sys.path.insert(0, 'open-claude')
import oc_codex_server
assert oc_codex_server.AGENT_RUNTIME.status == 'NOT_LOADED'
assert 'open_claude.repl' not in sys.modules
assert 'open_claude.agent' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

