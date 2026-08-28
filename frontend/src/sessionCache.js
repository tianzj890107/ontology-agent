// Bounded in-memory session caches shared by the 47313 task workbench and the
// 47314 standalone modeling service. Everything here is pure and independent of
// React/DOM so it can be unit-tested without a browser.
//
// Scope: one browser page lifetime only. No localStorage, sessionStorage or
// IndexedDB is used; a page refresh starts a fresh cache, which the apps
// deliberately allow.

const MAX_DEFAULT = 10;

// LRU key-value store. `get`/`set`/`touch` bump recency; `evictToFit` drops
// the least-recently-used entries beyond `maxEntries`, never the protected
// (currently active) key. `onEvict` is invoked with (key, value) so callers
// can release related working state when an entry is dropped.
export function createSessionCache(options = {}) {
  const maxEntries = Math.max(1, Number(options.maxEntries) || MAX_DEFAULT);
  const onEvict = typeof options.onEvict === "function" ? options.onEvict : () => {};
  const map = new Map();
  let clock = 0;
  return {
    size: () => map.size,
    has: (key) => map.has(key),
    get(key) {
      const hit = map.get(key);
      if (!hit) return undefined;
      hit.lastUsed = ++clock;
      return hit.value;
    },
    peek(key) {
      return map.get(key)?.value;
    },
    set(key, value) {
      map.set(key, { value, lastUsed: ++clock });
      return this;
    },
    delete(key) {
      return map.delete(key);
    },
    touch(key) {
      const hit = map.get(key);
      if (hit) hit.lastUsed = ++clock;
    },
    keys: () => [...map.keys()],
    evictToFit(protectedKey) {
      while (map.size > maxEntries) {
        let oldestKey = null;
        let oldestUsed = Infinity;
        for (const [key, hit] of map) {
          if (key === protectedKey) continue;
          if (hit.lastUsed < oldestUsed) {
            oldestUsed = hit.lastUsed;
            oldestKey = key;
          }
        }
        if (oldestKey == null) break;
        const removed = map.get(oldestKey).value;
        map.delete(oldestKey);
        onEvict(oldestKey, removed);
      }
    },
    clear() {
      map.clear();
    },
  };
}

// Stable signature for the artifact set feeding an ontology graph. Only the
// server-provided immutable metadata (path, size, mtime/modifiedAt, version,
// hash/etag) is used; content is never downloaded just to compute the
// signature. Sorted by path so identical sets produce identical signatures.
export function artifactSignature(artifacts) {
  const rows = [];
  const push = (item) => {
    // Accept both bare artifacts and [layer, artifact] pairs (the shape the
    // apps pass from selectOntologyArtifacts().entries()).
    const artifact = Array.isArray(item) && item.length === 2 && item[1] && typeof item[1] === "object"
      ? item[1]
      : item;
    const path = String(artifact?.path || artifact?.name || "").trim();
    if (!path) return;
    const fields = [
      artifact?.size,
      artifact?.mtime,
      artifact?.mtimeMs,
      artifact?.modifiedAt,
      artifact?.updatedAt,
      artifact?.version,
      artifact?.hash,
      artifact?.etag,
      artifact?.checksum,
      artifact?.md5,
      artifact?.sha256,
    ];
    rows.push(`${path}|${fields.map((value) => (value == null ? "" : String(value))).join("|")}`);
  };
  if (artifacts instanceof Map) {
    for (const value of artifacts.values()) push(value);
  } else if (Array.isArray(artifacts)) {
    for (const artifact of artifacts) push(artifact);
  } else if (artifacts && typeof artifacts[Symbol.iterator] === "function") {
    for (const artifact of artifacts) push(artifact);
  }
  rows.sort();
  return rows.join("\n");
}

// Promise registry used to deduplicate in-flight graph loads. Keyed by
// `scopeId:signature` so a session preload and a user click on the same
// artifact set share exactly one network/parse/build pipeline.
export function createInFlightRegistry() {
  const map = new Map();
  return {
    has: (key) => map.has(key),
    get: (key) => map.get(key),
    set: (key, promise) => {
      map.set(key, promise);
    },
    delete: (key) => map.delete(key),
    keys: () => [...map.keys()],
  };
}

function normalizeArtifacts(artifacts) {
  if (artifacts instanceof Map) return [...artifacts.entries()];
  if (Array.isArray(artifacts)) return artifacts;
  if (artifacts && typeof artifacts[Symbol.iterator] === "function") return [...artifacts];
  return [];
}

// Per-scope (taskId/runId) ontology graph cache.
//
//   loadText(artifact, context) -> Promise<string>   fetch one CSV as text
//   buildGraph(entries)         -> graph             entries: [[layer, text]]
//
// `ensure(scopeId, artifacts, context)` downloads/builds once per
// `scopeId:signature`, stores the graph under `scopeId`, records failures in
// the entry (so a later click can retry), and resolves with the graph. A load
// started for an older signature never overwrites a newer entry when the file
// list changed mid-flight. `getStatus` distinguishes empty/stale/loading/
// error/ready. `evictToFit(activeScopeId)` bounds memory to `maxEntries`
// scopes while keeping the active scope.
export function createOntologyGraphCache(options = {}) {
  const maxEntries = Math.max(1, Number(options.maxEntries) || MAX_DEFAULT);
  const loadText = options.loadText;
  const buildGraph = options.buildGraph;
  if (typeof loadText !== "function") throw new Error("createOntologyGraphCache requires loadText");
  if (typeof buildGraph !== "function") throw new Error("createOntologyGraphCache requires buildGraph");
  const entries = new Map();
  const inflight = createInFlightRegistry();
  let clock = 0;

  const entryOf = (scopeId) => entries.get(scopeId) || null;

  function getStatus(scopeId, artifacts) {
    const signature = artifactSignature(artifacts);
    const entry = entryOf(scopeId);
    if (!entry) return { status: "empty", signature };
    if (entry.signature !== signature) return { status: "stale", signature };
    if (entry.graph) return { status: "ready", graph: entry.graph, signature };
    if (entry.loading || inflight.has(`${scopeId}:${signature}`)) return { status: "loading", signature };
    if (entry.graphError) return { status: "error", error: entry.graphError, signature };
    return { status: "empty", signature };
  }

  function ensure(scopeId, artifacts, context = {}) {
    const signature = artifactSignature(artifacts);
    const key = `${scopeId}:${signature}`;
    const existing = inflight.get(key);
    if (existing) return existing;
    const current = entryOf(scopeId);
    if (current?.graph && current.signature === signature) return Promise.resolve(current.graph);
    entries.set(scopeId, {
      ...(current || { signature: "", graph: null, graphError: null }),
      signature,
      loading: true,
      lastUsed: ++clock,
    });
    const promise = (async () => {
      const items = normalizeArtifacts(artifacts);
      const texts = await Promise.all(items.map(async ([layer, artifact]) => [layer, await loadText(artifact, context)]));
      const graph = await buildGraph(texts);
      const latest = entryOf(scopeId);
      if (latest && latest.signature !== signature) return null;
      entries.set(scopeId, { signature, graph, graphError: null, loading: false, lastUsed: ++clock });
      return graph;
    })();
    const wrapped = promise.then((graph) => {
      inflight.delete(key);
      return graph;
    }, (error) => {
      inflight.delete(key);
      const latest = entryOf(scopeId);
      if (!latest || latest.signature === signature) {
        entries.set(scopeId, { signature, graph: null, graphError: error?.message || String(error), loading: false, lastUsed: ++clock });
      }
      throw error;
    });
    inflight.set(key, wrapped);
    return wrapped;
  }

  function evictToFit(activeScopeId) {
    while (entries.size > maxEntries) {
      let oldestKey = null;
      let oldestUsed = Infinity;
      for (const [key, entry] of entries) {
        if (key === activeScopeId) continue;
        if ((entry.lastUsed || 0) < oldestUsed) {
          oldestUsed = entry.lastUsed || 0;
          oldestKey = key;
        }
      }
      if (oldestKey == null) break;
      entries.delete(oldestKey);
    }
  }

  return { getStatus, ensure, evictToFit, size: () => entries.size };
}

// ---------------------------------------------------------------------------
// Task-session open/restore helpers (pure, React-free, unit-testable).
//
// The 47313 workbench computes one namespaced cache key per task so the
// session cache, the ontology graph cache, LRU protection and request
// generation gating all agree on the same key.  A mission task is keyed by
// mission identity + task id; a plain task falls back to `task:<id>` so the
// same local id can never leak across identity spaces.
// ---------------------------------------------------------------------------

export function taskCacheKey(task, fallbackMission = null) {
  const id = String(task?.id || "").trim();
  if (!id) return "";
  const repositoryId = String(task?.repositoryId || fallbackMission?.repositoryId || "").trim();
  const taskCode = String(task?.taskCode || fallbackMission?.taskCode || "").trim();
  if (repositoryId && taskCode) return `mission:${repositoryId}:${taskCode}:${id}`;
  return `task:${id}`;
}

// Reads a cached session snapshot and bumps its LRU recency (restoring a
// session is a use). Returns undefined when the key is absent.
export function sessionSnapshotFor(cache, taskKey) {
  if (!cache || !taskKey) return undefined;
  return cache.get(taskKey);
}

// Normalizes a raw cache entry into the fields openTask needs to switch the
// visible session immediately, before any detail request completes.
export function restoreTaskPlan(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return null;
  return {
    events: Array.isArray(snapshot.events) ? snapshot.events : [],
    files: Array.isArray(snapshot.files) ? snapshot.files : [],
    filesTaskId: String(snapshot.filesTaskId || ""),
    logWindow: snapshot.logWindow || null,
    detail: snapshot.detail || null,
  };
}

// Log-window restore rule: the server tail window is authoritative for
// total/cursor, but a previously loaded older range keeps its smaller start
// so reopening a session never re-downloads history it already holds.
export function mergeLogWindow(cachedWindow, freshWindow) {
  if (!freshWindow || typeof freshWindow !== "object") return cachedWindow || null;
  const restoredStart = Number(cachedWindow?.start);
  const freshStart = Number(freshWindow.start ?? 0);
  if (Number.isFinite(restoredStart) && restoredStart < freshStart) {
    return { ...freshWindow, start: restoredStart };
  }
  return freshWindow;
}

// Merges a patch into the cached session and bounds the cache, never evicting
// the currently active namespaced key. `activeKey` must be the namespaced key,
// never a bare task id.
export function commitSessionSnapshot(cache, taskKey, patch, activeKey) {
  if (!cache || !taskKey) return undefined;
  const current = cache.get(taskKey) || {};
  cache.set(taskKey, { ...current, ...patch });
  cache.evictToFit(activeKey);
  return cache.peek(taskKey);
}

// Generation gate for fast task/run switching. Each open of a session bumps
// the generation; a late response can still write its own session cache but
// `isCurrent` tells it whether it may touch visible React state.
export function createOpenGate() {
  let generation = 0;
  return {
    begin() {
      generation += 1;
      return generation;
    },
    isCurrent(candidate) {
      return candidate === generation;
    },
    current() {
      return generation;
    },
  };
}

// Generation gate for mission-info requests (bootstrap, history-switch and
// refresh all share one coordinator). `begin(key)` marks the newest request;
// `isCurrent(request)` is the single commit gate, so a slow mission response
// for a superseded session can never overwrite the visible mission context or
// clear its loading flag. The key is the mission identity
// (repositoryId:taskCode:taskType) so different mission spaces never share
// visible state.
export function createMissionCoordinator() {
  let generation = 0;
  let identityKey = "";
  return {
    begin(key) {
      generation += 1;
      identityKey = String(key || "");
      return { generation, key: String(key || "") };
    },
    isCurrent(request) {
      return Boolean(
        request
        && request.generation === generation
        && String(request.key || "") === identityKey
      );
    },
    current() {
      return { generation, key: identityKey };
    },
  };
}
