"""Real-Redis integration tests for the P1/P2 execution coordinator.

These tests run only when ``ONTOLOGY_TEST_REDIS_URL`` points at a reachable
Redis server (e.g. ``redis://127.0.0.1:6390/15``).  They exercise the exact
Lua scripts and storage layout that production 47313/47314 instances use, so
a FakeRedis-only green suite can never hide a protocol mismatch (wrong hash
field names, queue items that are never removed, token/meta TTL mismatches).

Every test claims a unique ``ontology:test:<uuid>:`` prefix and deletes every
key under it afterwards.
"""
import os
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))
sys.path.insert(0, str(ROOT / "tests"))

REDIS_URL = os.environ.get("ONTOLOGY_TEST_REDIS_URL")

from open_claude.execution_coordinator import (  # noqa: E402
    CoordinatorConfig,
    ExecutionCoordinator,
    _RedisBackend,
)


class _Adapter:
    """Minimal coordinator adapter; worker holds briefly and finishes."""

    scope = "real-redis-test"

    def __init__(self, instance_id="inst-a"):
        self.instance_id = instance_id
        self.started = []
        self.finished = []

    def record_event(self, execution_id, event):
        pass

    def on_queued(self, execution_id, position, queue_length):
        pass

    def on_started(self, execution_id):
        self.started.append(execution_id)

    def run_worker(self, execution_id, token):
        time.sleep(0.2)

    def on_finished(self, execution_id, ok, token):
        self.finished.append((execution_id, ok))


@unittest.skipUnless(REDIS_URL,
                     "ONTOLOGY_TEST_REDIS_URL 未设置，跳过真实 Redis 集成测试")
class RealRedisCoordinatorTests(unittest.TestCase):

    def setUp(self):
        import redis
        self.client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        self.client.ping()
        self.prefix = f"ontology:test:{uuid.uuid4().hex}:"

    def tearDown(self):
        keys = list(self.client.scan_iter(match=self.prefix + "*", count=200))
        if keys:
            self.client.delete(*keys)
        self.client.close()

    def _config(self, **overrides):
        values = dict(backend="redis", redis_url=REDIS_URL,
                      redis_prefix=self.prefix, max_active=2,
                      max_active_per_user=1, max_queued_per_user=5,
                      max_queued=5, lease_seconds=60,
                      queued_lease_seconds=60, recovery_seconds=600)
        values.update(overrides)
        return CoordinatorConfig(**values)

    def _key(self, suffix):
        return f"{self.prefix}{suffix}"

    # -- basic protocol -------------------------------------------------------

    def test_claim_admit_release_roundtrip_on_real_redis(self):
        backend = _RedisBackend(self._config(max_active=1), self.client,
                                "inst-a")
        admitted = backend.claim("t1", "exec-a", "u1", 1)
        self.assertEqual(admitted[0].decision, "admitted")
        queued = backend.claim("t2", "exec-b", "u2", 1)
        self.assertEqual(queued[0].decision, "queued")
        # Real storage layout used by the Lua scripts: token value is the
        # execution id, the queue stores resource ids, meta is a hash.
        self.assertEqual(self.client.get(self._key("execution:t1:token")),
                         "exec-a")
        self.assertEqual(
            self.client.hget(self._key("execution:t2:meta"), "status"),
            "QUEUED")
        self.assertEqual(self.client.lrange(self._key("queue"), 0, -1), ["t2"])
        self.assertEqual(self.client.lrange(self._key("queue:u2"), 0, -1),
                         ["t2"])
        # Releasing the admitted run frees a slot for the queued one.
        backend.release("t1", admitted[0].execution_id,
                        admitted[0].fence_token, was_queued=False)
        self.assertEqual(backend.admit_next(), "t2")
        self.assertEqual(
            self.client.hget(self._key("execution:t2:meta"), "status"),
            "ADMITTED")
        backend.release("t2", queued[0].execution_id, queued[0].fence_token,
                        was_queued=False)
        self.assertIsNone(self.client.get(self._key("execution:t2:token")))
        self.assertEqual(self.client.lrange(self._key("queue"), 0, -1), [])

    def test_renew_and_release_require_correct_token(self):
        backend = _RedisBackend(self._config(), self.client, "inst-a")
        first = backend.claim("t1", "exec-a", "u1", 1)
        # Wrong execution id cannot renew or release.
        self.assertFalse(backend.heartbeat("t1", "wrong-exec"))
        backend.release("t1", "wrong-exec", first[0].fence_token,
                        was_queued=False)
        self.assertEqual(self.client.get(self._key("execution:t1:token")),
                         "exec-a")
        # Correct token renews and updates heartbeat metadata.
        self.assertTrue(backend.heartbeat("t1", first[0].execution_id))
        meta = self.client.hgetall(self._key("execution:t1:meta"))
        self.assertEqual(meta["execution_id"], "exec-a")
        self.assertEqual(meta["fence_token"], str(first[0].fence_token))
        # Correct release works and removes token + meta.
        backend.release("t1", first[0].execution_id, first[0].fence_token,
                        was_queued=False)
        self.assertIsNone(self.client.get(self._key("execution:t1:token")))
        self.assertIsNone(self.client.get(self._key("execution:t1:meta")))

    def test_stale_fence_cannot_release_new_execution(self):
        backend = _RedisBackend(self._config(), self.client, "inst-a")
        first = backend.claim("t1", "exec-1", "u1", 1)
        backend.release("t1", first[0].execution_id, first[0].fence_token,
                        was_queued=False)
        second = backend.claim("t1", "exec-2", "u1", 2)
        self.assertEqual(second[0].decision, "admitted")
        # Fence tokens are strictly increasing per resource.
        self.assertGreater(second[0].fence_token, first[0].fence_token)
        # Old execution + old fence must not release the new execution.
        backend.release("t1", first[0].execution_id, first[0].fence_token,
                        was_queued=False)
        self.assertEqual(self.client.get(self._key("execution:t1:token")),
                         "exec-2")
        self.assertTrue(backend.verify_fence(
            "t1", second[0].execution_id, second[0].fence_token))
        self.assertFalse(backend.verify_fence(
            "t1", first[0].execution_id, first[0].fence_token))
        backend.release("t1", second[0].execution_id, second[0].fence_token,
                        was_queued=False)

    # -- queue ownership and quotas ------------------------------------------

    def test_cancel_of_queued_item_cleans_queues_and_counters(self):
        backend = _RedisBackend(self._config(max_active=1), self.client,
                                "inst-a")
        admitted = backend.claim("t1", "exec-a", "u1", 1)
        queued = backend.claim("t2", "exec-b", "u1", 1)
        self.assertEqual(queued[0].decision, "queued")
        self.assertEqual(self.client.lrange(self._key("queue"), 0, -1),
                         ["t2"])
        self.assertTrue(
            backend.cancel("t2", queued[0].execution_id, queued[0].fence_token))
        # No ghost queue items and no leaked queued counter.
        self.assertEqual(self.client.lrange(self._key("queue"), 0, -1), [])
        self.assertEqual(self.client.lrange(self._key("queue:u1"), 0, -1), [])
        self.assertEqual(int(self.client.get(self._key("counters:queued"))
                             or 0), 0)
        backend.release("t1", admitted[0].execution_id,
                        admitted[0].fence_token, was_queued=False)

    def test_two_instances_share_global_and_per_user_quota(self):
        config = self._config(max_active=2)
        backend_a = _RedisBackend(config, self.client, "inst-a")
        backend_b = _RedisBackend(config, self.client, "inst-b")
        try:
            a1 = backend_a.claim("t1", "exec-a1", "u1", 1)
            self.assertEqual(a1[0].decision, "admitted")
            # u1's single active slot is cluster-scoped: instance B queues.
            b1 = backend_b.claim("t2", "exec-b1", "u1", 1)
            self.assertEqual(b1[0].decision, "queued")
            # A different user on B fills the second global active slot.
            c1 = backend_b.claim("t3", "exec-c1", "u2", 1)
            self.assertEqual(c1[0].decision, "admitted")
            self.assertEqual(int(self.client.get(self._key("counters:active"))
                                 or 0), 2)
            # No free slot yet: B's dispatcher cannot admit its own queued
            # task while the cluster active counter is at its cap.
            self.assertIsNone(backend_b.admit_next())
            # A frees a slot; B's dispatcher then admits its own queued task.
            backend_a.release("t1", a1[0].execution_id, a1[0].fence_token,
                              was_queued=False)
            self.assertEqual(backend_b.admit_next(), "t2")
            backend_b.release("t2", b1[0].execution_id, b1[0].fence_token,
                              was_queued=False)
            backend_b.release("t3", c1[0].execution_id, c1[0].fence_token,
                              was_queued=False)
        finally:
            self.assertEqual(self.client.lrange(self._key("queue"), 0, -1), [])

    def test_owner_affinity_blocks_other_instance_admit(self):
        config = self._config(max_active=1)
        backend_a = _RedisBackend(config, self.client, "inst-a")
        backend_b = _RedisBackend(config, self.client, "inst-b")
        try:
            a1 = backend_a.claim("t1", "exec-a1", "u1", 1)
            q2 = backend_b.claim("t2", "exec-b2", "u2", 1)
            self.assertEqual(a1[0].decision, "admitted")
            self.assertEqual(q2[0].decision, "queued")
            # t2's payload lives on B: A's dispatcher must not admit it even
            # though the queue is not empty.
            self.assertIsNone(backend_a.admit_next())
            self.assertEqual(
                self.client.hget(self._key("execution:t2:meta"),
                                 "owner_instance_id"), "inst-b")
            # A frees the only slot; A still cannot admit B's task, but B can.
            backend_a.release("t1", a1[0].execution_id, a1[0].fence_token,
                              was_queued=False)
            self.assertIsNone(backend_a.admit_next())
            self.assertEqual(backend_b.admit_next(), "t2")
            backend_b.release("t2", q2[0].execution_id, q2[0].fence_token,
                              was_queued=False)
        finally:
            self.assertEqual(self.client.lrange(self._key("queue"), 0, -1), [])

    # -- TTL, heartbeat and recovery -----------------------------------------

    def test_queued_lease_outlives_execution_ttl_without_ghost(self):
        config = self._config(max_active=1, lease_seconds=1,
                              queued_lease_seconds=5, recovery_seconds=30)
        backend = _RedisBackend(config, self.client, "inst-a")
        admitted = backend.claim("t1", "exec-a", "u1", 1)
        queued = backend.claim("t2", "exec-b", "u2", 1)
        self.assertEqual(admitted[0].decision, "admitted")
        self.assertEqual(queued[0].decision, "queued")
        time.sleep(1.2)
        # The admitted execution's token expired; the queued token is still
        # alive because it uses the longer queued lease TTL.
        self.assertIsNone(self.client.get(self._key("execution:t1:token")))
        self.assertEqual(self.client.get(self._key("execution:t2:token")),
                         "exec-b")
        self.assertEqual(
            self.client.hget(self._key("execution:t2:meta"), "status"),
            "QUEUED")
        # Recovery frees the expired admitted lease; the owner then admits its
        # own queued task.
        self.assertEqual(backend.recover_expired(), 1)
        self.assertEqual(backend.admit_next(), "t2")
        backend.release("t2", queued[0].execution_id, queued[0].fence_token,
                        was_queued=False)
        self.assertEqual(self.client.lrange(self._key("queue"), 0, -1), [])

    def test_ttl_expiry_recovery_then_reclaim(self):
        config = self._config(max_active=1, lease_seconds=1,
                              queued_lease_seconds=2, recovery_seconds=10)
        backend = _RedisBackend(config, self.client, "inst-a")
        first = backend.claim("t1", "exec-1", "u1", 1)
        self.assertEqual(first[0].decision, "admitted")
        time.sleep(1.2)
        self.assertIsNone(self.client.get(self._key("execution:t1:token")))
        # The meta survives inside the recovery window so a dead owner can be
        # detected and the counters corrected atomically.
        self.assertEqual(backend.recover_expired(), 1)
        self.assertEqual(int(self.client.get(self._key("counters:active"))
                             or 0), 0)
        second = backend.claim("t1", "exec-2", "u1", 2)
        self.assertEqual(second[0].decision, "admitted")
        backend.release("t1", second[0].execution_id, second[0].fence_token,
                        was_queued=False)

    def test_multi_instance_recovery_single_winner(self):
        config = self._config(max_active=1, lease_seconds=1,
                              queued_lease_seconds=1, recovery_seconds=30)
        backend_a = _RedisBackend(config, self.client, "inst-a")
        backend_b = _RedisBackend(config, self.client, "inst-b")
        admitted = backend_a.claim("t1", "exec-a1", "u1", 1)
        queued = backend_a.claim("t2", "exec-a2", "u2", 1)
        self.assertEqual(admitted[0].decision, "admitted")
        self.assertEqual(queued[0].decision, "queued")
        time.sleep(1.2)
        # Both tokens expired (1s leases) but both metas are still inside the
        # recovery window; two instances race to recover the same executions.
        barrier = threading.Barrier(2)
        results = []
        results_lock = threading.Lock()

        def recover(backend):
            barrier.wait(timeout=5)
            try:
                count = backend.recover_expired()
            except Exception:  # noqa: BLE001 - record and continue
                count = -1
            with results_lock:
                results.append(count)

        threads = [threading.Thread(target=recover, args=(backend_a,)),
                   threading.Thread(target=recover, args=(backend_b,))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        # Exactly the two expired executions are recovered (each exactly once),
        # never more, even with two instances racing.
        self.assertEqual(sum(results), 2)
        self.assertEqual(int(self.client.get(self._key("counters:active"))
                             or 0), 0)
        self.assertEqual(int(self.client.get(self._key("counters:queued"))
                             or 0), 0)
        self.assertEqual(self.client.lrange(self._key("queue"), 0, -1), [])
        # A second pass finds nothing.
        self.assertEqual(backend_b.recover_expired(), 0)

    # -- full coordinator lifecycle ------------------------------------------

    def test_coordinator_lifecycle_on_real_redis(self):
        adapter = _Adapter("inst-a")
        coordinator = ExecutionCoordinator(self._config(max_active=1), adapter,
                                           redis_client=self.client)
        try:
            first = coordinator.claim("t1", "exec-1", "u1")
            self.assertEqual(first.decision, "admitted")
            queued = coordinator.claim("t2", "exec-2", "u2")
            self.assertEqual(queued.decision, "queued")
            deadline = time.time() + 10
            while len(adapter.started) < 2 and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(len(adapter.started), 2)
            # Both workers finished; no lease/queue residue remains.
            deadline = time.time() + 10
            while (self.client.get(self._key("execution:t2:token"))
                   and time.time() < deadline):
                time.sleep(0.05)
            self.assertIsNone(self.client.get(self._key("execution:t1:token")))
            self.assertIsNone(self.client.get(self._key("execution:t2:token")))
            self.assertEqual(self.client.lrange(self._key("queue"), 0, -1), [])
            self.assertEqual(int(self.client.get(self._key("counters:active"))
                                 or 0), 0)
            self.assertEqual(int(self.client.get(self._key("counters:queued"))
                                 or 0), 0)
            coordination = coordinator.metrics()["coordination"]
            self.assertEqual(coordination["backend"], "redis")
            self.assertTrue(coordination["multiHostSafe"])
            self.assertEqual(coordination["quotaScope"], "cluster")
            self.assertEqual(coordination["queueScope"], "cluster")
        finally:
            coordinator.shutdown()


if __name__ == "__main__":
    unittest.main()
