"""P1: shared ExecutionCoordinator admission, worker pool and leases.

Both 47313 and 47314 route through this one module, so the tests here are the
contract for both services: a claim never blocks the caller (HTTP thread), a
queued execution is admitted later by a bounded worker pool, cancelling a
queued waiter always wakes it, and the Redis backend keeps quotas and leases
inside atomic Lua scripts.
"""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))
sys.path.insert(0, str(ROOT / "tests"))

from fake_redis import FakeRedis  # noqa: E402
from open_claude.execution_coordinator import (  # noqa: E402
    CoordinatorConfig,
    ExecutionCoordinator,
    SchedulerLimitError,
    Waiter,
    _RedisBackend,
)
from open_claude.execution_lease import FileExecutionLeaseStore  # noqa: E402


class _Adapter:
    """Minimal in-process adapter recording coordinator callbacks."""

    scope = "test"

    def __init__(self, instance_id="inst-test"):
        self.instance_id = instance_id
        self.started = []
        self.queued = []
        self.finished = []
        self.events = []
        self.workers = []
        self.worker_gate = threading.Event()
        self.worker_gate.set()

    def record_event(self, execution_id, event):
        self.events.append((execution_id, dict(event)))

    def on_queued(self, execution_id, position, queue_length):
        self.queued.append((execution_id, position, queue_length))

    def on_started(self, execution_id):
        self.started.append(execution_id)

    def run_worker(self, execution_id, token):
        self.workers.append(execution_id)
        self.worker_gate.wait(timeout=10)
        if token.cancelled:
            return
        self.record_event(execution_id, {"type": "assistant", "text": "ok"})

    def on_finished(self, execution_id, ok, token):
        self.finished.append((execution_id, ok))


def _config(**overrides):
    values = dict(
        service_namespace="test", backend="none", max_active=2,
        max_active_per_user=1, max_queued_per_user=2, max_queued=4,
        provider_concurrency=2, database_concurrency=2,
        lease_seconds=30, heartbeat_seconds=0.05, max_heartbeat_failures=2,
    )
    values.update(overrides)
    return CoordinatorConfig(**values)


class ClaimSemanticsTests(unittest.TestCase):
    def test_claim_never_blocks_and_returns_202_shaped_result(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()  # hold workers on claims
        coordinator = ExecutionCoordinator(_config(max_active=1, max_queued=2),
                                           adapter)
        try:
            first = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(first.decision, "admitted")
            self.assertGreaterEqual(first.queue_position, 0)
            second = coordinator.claim("t2", "exec-t2", "u1")
            self.assertEqual(second.decision, "queued")
            self.assertGreaterEqual(second.queue_position, 1)
            # No position=0 for admitted runs.
            self.assertNotIn((first.execution_id, 0), adapter.queued)
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()

    def test_immediate_admit_has_no_queued_event_or_position_zero(self):
        adapter = _Adapter()
        coordinator = ExecutionCoordinator(_config(max_active=1), adapter)
        try:
            result = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(result.decision, "admitted")
            self.assertEqual(adapter.queued, [])
            deadline = time.time() + 5
            while not adapter.started and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(adapter.started, ["t1"])
        finally:
            coordinator.shutdown()

    def test_second_execution_of_same_task_is_rejected(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()  # hold the first worker
        coordinator = ExecutionCoordinator(_config(), adapter)
        try:
            first = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(first.decision, "admitted")
            second = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(second.decision, "active_exists")
            self.assertEqual(second.error_code, "ACTIVE_RUN_EXISTS")
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()

    def test_worker_pool_active_never_exceeds_max(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()  # hold workers
        coordinator = ExecutionCoordinator(
            _config(max_active=2, max_active_per_user=2,
                    max_queued_per_user=10, max_queued=10), adapter)
        try:
            claims = [coordinator.claim(f"t{i}", f"exec-t{i}", f"u{i % 3}") for i in range(8)]
            admitted = [c for c in claims if c.decision == "admitted"]
            queued = [c for c in claims if c.decision == "queued"]
            self.assertEqual(len(admitted), 2)
            self.assertEqual(len(queued), 6)
            deadline = time.time() + 5
            while len(adapter.started) < 2 and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(adapter.started), 2)
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()

    def test_per_user_active_cap(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()  # hold workers
        coordinator = ExecutionCoordinator(
            _config(max_active=4, max_active_per_user=2,
                    max_queued_per_user=10, max_queued=10), adapter)
        try:
            claims = [coordinator.claim(f"t{i}", f"exec-t{i}", "u1") for i in range(4)]
            admitted = [c for c in claims if c.decision == "admitted"]
            self.assertEqual(len(admitted), 2)
            # u2 can still take the remaining global slots.
            other = coordinator.claim("b1", "exec-b1", "u2")
            self.assertEqual(other.decision, "admitted")
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()

    def test_queued_limit_returns_explicit_error(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()
        coordinator = ExecutionCoordinator(
            _config(max_active=1, max_active_per_user=1,
                    max_queued_per_user=1, max_queued=2), adapter)
        try:
            coordinator.claim("t1", "exec-t1", "u1")
            result = coordinator.claim("t2", "exec-t2", "u1")
            self.assertEqual(result.decision, "queued")
            overflow = coordinator.claim("t3", "exec-t3", "u1")
            self.assertEqual(overflow.decision, "user_queue_limit")
            self.assertEqual(overflow.error_code, "USER_QUEUE_LIMIT_REACHED")
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()

    def test_global_queue_limit(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()
        coordinator = ExecutionCoordinator(
            _config(max_active=1, max_active_per_user=1,
                    max_queued_per_user=5, max_queued=1), adapter)
        try:
            coordinator.claim("t1", "exec-t1", "u1")
            result = coordinator.claim("t2", "exec-t2", "u2")
            self.assertEqual(result.decision, "queued")
            overflow = coordinator.claim("t3", "exec-t3", "u3")
            self.assertEqual(overflow.decision, "global_queue_full")
            self.assertEqual(overflow.error_code, "GLOBAL_QUEUE_FULL")
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()

    def test_provider_database_semaphores_bound_concurrency(self):
        adapter = _Adapter()
        coordinator = ExecutionCoordinator(_config(provider_concurrency=2,
                                                   database_concurrency=1),
                                           adapter)
        try:
            self.assertEqual(coordinator.provider_slots._value, 2)
            self.assertEqual(coordinator.database_slots._value, 1)
            with coordinator.provider_slots:
                with coordinator.database_slots:
                    self.assertEqual(coordinator.provider_slots._value, 1)
                    self.assertEqual(coordinator.database_slots._value, 0)
        finally:
            coordinator.shutdown()

    def test_worker_failure_restores_quotas_and_slots(self):
        class _RaisingAdapter(_Adapter):
            def run_worker(self, execution_id, token):
                raise RuntimeError("worker boom")

        adapter = _RaisingAdapter()
        coordinator = ExecutionCoordinator(_config(max_active=2, max_queued=2),
                                           adapter)
        try:
            coordinator.claim("t1", "exec-t1", "u1")
            coordinator.claim("t2", "exec-t2", "u2")
            deadline = time.time() + 5
            while (coordinator.metrics()["concurrency"]["activeRuns"]
                   and time.time() < deadline):
                time.sleep(0.01)
            concurrency = coordinator.metrics()["concurrency"]
            self.assertEqual(concurrency["activeRuns"], 0)
            self.assertEqual(concurrency["queuedRuns"], 0)
            self.assertEqual(coordinator.provider_slots._value, 2)
            self.assertEqual(coordinator.database_slots._value, 2)
        finally:
            coordinator.shutdown()

    def test_fair_admission_skips_users_at_per_user_cap(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()  # hold admitted workers
        coordinator = ExecutionCoordinator(
            _config(max_active=2, max_active_per_user=1,
                    max_queued_per_user=10, max_queued=10), adapter)
        try:
            first = coordinator.claim("t1", "exec-t1", "u1")
            second = coordinator.claim("t2", "exec-t2", "u2")
            # u1 already occupies its only active slot, so the next u1 claim
            # must stay queued while an eligible u3 claim is admitted next.
            coordinator.claim("t3", "exec-t3", "u1")
            coordinator.claim("t4", "exec-t4", "u3")
            deadline = time.time() + 5
            while (len(adapter.started) < 2 and time.time() < deadline):
                time.sleep(0.01)
            self.assertEqual(sorted(adapter.started[:2]), ["t1", "t2"])
            # Free one global slot (u2 finishes) so the dispatcher can admit.
            coordinator.release("t2", second.execution_id, second.fence_token)
            admitted = coordinator.backend.admit_next()
            # Fair round-robin: u3 (not at its cap) is admitted before u1.
            self.assertEqual(admitted, "t4")
            # u1's queued claim stays queued while u1 remains at its cap.
            self.assertEqual(coordinator.backend.admit_next(), None)
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()

    def test_release_is_idempotent_and_counts_never_negative(self):
        adapter = _Adapter()
        adapter.worker_gate.clear()  # hold workers so leases stay claimed
        coordinator = ExecutionCoordinator(
            _config(max_active=2, max_active_per_user=1,
                    max_queued_per_user=3, max_queued=3), adapter)
        try:
            first = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(first.decision, "admitted")
            # Double release with the same fence is harmless.
            coordinator.release("t1", first.execution_id, first.fence_token)
            coordinator.release("t1", first.execution_id, first.fence_token)
            # Releasing a stale fence for a new execution must not clear it.
            second = coordinator.claim("t1", "exec-t1", "u1", attempt=2)
            self.assertEqual(second.decision, "admitted")
            coordinator.backend.release("t1", first.execution_id, first.fence_token, was_queued=False)
            self.assertEqual(coordinator.read_lease("t1").execution_id,
                             second.execution_id)
            metrics = coordinator.metrics()["concurrency"]
            self.assertGreaterEqual(metrics["activeRuns"], 0)
            self.assertGreaterEqual(metrics["queuedRuns"], 0)
        finally:
            coordinator.shutdown()

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            _config(max_active=0).validate()
        with self.assertRaises(ValueError):
            _config(max_active=100).validate()
        with self.assertRaises(ValueError):
            _config(provider_concurrency=0).validate()


class WaiterLifecycleTests(unittest.TestCase):
    def test_cancel_wakes_queued_waiter(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()
        coordinator = ExecutionCoordinator(
            _config(max_active=1, max_active_per_user=1,
                    max_queued_per_user=5, max_queued=5), adapter)
        exited = []
        try:
            first = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(first.decision, "admitted")

            def wait_for_slot():
                result = coordinator.claim("t2", "exec-t2", "u1")
                self.assertEqual(result.decision, "queued")
                exited.append(result.execution_id)

            thread = threading.Thread(target=wait_for_slot)
            thread.start()
            deadline = time.time() + 5
            while not exited and time.time() < deadline:
                time.sleep(0.01)
            # Cancel the queued execution; the claim thread must exit quickly.
            coordinator.cancel("t2")
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()

    def test_release_queued_waiter_is_idempotent(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()
        coordinator = ExecutionCoordinator(
            _config(max_active=1, max_active_per_user=1,
                    max_queued_per_user=5, max_queued=5), adapter)
        try:
            coordinator.claim("t1", "exec-t1", "u1")
            result = coordinator.claim("t2", "exec-t2", "u1")
            self.assertEqual(result.decision, "queued")
            self.assertTrue(coordinator.cancel("t2"))
            self.assertFalse(coordinator.cancel("t2"))
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()

    def test_release_wakes_queued_waiter_thread(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()  # hold the admitted worker
        coordinator = ExecutionCoordinator(
            _config(max_active=1, max_active_per_user=1,
                    max_queued_per_user=5, max_queued=5), adapter)
        try:
            coordinator.claim("t1", "exec-t1", "u1")
            result = coordinator.claim("t2", "exec-t2", "u1")
            self.assertEqual(result.decision, "queued")
            entry = coordinator._executions["t2"]
            self.assertIsNotNone(entry.waiter)
            outcome = []

            def wait_for_slot():
                outcome.append(entry.waiter.wait_for_slot(timeout=5))

            thread = threading.Thread(target=wait_for_slot)
            thread.start()
            deadline = time.time() + 5
            while (entry.waiter.state == Waiter.WAITING
                   and time.time() < deadline):
                time.sleep(0.01)
            self.assertEqual(entry.waiter.state, Waiter.WAITING)
            # Releasing the queued execution must wake the waiter with False
            # (never a permanent wait) and free the queue slot.
            coordinator.release("t2", result.execution_id, result.fence_token)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome, [False])
            self.assertEqual(entry.waiter.state, Waiter.RELEASED)
            self.assertEqual(
                coordinator.metrics()["concurrency"]["queuedRuns"], 0)
            # A second release stays idempotent.
            coordinator.release("t2", result.execution_id, result.fence_token)
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()


class HeartbeatTests(unittest.TestCase):
    def test_lease_loss_cancels_worker(self):
        directory = tempfile.mkdtemp()
        try:
            adapter = _Adapter()
            adapter.worker_gate = threading.Event()  # hold the worker
            lease_store = FileExecutionLeaseStore(directory, lease_seconds=30)
            coordinator = ExecutionCoordinator(
                _config(backend="file", max_active=1, heartbeat_seconds=0.05,
                        max_heartbeat_failures=2), adapter,
                lease_store=lease_store)
            try:
                result = coordinator.claim("t1", "exec-t1", "u1")
                self.assertEqual(result.decision, "admitted")
                deadline = time.time() + 5
                while not adapter.started and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(adapter.started)
                # Steal the lease: renew with a different owner fails, so
                # release the lease directly and let a new owner claim it.
                lease_store.release("t1", result.execution_id)
                lease_store.try_claim("t1", "other-instance", "t1-other",
                                      lease_seconds=30)
                deadline = time.time() + 5
                while (not any(e[1].get("code") == "LEASE_LOST"
                               for e in adapter.events)
                       and time.time() < deadline):
                    time.sleep(0.05)
                lost = [e for e in adapter.events
                        if e[1].get("code") == "LEASE_LOST"]
                self.assertTrue(lost, "expected LEASE_LOST event")
            finally:
                adapter.worker_gate.set()
                coordinator.shutdown()
        finally:
            import shutil
            shutil.rmtree(directory, ignore_errors=True)


class RedisCoordinatorTests(unittest.TestCase):
    def _coordinator(self, client, **overrides):
        values = dict(backend="redis", redis_url="redis://fake",
                      redis_prefix="test:", max_active=1,
                      max_active_per_user=1, max_queued_per_user=2,
                      max_queued=2, lease_seconds=60)
        values.update(overrides)
        adapter = _Adapter()
        coordinator = ExecutionCoordinator(CoordinatorConfig(**values), adapter,
                                           redis_client=client)
        return coordinator, adapter

    def test_claim_admit_release_via_redis_lua(self):
        client = FakeRedis()
        coordinator, adapter = self._coordinator(client)
        try:
            first = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(first.decision, "admitted")
            second = coordinator.claim("t2", "exec-t2", "u1")
            self.assertEqual(second.decision, "queued")
            third = coordinator.claim("t3", "exec-t3", "u2")
            self.assertEqual(third.decision, "queued")
            # Storage layout used by the Lua scripts.
            self.assertEqual(client.get("test:execution:t1:token"), "exec-t1")
            self.assertEqual(
                client.hget("test:execution:t2:meta", "status"), "QUEUED")
            coordinator.release("t1", first.execution_id, first.fence_token)
            admitted = coordinator.backend.admit_next()
            self.assertEqual(admitted, "t2")
            self.assertEqual(
                client.hget("test:execution:t2:meta", "status"), "ADMITTED")
            coordinator.release("t2", second.execution_id, second.fence_token)
            self.assertEqual(coordinator.backend.admit_next(), "t3")
        finally:
            coordinator.shutdown()

    def test_multi_instance_global_quota_shared_in_redis(self):
        client = FakeRedis()
        config_a = CoordinatorConfig(
            backend="redis", redis_url="redis://fake", redis_prefix="test:",
            max_active=1, max_active_per_user=1, max_queued_per_user=5,
            max_queued=5, lease_seconds=60)
        backend_a = _RedisBackend(config_a, client, "inst-a")
        backend_b = _RedisBackend(config_a, client, "inst-b")
        try:
            result_a = backend_a.claim("t1", "exec-a", "u1", 1)
            self.assertEqual(result_a[0].decision, "admitted")
            # Second instance sees the same global active budget in Redis.
            result_b = backend_b.claim("t2", "exec-b", "u2", 1)
            self.assertEqual(result_b[0].decision, "queued")
            # active counter never exceeds the global cap across instances.
            self.assertEqual(int(client.get("test:counters:active") or 0), 1)
            # Instance A finishes; instance B's dispatcher can then admit.
            backend_a.release("t1", result_a[0].execution_id, result_a[0].fence_token, was_queued=False)
            self.assertEqual(backend_b.admit_next(), "t2")
            self.assertEqual(int(client.get("test:counters:active") or 0), 1)
        finally:
            backend_b.release("t2", result_b[0].execution_id, result_b[0].fence_token, was_queued=True)

    def test_stale_fence_cannot_release_newer(self):
        client = FakeRedis()
        coordinator, _ = self._coordinator(client)
        try:
            first = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(first.decision, "admitted")
            coordinator.release("t1", first.execution_id, first.fence_token)
            second = coordinator.claim("t1", "exec-t1", "u1", attempt=2)
            self.assertEqual(second.decision, "admitted")
            self.assertGreater(second.fence_token, first.fence_token)
            # Old fence must not release the new execution.
            coordinator.backend.release("t1", first.execution_id, first.fence_token, was_queued=False)
            self.assertEqual(coordinator.read_lease("t1").execution_id,
                             second.execution_id)
        finally:
            coordinator.shutdown()


class CoordinatorMetricsTests(unittest.TestCase):
    """Unified concurrency/coordination metrics for /health."""

    def test_metrics_report_unified_structure(self):
        adapter = _Adapter()
        adapter.worker_gate.clear()
        coordinator = ExecutionCoordinator(
            _config(backend="file", max_active=3, max_queued=4,
                    lease_seconds=30, heartbeat_seconds=0.05,
                    lease_dir=tempfile.mkdtemp()),
            adapter)
        try:
            coordinator.claim("t1", "exec-t1", "u1")
            coordinator.claim("t2", "exec-t2", "u2")
            coordinator.claim("t3", "exec-t3", "u3")
            coordinator.claim("t4", "exec-t4", "u1")
            deadline = time.time() + 5
            while (len(adapter.started) < 3 and time.time() < deadline):
                time.sleep(0.01)
            metrics = coordinator.metrics()
            concurrency = metrics["concurrency"]
            for key in ("activeRuns", "queuedRuns", "maxActiveRuns",
                        "maxActivePerUser", "maxQueuedPerUser", "maxQueuedRuns",
                        "oldestQueuedSeconds", "providerConcurrency",
                        "providerInUse", "databaseConcurrency", "databaseInUse"):
                self.assertIn(key, concurrency)
            self.assertEqual(concurrency["activeRuns"], 3)
            self.assertEqual(concurrency["queuedRuns"], 1)
            coordination = metrics["coordination"]
            for key in ("backend", "instanceId", "multiProcessSafe",
                        "multiHostSafe", "leaseSeconds", "heartbeatSeconds",
                        "activeLeases", "expiredLeasesRecovered"):
                self.assertIn(key, coordination)
            self.assertEqual(coordination["backend"], "file")
            self.assertTrue(coordination["multiProcessSafe"])
            self.assertFalse(coordination["multiHostSafe"])
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown()


if __name__ == "__main__":
    unittest.main()


class P2RegressionTests(unittest.TestCase):
    """Joint P1/P2 acceptance regressions (313+314 shared coordinator).

    These tests exercise the exact Redis storage structures and Lua scripts
    (via the fake Redis Lua evaluator) that production instances run, so the
    owner-affinity queue, cluster-scope quotas, queued-lease TTL and recovery
    behaviour are verified against the real protocol rather than a JSON shim.
    """

    def _redis_config(self, **overrides):
        values = dict(backend="redis", redis_url="redis://fake",
                      redis_prefix="test:", max_active=2,
                      max_active_per_user=1, max_queued_per_user=5,
                      max_queued=5, lease_seconds=60,
                      queued_lease_seconds=60, recovery_seconds=600)
        values.update(overrides)
        return CoordinatorConfig(**values)

    def test_redis_metrics_report_cluster_scope(self):
        client = FakeRedis()
        adapter = _Adapter()
        coordinator = ExecutionCoordinator(self._redis_config(), adapter,
                                           redis_client=client)
        try:
            coordination = coordinator.metrics()["coordination"]
            self.assertEqual(coordination["backend"], "redis")
            self.assertTrue(coordination["multiHostSafe"])
            self.assertTrue(coordination["leaseMultiProcessSafe"])
            self.assertEqual(coordination["quotaScope"], "cluster")
            self.assertEqual(coordination["queueScope"], "cluster")
        finally:
            coordinator.shutdown()

    def test_file_metrics_do_not_claim_cluster_quota(self):
        adapter = _Adapter()
        coordinator = ExecutionCoordinator(
            _config(backend="file", max_active=1, lease_seconds=30,
                    lease_dir=tempfile.mkdtemp()),
            adapter)
        try:
            coordination = coordinator.metrics()["coordination"]
            self.assertEqual(coordination["backend"], "file")
            self.assertFalse(coordination["multiHostSafe"])
            self.assertEqual(coordination["quotaScope"], "process")
            self.assertEqual(coordination["queueScope"], "process")
        finally:
            coordinator.shutdown()

    def test_per_user_active_shared_across_redis_instances(self):
        client = FakeRedis()
        config = self._redis_config(max_active=4)
        backend_a = _RedisBackend(config, client, "inst-a")
        backend_b = _RedisBackend(config, client, "inst-b")
        try:
            # u1 fills its single active slot on instance A.
            a = backend_a.claim("t1", "exec-a", "u1", 1)
            self.assertEqual(a[0].decision, "admitted")
            # Instance B cannot admit another u1 task (per-user cap is
            # cluster-scoped), it must queue.
            b = backend_b.claim("t2", "exec-b", "u1", 1)
            self.assertEqual(b[0].decision, "queued")
            # A different user on B is admitted.
            c = backend_b.claim("t3", "exec-c", "u2", 1)
            self.assertEqual(c[0].decision, "admitted")
        finally:
            backend_a.release("t1", "exec-a", a[0].fence_token, was_queued=False)
            backend_b.release("t2", "exec-b", b[0].fence_token, was_queued=True)
            backend_b.release("t3", "exec-c", c[0].fence_token, was_queued=False)

    def test_owner_affinity_dispatcher_cannot_admit_other_instance_payload(self):
        client = FakeRedis()
        config = self._redis_config(max_active=2)
        backend_a = _RedisBackend(config, client, "inst-a")
        backend_b = _RedisBackend(config, client, "inst-b")
        try:
            a1 = backend_a.claim("t1", "exec-a1", "u1", 1)
            a2 = backend_a.claim("t2", "exec-a2", "u2", 1)
            q3 = backend_a.claim("t3", "exec-a3", "u3", 1)  # queued, owner A
            q4 = backend_b.claim("t4", "exec-b4", "u4", 1)  # queued, owner B
            self.assertEqual(a1[0].decision, "admitted")
            self.assertEqual(a2[0].decision, "admitted")
            self.assertEqual(q3[0].decision, "queued")
            self.assertEqual(q4[0].decision, "queued")
            # No capacity yet: B's dispatcher must not admit anything.
            self.assertIsNone(backend_b.admit_next())
            # A frees a slot; B's dispatcher skips A's queued task (its
            # executable payload lives in A's memory) and admits its own.
            backend_a.release("t1", "exec-a1", a1[0].fence_token,
                              was_queued=False)
            self.assertEqual(backend_b.admit_next(), "t4")
            # A's queued task is untouched and still owned by A.
            self.assertEqual(
                client.hget("test:execution:t3:meta", "owner_instance_id"),
                "inst-a")
        finally:
            backend_a.release("t2", "exec-a2", a2[0].fence_token,
                              was_queued=False)
            backend_b.release("t4", "exec-b4", q4[0].fence_token,
                              was_queued=False)
            backend_a.release("t3", "exec-a3", q3[0].fence_token,
                              was_queued=True)

    def test_cancel_of_queued_item_cleans_global_and_user_queue(self):
        client = FakeRedis()
        config = self._redis_config(max_active=1)
        backend = _RedisBackend(config, client, "inst-a")
        try:
            a = backend.claim("t1", "exec-a", "u1", 1)
            q = backend.claim("t2", "exec-b", "u1", 1)
            self.assertEqual(a[0].decision, "admitted")
            self.assertEqual(q[0].decision, "queued")
            # Queue items are resource ids, the token is the execution id.
            self.assertEqual(client.lrange("test:queue", 0, -1), ["t2"])
            self.assertEqual(client.lrange("test:queue:u1", 0, -1), ["t2"])
            self.assertTrue(
                backend.cancel("t2", q[0].execution_id, q[0].fence_token))
            # No ghost items remain and no capacity is leaked.
            self.assertEqual(client.lrange("test:queue", 0, -1), [])
            self.assertEqual(client.lrange("test:queue:u1", 0, -1), [])
            self.assertEqual(int(client.get("test:counters:queued") or 0), 0)
            self.assertIsNone(backend.admit_next())
        finally:
            backend.release("t1", a[0].execution_id, a[0].fence_token,
                            was_queued=False)

    def test_release_of_queued_item_cleans_queues_and_counters(self):
        client = FakeRedis()
        config = self._redis_config(max_active=1)
        backend = _RedisBackend(config, client, "inst-a")
        try:
            a = backend.claim("t1", "exec-a", "u1", 1)
            q = backend.claim("t2", "exec-b", "u1", 1)
            self.assertEqual(q[0].decision, "queued")
            backend.release("t2", q[0].execution_id, q[0].fence_token,
                            was_queued=True)
            self.assertEqual(client.lrange("test:queue", 0, -1), [])
            self.assertEqual(client.lrange("test:queue:u1", 0, -1), [])
            self.assertEqual(int(client.get("test:counters:queued") or 0), 0)
            self.assertIsNone(backend.admit_next())
        finally:
            backend.release("t1", a[0].execution_id, a[0].fence_token,
                            was_queued=False)

    def test_queued_lease_outlives_execution_ttl_without_ghost(self):
        clock = {"now": 1000.0}
        client = FakeRedis(clock=lambda: clock["now"])
        config = self._redis_config(max_active=1, lease_seconds=5,
                                    queued_lease_seconds=60,
                                    recovery_seconds=600)
        backend = _RedisBackend(config, client, "inst-a",
                                clock=lambda: clock["now"])
        try:
            a1 = backend.claim("t1", "exec-1", "u1", 1)
            self.assertEqual(a1[0].decision, "admitted")
            q1 = backend.claim("t2", "exec-2", "u2", 1)
            self.assertEqual(q1[0].decision, "queued")
            # Move past the execution lease TTL but not the queued TTL.
            clock["now"] += 10
            # The queued item's token still exists (not a ghost) even though
            # the admitted execution's short lease already expired.
            self.assertIsNotNone(client.get("test:execution:t2:token"))
            self.assertEqual(client.hget("test:execution:t2:meta", "status"),
                             "QUEUED")
            # The expired admitted lease is recovered; the owner then admits
            # its own queued task after the long wait.
            self.assertEqual(backend.recover_expired(), 1)
            self.assertEqual(backend.admit_next(), "t2")
        finally:
            backend.release("t2", "exec-2", q1[0].fence_token,
                            was_queued=False)

    def test_owner_death_queued_cleanup_recovers_counters_once(self):
        clock = {"now": 1000.0}
        client = FakeRedis(clock=lambda: clock["now"])
        config = self._redis_config(max_active=1, lease_seconds=60,
                                    queued_lease_seconds=10,
                                    recovery_seconds=600)
        backend_a = _RedisBackend(config, client, "inst-a",
                                  clock=lambda: clock["now"])
        backend_b = _RedisBackend(config, client, "inst-b",
                                  clock=lambda: clock["now"])
        try:
            backend_a.claim("t1", "exec-1", "u1", 1)  # admitted (60s lease)
            backend_a.claim("t2", "exec-2", "u2", 1)  # queued (10s queued lease)
            # Owner A dies: the queued token expires but the meta survives
            # inside the recovery window (token TTL < meta TTL).
            clock["now"] += 30
            self.assertIsNone(client.get("test:execution:t2:token"))
            self.assertEqual(client.hget("test:execution:t2:meta", "status"),
                             "QUEUED")
            self.assertEqual(int(client.get("test:counters:queued") or 0), 1)
            # Instance B recovers exactly once; counters return to zero.
            self.assertEqual(backend_b.recover_expired(), 1)
            self.assertEqual(int(client.get("test:counters:queued") or 0), 0)
            self.assertIsNone(client.get("test:execution:t2:meta"))
            # A second recovery pass finds nothing.
            self.assertEqual(backend_b.recover_expired(), 0)
        finally:
            backend_a.release("t1", "exec-1", 1, was_queued=False)

    def test_recovery_uses_scan_not_keys(self):
        from unittest.mock import patch
        clock = {"now": 1000.0}
        client = FakeRedis(clock=lambda: clock["now"])
        config = self._redis_config(max_active=1, lease_seconds=60,
                                    queued_lease_seconds=10,
                                    recovery_seconds=600)
        backend = _RedisBackend(config, client, "inst-a",
                                clock=lambda: clock["now"])
        try:
            backend.claim("t1", "exec-1", "u1", 1)
            backend.claim("t2", "exec-2", "u2", 1)
            clock["now"] += 30
            with patch.object(client, "keys",
                              side_effect=AssertionError("KEYS must not be used")):
                self.assertEqual(backend.recover_expired(), 1)
        finally:
            backend.release("t1", "exec-1", 1, was_queued=False)

    def test_multi_instance_recovery_only_one_wins(self):
        clock = {"now": 1000.0}
        client = FakeRedis(clock=lambda: clock["now"])
        config = self._redis_config(max_active=1, lease_seconds=60,
                                    queued_lease_seconds=10,
                                    recovery_seconds=600)
        backend_a = _RedisBackend(config, client, "inst-a",
                                  clock=lambda: clock["now"])
        backend_b = _RedisBackend(config, client, "inst-b",
                                  clock=lambda: clock["now"])
        barrier = threading.Barrier(2)
        results = []
        results_lock = threading.Lock()

        def recover(backend):
            barrier.wait(timeout=5)
            try:
                count = backend.recover_expired()
            except Exception as exc:  # noqa: BLE001 - record and continue
                count = -1
            with results_lock:
                results.append(count)

        try:
            backend_a.claim("t1", "exec-1", "u1", 1)
            backend_a.claim("t2", "exec-2", "u2", 1)
            clock["now"] += 30
            threads = [threading.Thread(target=recover, args=(backend_a,)),
                       threading.Thread(target=recover, args=(backend_b,))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertEqual(sum(results), 1)
            self.assertEqual(int(client.get("test:counters:queued") or 0), 0)
        finally:
            backend_a.release("t1", "exec-1", 1, was_queued=False)

    def test_stale_release_does_not_decrement_new_execution_counters(self):
        client = FakeRedis()
        config = self._redis_config(max_active=1)
        backend = _RedisBackend(config, client, "inst-a")
        try:
            first = backend.claim("t1", "exec-1", "u1", 1)
            self.assertEqual(first[0].decision, "admitted")
            backend.release("t1", "exec-1", first[0].fence_token,
                            was_queued=False)
            second = backend.claim("t1", "exec-2", "u1", 2)
            self.assertEqual(second[0].decision, "admitted")
            self.assertGreater(second[0].fence_token, first[0].fence_token)
            # The old execution releasing afterwards must be a no-op: the new
            # execution keeps its active slot.
            backend.release("t1", "exec-1", first[0].fence_token,
                            was_queued=False)
            self.assertEqual(int(client.get("test:counters:active") or 0), 1)
            backend.release("t1", "exec-2", second[0].fence_token,
                            was_queued=False)
            self.assertEqual(int(client.get("test:counters:active") or 0), 0)
        except Exception:
            backend.release("t1", "exec-2", 1, was_queued=False)
            raise

    def test_on_finished_called_exactly_once(self):
        class _CountingAdapter(_Adapter):
            def run_worker(self, execution_id, token):
                raise RuntimeError("worker boom")

        adapter = _CountingAdapter()
        coordinator = ExecutionCoordinator(_config(max_active=2), adapter)
        try:
            coordinator.claim("t1", "exec-1", "u1")
            coordinator.claim("t2", "exec-2", "u2")
            deadline = time.time() + 5
            while len(adapter.finished) < 2 and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(adapter.finished), 2)
        finally:
            coordinator.shutdown()

    def test_acquire_cancelable_does_not_leak_slots(self):
        from open_claude.execution_coordinator import (
            CancellationToken,
            ExecutionCancelled,
            acquire_cancelable,
        )
        semaphore = threading.BoundedSemaphore(1)
        self.assertTrue(semaphore.acquire(blocking=False))  # occupy the slot
        token = CancellationToken()
        outcome = []

        def waiter():
            try:
                acquire_cancelable(semaphore, token, timeout=0.01)
                outcome.append("acquired")
            except Exception as exc:  # noqa: BLE001 - record the exception
                outcome.append(type(exc).__name__)

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.1)
        token.cancel("TEST_CANCEL")
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [ExecutionCancelled.__name__])
        # The cancelled wait never consumed the slot.
        semaphore.release()
        self.assertEqual(semaphore._value, 1)


class FinalAcceptanceTests(unittest.TestCase):
    """P1/P2 final acceptance: heartbeat order, bounded shutdown, no KEYS."""

    def _redis_config(self, **overrides):
        values = dict(backend="redis", redis_url="redis://fake",
                      redis_prefix="test:", max_active=1,
                      max_active_per_user=1, max_queued_per_user=2,
                      max_queued=2, lease_seconds=60,
                      queued_lease_seconds=60, recovery_seconds=600)
        values.update(overrides)
        return CoordinatorConfig(**values)

    # -- heartbeat must start before on_started ------------------------------

    def test_heartbeat_starts_before_on_started_and_keeps_lease(self):
        directory = tempfile.mkdtemp()
        try:
            adapter = _Adapter()
            adapter.started_gate = threading.Event()  # block inside on_started

            def blocking_started(execution_id):
                adapter.started.append(execution_id)
                adapter.started_gate.wait(timeout=5)

            adapter.on_started = blocking_started
            lease_store = FileExecutionLeaseStore(directory, lease_seconds=1)
            coordinator = ExecutionCoordinator(
                _config(backend="file", max_active=1, lease_seconds=1,
                        heartbeat_seconds=0.05, max_heartbeat_failures=2),
                adapter, lease_store=lease_store)
            try:
                result = coordinator.claim("t1", "exec-t1", "u1")
                self.assertEqual(result.decision, "admitted")
                deadline = time.time() + 5
                while not adapter.started and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(adapter.started)
                # While on_started blocks past one lease TTL the heartbeat
                # must keep the lease alive so no other instance can claim.
                time.sleep(1.2)
                lease = lease_store.read("t1")
                self.assertIsNotNone(lease)
                self.assertEqual(lease.execution_id, result.execution_id)
                other = lease_store.try_claim("t1", "other-instance",
                                              "t1-other", lease_seconds=1)
                self.assertFalse(other[0])
                self.assertEqual(other[1].execution_id, result.execution_id)
                adapter.started_gate.set()
                deadline = time.time() + 5
                while not adapter.finished and time.time() < deadline:
                    time.sleep(0.01)
                self.assertEqual(adapter.finished, [("t1", True)])
            finally:
                adapter.started_gate.set()
                coordinator.shutdown(timeout=5)
        finally:
            import shutil
            shutil.rmtree(directory, ignore_errors=True)

    def test_heartbeat_failure_during_on_started_prevents_worker(self):
        directory = tempfile.mkdtemp()
        try:
            adapter = _Adapter()
            adapter.started_gate = threading.Event()  # block inside on_started

            def blocking_started(execution_id):
                adapter.started.append(execution_id)
                adapter.started_gate.wait(timeout=5)

            adapter.on_started = blocking_started
            lease_store = FileExecutionLeaseStore(directory, lease_seconds=30)
            coordinator = ExecutionCoordinator(
                _config(backend="file", max_active=1, heartbeat_seconds=0.05,
                        max_heartbeat_failures=2), adapter,
                lease_store=lease_store)
            try:
                result = coordinator.claim("t1", "exec-t1", "u1")
                self.assertEqual(result.decision, "admitted")
                deadline = time.time() + 5
                while not adapter.started and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(adapter.started)
                # Steal the lease while on_started is blocking: the heartbeat
                # fails, the token is cancelled and the worker must not run.
                lease_store.release("t1", result.execution_id)
                lease_store.try_claim("t1", "other-instance", "t1-other",
                                      lease_seconds=30)
                deadline = time.time() + 5
                while (not any(e[1].get("code") == "LEASE_LOST"
                               for e in adapter.events)
                       and time.time() < deadline):
                    time.sleep(0.05)
                self.assertTrue(any(e[1].get("code") == "LEASE_LOST"
                                    for e in adapter.events))
                adapter.started_gate.set()
                deadline = time.time() + 5
                while not adapter.finished and time.time() < deadline:
                    time.sleep(0.05)
                self.assertEqual(adapter.workers, [])
                self.assertEqual(adapter.finished, [("t1", False)])
            finally:
                adapter.started_gate.set()
                coordinator.shutdown(timeout=5)
        finally:
            import shutil
            shutil.rmtree(directory, ignore_errors=True)

    # -- bounded graceful shutdown -------------------------------------------

    def test_shutdown_returns_bounded_and_rejects_new_claims(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()  # workers block forever
        coordinator = ExecutionCoordinator(_config(max_active=1, max_queued=2),
                                           adapter)
        try:
            first = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(first.decision, "admitted")
            queued = coordinator.claim("t2", "exec-t2", "u2")
            self.assertEqual(queued.decision, "queued")
            deadline = time.time() + 5
            while not adapter.started and time.time() < deadline:
                time.sleep(0.01)
            started = time.monotonic()
            coordinator.shutdown(timeout=0.5)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 5.0)
            # Queued counters were returned to zero.
            self.assertEqual(
                coordinator.metrics()["concurrency"]["queuedRuns"], 0)
            # New claims are rejected with COORDINATOR_STOPPING.
            after = coordinator.claim("t3", "exec-t3", "u3")
            self.assertEqual(after.decision, "stopping")
            self.assertEqual(after.error_code, "COORDINATOR_STOPPING")
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown(timeout=2)

    def test_shutdown_abandoned_worker_cannot_write_formal_status(self):
        adapter = _Adapter()
        adapter.worker_gate = threading.Event()  # workers block forever
        coordinator = ExecutionCoordinator(_config(max_active=1), adapter)
        try:
            first = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(first.decision, "admitted")
            deadline = time.time() + 5
            while not adapter.started and time.time() < deadline:
                time.sleep(0.01)
            coordinator.shutdown(timeout=0.3)
            # Let the abandoned worker finally return; it must not call
            # on_finished or write any formal completion status.
            adapter.worker_gate.set()
            deadline = time.time() + 5
            while not adapter.workers and time.time() < deadline:
                time.sleep(0.05)
            time.sleep(0.3)
            self.assertEqual(adapter.finished, [])
        finally:
            adapter.worker_gate.set()
            coordinator.shutdown(timeout=2)

    def test_shutdown_returns_quickly_when_workers_are_idle(self):
        adapter = _Adapter()
        coordinator = ExecutionCoordinator(_config(max_active=1), adapter)
        try:
            first = coordinator.claim("t1", "exec-t1", "u1")
            self.assertEqual(first.decision, "admitted")
            deadline = time.time() + 5
            while not adapter.finished and time.time() < deadline:
                time.sleep(0.01)
            started = time.monotonic()
            coordinator.shutdown(timeout=2.0)
            self.assertLess(time.monotonic() - started, 2.0)
        finally:
            coordinator.shutdown(timeout=1)

    # -- recovery must never fall back to Redis KEYS -------------------------

    def test_production_path_never_uses_redis_keys(self):
        import re
        path = Path(__file__).resolve().parents[1] / "open-claude" / "open_claude" / "execution_coordinator.py"
        source = path.read_text(encoding="utf-8")
        # The production Python path must not call client.keys(...).
        self.assertNotIn(".client.keys(", source)
        self.assertNotIn(".keys(", source)
        # The Lua scripts must not call the KEYS command (only the KEYS table
        # passed by EVAL, which is always spelled ``KEYS[n]``).
        for line in source.splitlines():
            stripped = line.strip()
            if "redis.call(" in stripped and "KEYS" in stripped:
                self.assertNotIn('"KEYS"', stripped)
                self.assertNotIn("'KEYS'", stripped)

    def test_redis_backend_requires_scan_iter_client(self):
        client = FakeRedis()
        client.scan_iter = None  # simulate a client without SCAN support
        with self.assertRaises(RuntimeError):
            ExecutionCoordinator(self._redis_config(), _Adapter(),
                                 redis_client=client)
