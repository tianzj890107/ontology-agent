"""P2: durable, expiring execution leases for 47313/47314.

Covers the shared ``execution_lease`` module (file + Redis backends) with a
fake Redis client whose ``eval`` executes the *actual* production Lua scripts
against real Redis storage structures (string token key, hash metadata,
integer fence key, TTLs).  Tests never parse JSON to fake the lease protocol.
"""
import multiprocessing
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))
sys.path.insert(0, str(ROOT / "tests"))

from fake_redis import FakeRedis  # noqa: E402
from open_claude.execution_lease import (  # noqa: E402
    CLAIM_SCRIPT,
    FileExecutionLeaseStore,
    LeaseRecord,
    RedisExecutionLeaseStore,
    RENEW_SCRIPT,
    RELEASE_SCRIPT,
    build_lease_store,
)


def _child_claim(lease_dir, task_id, owner_id, execution_id, queue):
    store = FileExecutionLeaseStore(lease_dir)
    ok, record = store.try_claim(task_id, owner_id, execution_id, lease_seconds=60)
    queue.put((ok, record.execution_id if record else ""))


def _child_race(lease_dir, task_id, owner_id, execution_id, barrier, queue):
    barrier.wait(timeout=20)
    store = FileExecutionLeaseStore(lease_dir)
    ok, record = store.try_claim(task_id, owner_id, execution_id, lease_seconds=60)
    queue.put((ok, record.execution_id if record else ""))


class FileLeaseStoreTests(unittest.TestCase):
    def test_claim_release_reclaim_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileExecutionLeaseStore(directory, lease_seconds=60)
            ok, record = store.try_claim("task-1", "owner-a", "exec-1")
            self.assertTrue(ok)
            self.assertEqual(record.execution_id, "exec-1")
            ok2, active = store.try_claim("task-1", "owner-b", "exec-2")
            self.assertFalse(ok2)
            self.assertEqual(active.execution_id, "exec-1")
            # Releasing with a wrong execution id must not clear the lease.
            self.assertFalse(store.release("task-1", "exec-2"))
            self.assertTrue(store.release("task-1", "exec-1"))
            self.assertIsNone(store.read("task-1"))
            ok3, record3 = store.try_claim("task-1", "owner-b", "exec-2")
            self.assertTrue(ok3)
            self.assertEqual(record3.execution_id, "exec-2")

    def test_fence_is_monotonic_across_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileExecutionLeaseStore(directory, lease_seconds=60)
            _, first = store.try_claim("task-1", "owner-a", "exec-1")
            store.release("task-1", "exec-1")
            _, second = store.try_claim("task-1", "owner-b", "exec-2", attempt=2)
            self.assertGreater(second.fence_token, first.fence_token)
            self.assertGreater(second.attempt, first.attempt)

    def test_renew_only_for_matching_execution(self):
        directory = tempfile.mkdtemp()
        try:
            clock = {"now": 1000.0}
            store = FileExecutionLeaseStore(directory, lease_seconds=60,
                                            clock=lambda: clock["now"])
            store.try_claim("task-1", "owner-a", "exec-1")
            first = store.read("task-1")
            self.assertFalse(store.renew("task-1", "exec-2"))
            clock["now"] = 1100.0
            self.assertTrue(store.renew("task-1", "exec-1"))
            renewed = store.read("task-1")
            self.assertGreater(renewed.lease_expires_at, first.lease_expires_at)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_expired_lease_is_reclaimed(self):
        directory = tempfile.mkdtemp()
        try:
            clock = {"now": 1000.0}
            store = FileExecutionLeaseStore(directory, lease_seconds=60,
                                            clock=lambda: clock["now"])
            store.try_claim("task-1", "owner-a", "exec-1")
            clock["now"] = 2000.0
            ok, record = store.try_claim("task-1", "owner-b", "exec-2")
            self.assertTrue(ok)
            self.assertEqual(record.execution_id, "exec-2")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_cross_process_only_one_claim_wins(self):
        ctx = multiprocessing.get_context(
            "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn")
        with tempfile.TemporaryDirectory() as directory:
            barrier = ctx.Barrier(2)
            queue = ctx.Queue()
            processes = [
                ctx.Process(target=_child_race, args=(
                    directory, "shared-task", "owner-1", "exec-1", barrier, queue)),
                ctx.Process(target=_child_race, args=(
                    directory, "shared-task", "owner-2", "exec-2", barrier, queue)),
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=30)
            for process in processes:
                self.assertEqual(process.exitcode, 0)
            results = [queue.get(timeout=5), queue.get(timeout=5)]
            winners = [execution_id for ok, execution_id in results if ok]
            self.assertEqual(len(winners), 1)
            self.assertTrue(winners[0] in ("exec-1", "exec-2"))

    def test_100_threads_only_one_claim_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileExecutionLeaseStore(directory, lease_seconds=30)
            barrier = threading.Barrier(100)
            results: list[tuple[bool, str]] = []
            results_lock = threading.Lock()

            def claim(index: int) -> None:
                barrier.wait(timeout=20)
                ok, record = store.try_claim(
                    "shared-task", f"owner-{index}", f"exec-{index}",
                    lease_seconds=30, attempt=1, status="CLAIMED", user_id="u")
                with results_lock:
                    results.append((ok, record.execution_id if record else ""))

            threads = [threading.Thread(target=claim, args=(index,))
                       for index in range(100)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            winners = [execution_id for ok, execution_id in results if ok]
            self.assertEqual(len(winners), 1)
            self.assertTrue(winners[0].startswith("exec-"))

    def test_child_claim_visible_to_parent(self):
        ctx = multiprocessing.get_context(
            "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn")
        with tempfile.TemporaryDirectory() as directory:
            queue = ctx.Queue()
            process = ctx.Process(target=_child_claim, args=(
                directory, "shared-task", "owner-child", "exec-child", queue))
            process.start()
            process.join(timeout=30)
            self.assertEqual(process.exitcode, 0)
            ok, execution_id = queue.get(timeout=5)
            self.assertTrue(ok)
            self.assertEqual(execution_id, "exec-child")
            store = FileExecutionLeaseStore(directory)
            self.assertIsNotNone(store.read("shared-task"))
            parent_ok, active = store.try_claim("shared-task", "owner-parent", "exec-parent")
            self.assertFalse(parent_ok)
            self.assertEqual(active.execution_id, "exec-child")

    def test_stale_execution_cannot_release_newer(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileExecutionLeaseStore(directory, lease_seconds=60)
            _, old = store.try_claim("task-1", "owner-a", "exec-1")
            store.release("task-1", "exec-1")
            _, new = store.try_claim("task-1", "owner-b", "exec-2")
            self.assertGreater(new.fence_token, old.fence_token)
            # The old execution trying to release the new one must fail.
            self.assertFalse(store.release("task-1", "exec-1"))
            self.assertEqual(store.read("task-1").execution_id, "exec-2")
            self.assertTrue(store.release("task-1", "exec-2"))


class RedisLeaseStoreTests(unittest.TestCase):
    def test_claim_is_nx_and_token_checked(self):
        client = FakeRedis()
        store = RedisExecutionLeaseStore(client, prefix="test:", lease_seconds=60)
        ok, record = store.try_claim("task-1", "owner-a", "exec-1")
        self.assertTrue(ok)
        self.assertEqual(record.execution_id, "exec-1")
        # Storage structure must match the Lua scripts: the token key holds
        # the plain ownership token and the meta key is a hash.
        self.assertEqual(client.get("test:task-1:token"), "exec-1")
        meta = client.hgetall("test:task-1:meta")
        self.assertEqual(meta.get("execution_id"), "exec-1")
        self.assertEqual(meta.get("owner_instance_id"), "owner-a")
        self.assertEqual(meta.get("fence_token"), "1")
        ok2, active = store.try_claim("task-1", "owner-b", "exec-2")
        self.assertFalse(ok2)
        self.assertEqual(active.execution_id, "exec-1")
        # Wrong token cannot renew or release.
        self.assertFalse(store.release("task-1", "exec-2"))
        self.assertTrue(store.renew("task-1", "exec-1"))
        self.assertTrue(store.release("task-1", "exec-1"))
        self.assertIsNone(client.get("test:task-1:token"))
        ok3, _ = store.try_claim("task-1", "owner-b", "exec-3")
        self.assertTrue(ok3)

    def test_fence_monotonic_per_task(self):
        client = FakeRedis()
        store = RedisExecutionLeaseStore(client, prefix="f:", lease_seconds=60)
        _, first = store.try_claim("task-1", "owner-a", "exec-1")
        store.release("task-1", "exec-1")
        _, second = store.try_claim("task-1", "owner-b", "exec-2")
        self.assertGreater(second.fence_token, first.fence_token)

    def test_ttl_expiry_allows_reclaim(self):
        client = FakeRedis()
        store = RedisExecutionLeaseStore(client, lease_seconds=5)
        store.try_claim("task-1", "owner-a", "exec-1")
        client._clock = lambda: time.time() + 10
        ok, record = store.try_claim("task-1", "owner-b", "exec-2")
        self.assertTrue(ok)
        self.assertEqual(record.execution_id, "exec-2")

    def test_renew_missing_or_wrong_token_returns_false(self):
        client = FakeRedis()
        store = RedisExecutionLeaseStore(client, lease_seconds=60)
        self.assertFalse(store.renew("task-1", "exec-1"))
        store.try_claim("task-1", "owner-a", "exec-1")
        self.assertFalse(store.renew("task-1", "exec-other"))
        self.assertTrue(store.renew("task-1", "exec-1"))

    def test_stale_execution_cannot_release_newer(self):
        client = FakeRedis()
        store = RedisExecutionLeaseStore(client, lease_seconds=60)
        _, old = store.try_claim("task-1", "owner-a", "exec-1")
        store.release("task-1", "exec-1")
        _, new = store.try_claim("task-1", "owner-b", "exec-2")
        self.assertFalse(store.release("task-1", "exec-1"))
        self.assertEqual(store.read("task-1").execution_id, "exec-2")
        self.assertTrue(store.release("task-1", "exec-2"))


class LeaseStoreFactoryTests(unittest.TestCase):
    def test_none_disables_durable_leases(self):
        with patch.dict(os.environ, {"TASKS_LEASE_STORE": "none"}, clear=False):
            self.assertIsNone(build_lease_store())

    def test_file_backend_from_env(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {
                "TASKS_LEASE_STORE": "file",
                "TASKS_LEASE_DIR": directory,
            }, clear=False):
                store = build_lease_store()
                self.assertIsInstance(store, FileExecutionLeaseStore)

    def test_redis_requires_url(self):
        with patch.dict(os.environ, {"TASKS_LEASE_STORE": "redis"}, clear=False):
            with self.assertRaises(ValueError):
                build_lease_store()

    def test_redis_backend_requires_installed_package(self):
        try:
            import redis  # noqa: F401
        except ImportError:
            with patch.dict(os.environ, {
                "TASKS_LEASE_STORE": "redis",
                "REDIS_URL": "redis://localhost:6379/0",
            }, clear=False):
                with self.assertRaises(RuntimeError):
                    build_lease_store()
        else:
            with patch.dict(os.environ, {
                "TASKS_LEASE_STORE": "redis",
                "REDIS_URL": "redis://localhost:6379/0",
            }, clear=False):
                self.assertIsInstance(build_lease_store(), RedisExecutionLeaseStore)


class LuaProtocolTests(unittest.TestCase):
    """The fake client exercises the exact Lua branches a real Redis runs."""

    def test_claim_script_writes_token_and_meta_and_ttl(self):
        client = FakeRedis()
        client.incr("test:task-1:fence")
        result = client.eval(CLAIM_SCRIPT, 2, "test:task-1:token", "test:task-1:meta",
                             "exec-1", 60000, "exec-1", "owner-a",
                             "1", "1", "1000", "1060", "1000", "CLAIMED", "u1")
        self.assertEqual(result, 1)
        self.assertEqual(client.get("test:task-1:token"), "exec-1")
        self.assertEqual(client.hget("test:task-1:meta", "execution_id"), "exec-1")
        self.assertEqual(client.hget("test:task-1:meta", "fence_token"), "1")
        # Second claim returns 0 without touching the owner.
        result2 = client.eval(CLAIM_SCRIPT, 2, "test:task-1:token", "test:task-1:meta",
                              "exec-2", 60000, "exec-2", "owner-b",
                              "2", "1", "1000", "1060", "1000", "CLAIMED", "u1")
        self.assertEqual(result2, 0)
        self.assertEqual(client.get("test:task-1:token"), "exec-1")

    def test_renew_and_release_are_token_checked(self):
        client = FakeRedis()
        client.eval(CLAIM_SCRIPT, 2, "t:task:token", "t:task:meta",
                    "exec-1", 60000, "exec-1", "owner-a",
                    "1", "1", "1000", "1060", "1000", "CLAIMED", "u1")
        # Wrong token fails.
        self.assertEqual(client.eval(RENEW_SCRIPT, 2, "t:task:token", "t:task:meta",
                                     "exec-2", 60000, "1100", "1160"), 0)
        self.assertEqual(client.eval(RELEASE_SCRIPT, 2, "t:task:token", "t:task:meta",
                                     "exec-2"), 0)
        self.assertEqual(client.get("t:task:token"), "exec-1")
        # Correct token works.
        self.assertEqual(client.eval(RENEW_SCRIPT, 2, "t:task:token", "t:task:meta",
                                     "exec-1", 60000, "1100", "1160"), 1)
        self.assertEqual(client.hget("t:task:meta", "heartbeat_at"), "1100")
        self.assertEqual(client.eval(RELEASE_SCRIPT, 2, "t:task:token", "t:task:meta",
                                     "exec-1"), 1)
        self.assertIsNone(client.get("t:task:token"))
        self.assertEqual(client.hgetall("t:task:meta"), {})

    def test_ttl_expiry_after_lease_seconds(self):
        client = FakeRedis()
        client.eval(CLAIM_SCRIPT, 2, "t:task:token", "t:task:meta",
                    "exec-1", 5000, "exec-1", "owner-a",
                    "1", "1", "1000", "1005", "1000", "CLAIMED", "u1")
        self.assertEqual(client.get("t:task:token"), "exec-1")
        client._clock = lambda: time.time() + 10
        self.assertIsNone(client.get("t:task:token"))
        result = client.eval(CLAIM_SCRIPT, 2, "t:task:token", "t:task:meta",
                             "exec-2", 5000, "exec-2", "owner-b",
                             "2", "1", "1010", "1015", "1010", "CLAIMED", "u2")
        self.assertEqual(result, 1)
        self.assertEqual(client.get("t:task:token"), "exec-2")


if __name__ == "__main__":
    unittest.main()
