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
