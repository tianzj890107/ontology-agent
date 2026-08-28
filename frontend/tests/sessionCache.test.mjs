import test from "node:test";
import assert from "node:assert/strict";
import {
  artifactSignature,
  createInFlightRegistry,
  createOntologyGraphCache,
  createSessionCache,
} from "../src/sessionCache.js";

function artifact(path, extra = {}) {
  return {
    name: path.split("/").pop(),
    path,
    size: 100,
    mtime: 1000,
    ...extra,
  };
}

function fakeGraph(entries) {
  return {
    availability: { logicalEntity: Boolean(entries.length) },
    nodes: entries.map(([layer, text]) => ({ id: `${layer}:${text}` })),
    links: [],
  };
}

function makeCache(options = {}) {
  const calls = [];
  const cache = createOntologyGraphCache({
    maxEntries: 10,
    loadText: async (entry) => {
      calls.push(entry.path);
      return `csv:${entry.path}`;
    },
    buildGraph: fakeGraph,
    ...options,
  });
  return { cache, calls };
}

const artifactsA = () => [
  ["businessObject", artifact("output/business_objects.csv")],
  ["logicalEntity", artifact("output/logical_entities.csv")],
];
const artifactsA2 = () => [
  ["businessObject", artifact("output/business_objects.csv", { mtime: 2000 })],
  ["logicalEntity", artifact("output/logical_entities.csv")],
];

test("createSessionCache 按 LRU 淘汰且保护活动 key", () => {
  const evicted = [];
  const cache = createSessionCache({ maxEntries: 2, onEvict: (key) => evicted.push(key) });
  cache.set("a", 1);
  cache.set("b", 2);
  cache.get("a");
  cache.set("c", 3);
  cache.evictToFit("a");
  assert.deepEqual(evicted, ["b"]);
  assert.equal(cache.peek("a"), 1);
  assert.equal(cache.peek("c"), 3);
  assert.equal(cache.has("b"), false);
});

test("createSessionCache get 提升新鲜度，size/delete/clear 正确", () => {
  const cache = createSessionCache({ maxEntries: 3 });
  cache.set("a", 1);
  cache.set("b", 2);
  cache.set("c", 3);
  cache.get("a");
  cache.set("d", 4);
  cache.evictToFit();
  // b (oldest untouched) is evicted, a survives thanks to the get().
  assert.equal(cache.has("a"), true);
  assert.equal(cache.has("b"), false);
  assert.equal(cache.size(), 3);
  cache.delete("c");
  assert.equal(cache.has("c"), false);
  cache.clear();
  assert.equal(cache.size(), 0);
});

test("artifactSignature 对相同产物稳定且顺序无关", () => {
  const first = artifactSignature(artifactsA());
  const second = artifactSignature([...artifactsA()].reverse());
  assert.equal(first, second);
  assert.ok(first.includes("output/business_objects.csv"));
});

test("artifactSignature 在路径或元数据变化时变化", () => {
  const base = artifactSignature(artifactsA());
  assert.notEqual(base, artifactSignature(artifactsA2()));
  const renamed = [
    ["logicalEntity", artifact("output/renamed_entities.csv")],
    ...artifactsA(),
  ];
  assert.notEqual(base, artifactSignature(renamed));
});

test("首次 ensure 构建并缓存 graph，再次打开不重复下载 CSV", async () => {
  const { cache, calls } = makeCache();
  const first = await cache.ensure("run:1", artifactsA(), {});
  assert.equal(first.availability.logicalEntity, true);
  assert.equal(cache.getStatus("run:1", artifactsA()).status, "ready");
  await cache.ensure("run:1", artifactsA(), {});
  assert.equal(calls.length, 2); // two CSVs, one build, no re-download
  assert.deepEqual(calls, ["output/business_objects.csv", "output/logical_entities.csv"]);
});

test("预加载与按钮点击共享同一个在途 Promise", async () => {
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const cache = createOntologyGraphCache({
    loadText: async (entry) => { calls += 1; await gate; return `csv:${entry.path}`; },
    buildGraph: fakeGraph,
  });
  const preload = cache.ensure("run:1", artifactsA(), {});
  const click = cache.ensure("run:1", artifactsA(), {});
  assert.equal(cache.getStatus("run:1", artifactsA()).status, "loading");
  release();
  const [preloaded, clicked] = await Promise.all([preload, click]);
  assert.equal(calls, 2);
  assert.equal(preloaded, clicked);
  assert.equal(cache.getStatus("run:1", artifactsA()).status, "ready");
});

test("产物签名变化后 graph 缓存失效并重新构图", async () => {
  const { cache, calls } = makeCache();
  await cache.ensure("run:1", artifactsA(), {});
  const stale = cache.getStatus("run:1", artifactsA2());
  assert.equal(stale.status, "stale");
  const reloaded = await cache.ensure("run:1", artifactsA2(), {});
  assert.ok(reloaded);
  assert.equal(cache.getStatus("run:1", artifactsA()).status, "stale");
  assert.equal(cache.getStatus("run:1", artifactsA2()).status, "ready");
  assert.equal(calls.length, 4); // full rebuild after invalidation
});

test("预加载失败记录错误且不阻止会话，失败后点击可重试", async () => {
  let calls = 0;
  const cache = createOntologyGraphCache({
    loadText: async (entry) => {
      calls += 1;
      if (calls <= 2) throw new Error(`CSV 读取失败: ${entry.path}`);
      return `csv:${entry.path}`;
    },
    buildGraph: fakeGraph,
  });
  const failing = cache.ensure("run:1", artifactsA(), {});
  await assert.rejects(failing, /CSV 读取失败/);
  const status = cache.getStatus("run:1", artifactsA());
  assert.equal(status.status, "error");
  assert.match(status.error, /CSV 读取失败/);
  const retried = await cache.ensure("run:1", artifactsA(), {});
  assert.ok(retried);
  assert.equal(cache.getStatus("run:1", artifactsA()).status, "ready");
});

test("A 的迟到响应不能覆盖 B 的缓存条目", async () => {
  const gates = new Map();
  const waiters = [];
  const cache = createOntologyGraphCache({
    loadText: async (entry) => {
      const gate = new Promise((resolve) => waiters.push({ path: entry.path, resolve }));
      gates.set(entry.path, gate);
      await gate;
      return `csv:${entry.path}`;
    },
    buildGraph: fakeGraph,
  });
  const slowA = cache.ensure("scope:A", artifactsA(), {});
  // B starts with a different signature while A is still in flight.
  const fastB = cache.ensure("scope:B", artifactsA2(), {});
  for (const waiter of waiters) waiter.resolve();
  await fastB;
  await slowA;
  assert.equal(cache.getStatus("scope:B", artifactsA2()).status, "ready");
  assert.equal(cache.getStatus("scope:A", artifactsA()).status, "ready");
});

test("同一 scope 旧签名的迟到响应不会覆盖新签名条目", async () => {
  const waiters = [];
  const cache = createOntologyGraphCache({
    loadText: async (entry) => {
      const gate = new Promise((resolve) => waiters.push({ path: entry.path, mtime: entry.mtime, resolve }));
      await gate;
      return `csv:${entry.path}`;
    },
    buildGraph: fakeGraph,
  });
  const oldLoad = cache.ensure("run:1", artifactsA(), {});
  // The file list changes mid-flight: a newer signature load starts.
  const newLoad = cache.ensure("run:1", artifactsA2(), {});
  // loadText is invoked synchronously up to its gate in ensure order, so the
  // first two waiters belong to the old signature and the last two to the new.
  const oldWaiters = waiters.slice(0, 2);
  const newWaiters = waiters.slice(2);
  // Resolve the newer signature first, then let the old request come back late.
  for (const waiter of newWaiters) waiter.resolve();
  await newLoad;
  for (const waiter of oldWaiters) waiter.resolve();
  await oldLoad;
  assert.equal(cache.getStatus("run:1", artifactsA2()).status, "ready");
  assert.equal(cache.getStatus("run:1", artifactsA()).status, "stale");
});

test("LRU 上限只淘汰非活动 scope，活动 scope 保留", async () => {
  const { cache } = makeCache({ maxEntries: 2 });
  await cache.ensure("a", artifactsA(), {});
  await cache.ensure("b", artifactsA2(), {});
  await cache.ensure("c", artifactsA(), {});
  cache.evictToFit("c");
  assert.equal(cache.getStatus("c", artifactsA()).status, "ready");
  // a was touched first and has not been read since -> evicted.
  assert.equal(cache.getStatus("a", artifactsA()).status, "empty");
  assert.equal(cache.getStatus("b", artifactsA2()).status, "ready");
  cache.evictToFit("b");
  assert.equal(cache.getStatus("b", artifactsA2()).status, "ready");
});

test("刷新页面后新应用实例不继承旧内存缓存", async () => {
  const first = makeCache();
  const second = makeCache();
  await first.cache.ensure("run:1", artifactsA(), {});
  assert.equal(first.cache.getStatus("run:1", artifactsA()).status, "ready");
  assert.equal(second.cache.getStatus("run:1", artifactsA()).status, "empty");
  assert.equal(second.calls.length, 0);
});

test("缓存 key 按 scope 隔离，文件列表不会串到其他会话", async () => {
  const { cache, calls } = makeCache();
  await cache.ensure("run:1", artifactsA(), {});
  await cache.ensure("run:2", artifactsA2(), {});
  assert.equal(calls.length, 4);
  assert.equal(cache.getStatus("run:1", artifactsA()).status, "ready");
  assert.equal(cache.getStatus("run:2", artifactsA()).status, "stale");
});

test("getStatus 区分 empty/loading/ready/error/stale", async () => {
  const { cache } = makeCache();
  assert.equal(cache.getStatus("run:1", artifactsA()).status, "empty");
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const blocking = createOntologyGraphCache({
    loadText: async (entry) => { await gate; return `csv:${entry.path}`; },
    buildGraph: fakeGraph,
  });
  const pending = blocking.ensure("run:1", artifactsA(), {});
  assert.equal(blocking.getStatus("run:1", artifactsA()).status, "loading");
  release();
  await pending;
  assert.equal(blocking.getStatus("run:1", artifactsA()).status, "ready");
  assert.equal(cache.getStatus("run:1", artifactsA()).status, "empty");
});

test("createInFlightRegistry 去重与清理", async () => {
  const registry = createInFlightRegistry();
  const p = Promise.resolve("g");
  registry.set("k", p);
  assert.equal(registry.get("k"), p);
  assert.equal(registry.has("k"), true);
  registry.delete("k");
  assert.equal(registry.has("k"), false);
  assert.deepEqual(registry.keys(), []);
});
