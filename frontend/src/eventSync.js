// Unified event identity + idempotent merge for both workbench (47313) and
// standalone modeling (47314) sessions.
//
// Identity priority:
//   1. clientMessageId (optimistic client messages) -> cm:<scope>:<id>
//   2. persistent server sequence (seq)             -> sea:<scope>:<seq>
//   3. stable compatibility fingerprint for legacy  -> sea:<scope>:fp:<hash>
// Array indexes are never used as event identity.

function serverSeq(event) {
  if (!event || typeof event !== "object") return null;
  const raw = event.seq ?? event._seq ?? event.sequence;
  const seq = Number(raw);
  return Number.isFinite(seq) && seq >= 0 ? seq : null;
}

function eventClock(event) {
  if (!event || typeof event !== "object") return null;
  const raw = event._receivedAt ?? event.timestamp;
  if (raw == null || raw === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  return value > 1e11 ? value : value > 1e9 ? value * 1000 : value;
}

function stableHash(value) {
  // FNV-1a 32-bit; deterministic across reloads so legacy events that lack a
  // server sequence still merge to the same identity on every path.
  let hash = 0x811c9dc5;
  const text = String(value ?? "");
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(36);
}

function legacyFingerprint(event) {
  const type = String(event?.type ?? "");
  const id = String(event?.id ?? event?.tool_use_id ?? "");
  const timestamp = String(event?.timestamp ?? "");
  const text = String(event?.text ?? event?.content ?? "");
  return stableHash(`${type}|${id}|${timestamp}|${text}`);
}

export function eventIdentity(event, scope = "default") {
  if (!event || typeof event !== "object") return null;
  const clientMessageId = String(event.clientMessageId ?? "").trim();
  if (clientMessageId) return `cm:${scope}:${clientMessageId}`;
  const seq = serverSeq(event);
  if (seq != null) return `sea:${scope}:${seq}`;
  return `sea:${scope}:fp:${legacyFingerprint(event)}`;
}

// React keys: prefer the same identity the merge uses. Synthetic bubbles that
// carry an explicit `_key` (client-only UI, never persisted) use it directly.
export function eventKey(event, scope = "default", index = 0) {
  if (event && typeof event === "object" && event._key) return `synth:${event._key}`;
  return eventIdentity(event, scope) || `${scope}:idx:${index}`;
}

// Idempotent full merge. Any event reaching this function through the execute
// response, SSE, polling, /events?since=, history snapshots, forward
// pagination, or cache restoration is kept exactly once. Events are then
// ordered by server seq (ascending); legacy events fall back to wall-clock.
export function mergeEvents(existing, incoming, scope = "default") {
  const merged = new Map();
  const absorb = (list) => {
    if (!Array.isArray(list)) return;
    for (const event of list) {
      if (!event || typeof event !== "object") continue;
      const identity = eventIdentity(event, scope);
      if (!identity) continue;
      if (!merged.has(identity)) merged.set(identity, event);
    }
  };
  absorb(existing);
  absorb(incoming);
  const events = Array.from(merged.values());
  events.sort((a, b) => {
    const seqA = serverSeq(a);
    const seqB = serverSeq(b);
    if (seqA != null && seqB != null && seqA !== seqB) return seqA - seqB;
    const clockA = eventClock(a);
    const clockB = eventClock(b);
    if (clockA != null && clockB != null && clockA !== clockB) return clockA - clockB;
    return 0;
  });
  return events;
}

// Streaming append keeps the identity-dedupe window small: real-time deltas
// arrive in order, so a duplicated packet is always near the tail. Adjacent
// text/thinking tokens still concatenate exactly as normalizeEvents does.
export function appendStreamEvent(previous, event, scope = "default") {
  const events = Array.isArray(previous) ? previous : [];
  const incoming = event && typeof event === "object"
    ? event
    : { type: "text", text: String(event ?? "") };
  const identity = eventIdentity(incoming, scope);
  if (identity) {
    const start = Math.max(0, events.length - 64);
    for (let index = events.length - 1; index >= start; index -= 1) {
      if (eventIdentity(events[index], scope) === identity) return events;
    }
  }
  if (incoming.type === "text" || incoming.type === "thinking") {
    const last = events[events.length - 1];
    if (last?.type === incoming.type) {
      return [...events.slice(0, -1), { ...last, text: `${last.text || ""}${incoming.text || ""}` }];
    }
  }
  return [...events, incoming];
}

// Cursor semantics: the cursor is the next unread absolute seq (0-based
// position into the persisted event journal). Prefer the server-provided
// absolute position (nextCursor/eventEnd) over any locally counted length;
// `start + received.length` is only the legacy fallback.
export function nextCursor(window, received) {
  if (window && Number.isFinite(Number(window.nextCursor))) return Number(window.nextCursor);
  if (window && Number.isFinite(Number(window.eventEnd))) return Number(window.eventEnd);
  const start = Number(window?.eventStart ?? 0);
  const count = Array.isArray(received) ? received.length : 0;
  return start + count;
}
