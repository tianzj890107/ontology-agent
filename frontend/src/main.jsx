import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Alert,
  App as AntApp,
  Button,
  Checkbox,
  ConfigProvider,
  Divider,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Popover,
  Select,
  Slider,
  Spin,
  Switch,
  Tag,
  Tooltip,
  message,
} from "antd";
import "./styles.css";
import { formatDisplayValue, isNumericDisplayValue } from "./numberFormat.js";
import { appendStreamEvent, eventKey, mergeEvents, nextCursor } from "./eventSync.js";
import { ONTOLOGY_LAYER_DEFINITIONS } from "./ontologyRadialLayout.js";
import {
  createRadialLayoutCache,
  layoutIsForViewport,
  normalizeViewport,
  ontologyDataFingerprint,
  prepareRadialLayout,
  radialCacheKey,
  radialGraphOption,
  readViewport,
} from "./ontologyRadialPrecompute.js";
import { buildOntologyGraph } from "./ontologyGraphModel.js";
import { ONTOLOGY_LAYOUT_OPTIONS, ontologyLayoutOption } from "./ontologyLayoutOptions.js";

const OntologySigmaPreview = React.lazy(() => import("./OntologySigmaPreview.jsx"));

const MISSION = window.__MISSION__?.taskCode ? window.__MISSION__ : null;
const STANDALONE = Boolean(window.__STANDALONE_MODELING__);
const $json = (value) => JSON.stringify(value, null, 2);
const esc = (value) => String(value ?? "");

function hasMissionOutputFiles(files = []) {
  return files.some((file) => String(file?.path || "").replaceAll("\\", "/").startsWith("output/"));
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...options });
  } catch (error) {
    if (error?.name === "AbortError") return { _aborted: true };
    return { error: `网络连接失败: ${error?.message || "无法连接服务"}` };
  }
  let body;
  try {
    body = await response.json();
  } catch {
    body = { error: `接口返回异常(${response.status})` };
  }
  if (!response.ok && !body.error) body.error = body.msg || `请求失败(${response.status})`;
  if (response.status === 401) body.error = body.error || "未获取到外部本体平台登录态，请从本体平台进入";
  return body;
}

function missionIdentity(task = null) {
  const repositoryId = String(task?.repositoryId || MISSION?.repositoryId || "").trim();
  const taskCode = String(task?.taskCode || MISSION?.taskCode || "").trim();
  if (!repositoryId || !taskCode) return null;
  return { repositoryId, taskCode };
}

function missionQuery(extra = {}, task = null) {
  const identity = missionIdentity(task);
  if (!identity) return "";
  const query = new URLSearchParams({ ...identity, ...extra });
  return `&${query.toString()}`;
}

function missionSearch(extra = {}, task = null) {
  const query = missionQuery(extra, task);
  return query ? `?${query.slice(1)}` : "";
}

function relativeTime(timestamp) {
  const seconds = Math.max(0, Date.now() / 1000 - Number(timestamp || 0));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function truncateTitle(value, max = 15) {
  const text = String(value || "");
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

const STANDALONE_ARTIFACTS = [
  "business_objects.csv",
  "logical_entities.csv",
  "business_attributes.csv",
  "entity_relations.csv",
  "business_rules.csv",
  "actions.csv",
  "terms.csv",
  "indicators.csv",
];
const STANDALONE_ARTIFACT_LABELS = {
  "business_objects.csv": "业务对象",
  "logical_entities.csv": "逻辑实体",
  "business_attributes.csv": "业务属性",
  "entity_relations.csv": "实体关系",
  "business_rules.csv": "业务规则",
  "actions.csv": "动作",
  "terms.csv": "术语",
  "indicators.csv": "指标",
};

const ONTOLOGY_ARTIFACT_ALIASES = {
  businessObject: ["business_objects.csv"],
  logicalEntity: ["logical_entities.csv"],
  businessAttribute: ["business_attributes.csv"],
  metric: ["metrics.csv", "indicators.csv", "indicator.csv", "atomic_indicators.csv", "composite_indicators.csv"],
  businessRule: ["business_rules.csv", "rules.csv"],
};
const ONTOLOGY_ARTIFACT_NAMES = new Set(Object.values(ONTOLOGY_ARTIFACT_ALIASES).flat());

function selectOntologyArtifacts(files, outputMarker) {
  const byName = new Map();
  (files || []).forEach((file) => {
    const path = String(file?.path || "");
    const name = path.replaceAll("\\", "/").split("/").pop();
    if (ONTOLOGY_ARTIFACT_NAMES.has(name) && (!byName.has(name) || path.includes(outputMarker))) byName.set(name, path);
  });
  const selected = new Map();
  Object.entries(ONTOLOGY_ARTIFACT_ALIASES).forEach(([layer, aliases]) => {
    const name = aliases.find((candidate) => byName.has(candidate));
    if (name) selected.set(layer, { name, path: byName.get(name) });
  });
  return selected.has("logicalEntity") ? selected : null;
}

function standaloneRunTitle(run) {
  const explicit = [run?.title, run?.name]
    .map((value) => String(value || "").trim())
    .find((value) => value && value.length <= 48);
  if (explicit) return explicit;
  const prompt = String(run?.prompt || "").trim();
  // Empty-prompt runs receive the built-in instruction, which is execution
  // input rather than a human-facing title. Keep the same short title from
  // creation through every later status instead of falling back to the prompt.
  if (!prompt || prompt.length > 48 || prompt.startsWith("请直接读取当前任务 input/")) return "本体建模";
  return prompt;
}

function formatRunCreatedAt(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "—";
  const date = new Date(numeric < 1e12 ? numeric * 1000 : numeric);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function statusLabel(status) {
  if (status === "BLOCKED") return "EXECUTED";
  if (status === "ANALYZING") return "EXECUTING";
  return status;
}

async function standaloneApi(path, apiKey, options = {}, retrySession = true) {
  let response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: { ...(options.headers || {}), ...(apiKey ? { "X-Modeling-API-Key": apiKey } : {}) },
    });
  } catch (error) {
    if (error?.name === "AbortError") return { _aborted: true };
    return { error: `网络连接失败: ${error?.message || "无法连接服务"}` };
  }
  // The standalone server keeps browser-session ownership in memory. A
  // restart can invalidate the old cookie while the already-rendered history
  // list still contains valid run IDs. Refresh the root once to obtain a new
  // browser session, then retry the original request so BLOCKED/FAILED runs
  // remain viewable without requiring Continue or a manual page reload.
  if (response.status === 401 && retrySession && typeof window !== "undefined") {
    try {
      const refreshed = await fetch("/", { credentials: "same-origin", cache: "no-store" });
      if (refreshed.ok) return standaloneApi(path, apiKey, options, false);
    } catch (error) {
      if (error?.name === "AbortError") return { _aborted: true };
    }
  }
  let body;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) body.error = body.error || `请求失败(${response.status})`;
  return { ...body, _status: response.status };
}

async function standaloneFileResponse(path) {
  // Standalone file content is returned as raw bytes, so this mirrors
  // standaloneApi without JSON parsing. The browser session cookie can
  // expire while a long modeling run stays open; refresh it once like the
  // JSON API path instead of failing the download with a silent 401.
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin" });
  } catch (error) {
    if (error?.name === "AbortError") return { error: "请求已取消" };
    return { error: `网络连接失败: ${error?.message || "无法连接服务"}` };
  }
  if (response.status === 401 && typeof window !== "undefined") {
    try {
      const refreshed = await fetch("/", { credentials: "same-origin", cache: "no-store" });
      if (refreshed.ok) {
        try {
          response = await fetch(path, { credentials: "same-origin" });
        } catch (error) {
          if (error?.name === "AbortError") return { error: "请求已取消" };
          return { error: `网络连接失败: ${error?.message || "无法连接服务"}` };
        }
      }
    } catch (error) {
      if (error?.name === "AbortError") return { error: "请求已取消" };
    }
  }
  return { response };
}

function standaloneRequestFailed(result) {
  // Run detail payloads also have an `error` field for BLOCKED/FAILED reasons.
  // A runId is authoritative evidence that this is a successful detail
  // response, even if a proxy strips the synthetic HTTP status marker.
  if (result?.runId) return false;
  return Boolean(result?.error && (!Number.isFinite(Number(result?._status)) || Number(result._status) >= 400));
}

function scheduleIdle(callback) {
  if (typeof window !== "undefined" && typeof window.requestIdleCallback === "function") {
    return window.requestIdleCallback(callback, { timeout: 1200 });
  }
  return window.setTimeout(callback, 0);
}

function cancelScheduledIdle(handle) {
  if (handle == null || typeof window === "undefined") return;
  if (typeof window.cancelIdleCallback === "function") window.cancelIdleCallback(handle);
  else window.clearTimeout(handle);
}

function waitForNextPaint() {
  return new Promise((resolve) => {
    if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => resolve());
    } else {
      globalThis.setTimeout(resolve, 0);
    }
  });
}

function StandaloneApp() {
  const [standaloneTitle, setStandaloneTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [sourceMode, setSourceMode] = useState("DATABASE");
  const [selectedArtifacts, setSelectedArtifacts] = useState(STANDALONE_ARTIFACTS);
  const [inputFiles, setInputFiles] = useState([]);
  const [databaseSources, setDatabaseSources] = useState([]);
  const [databaseSourceId, setDatabaseSourceId] = useState("");
  const [databaseSchema, setDatabaseSchema] = useState("");
  const [databaseSchemas, setDatabaseSchemas] = useState([]);
  const [selectedSchemas, setSelectedSchemas] = useState([]);
  const [databaseTables, setDatabaseTables] = useState([]);
  const [selectedTables, setSelectedTables] = useState([]);
  const [tablesLoading, setTablesLoading] = useState(false);
  const [runs, setRuns] = useState([]);
  const [run, setRun] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewFullscreen, setPreviewFullscreen] = useState(false);
  const [runFilesOpen, setRunFilesOpen] = useState(true);
  const [runFilesLoading, setRunFilesLoading] = useState(false);
  const [selectedRunFiles, setSelectedRunFiles] = useState([]);
  const [standaloneComposerText, setStandaloneComposerText] = useState("");
  const [standalonePendingFiles, setStandalonePendingFiles] = useState([]);
  const [standaloneModels, setStandaloneModels] = useState([]);
  const [standaloneModel, setStandaloneModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [standaloneOntologyDrawing, setStandaloneOntologyDrawing] = useState(false);
  const [error, setError] = useState("");
  const [messageApi, contextHolder] = message.useMessage();
  const selectedRunIdRef = useRef("");
  const runRequestRef = useRef({ generation: 0, controller: null });
  const eventCursorRef = useRef(new Map());
  const eventWindowRef = useRef(new Map());
  // Keep the last loaded thought-chain window outside the selected-run state.
  // The history list intentionally omits events, so switching away and back
  // must not briefly replace a persisted chain with an empty array.
  const standaloneEventCacheRef = useRef(new Map());
  const olderEventsLoadingRef = useRef(new Set());
  // Per-run poll lock: a poll for run A must never block or release a poll
  // for run B after the user switches sessions.
  const pollInFlightRef = useRef(new Map());
  const continueInFlightRef = useRef(false);
  const standaloneFileInputRef = useRef(null);
  const standaloneFeedPrependAnchorRef = useRef(null);
  const standaloneOntologyFiles = useMemo(() => selectOntologyArtifacts(run?.files, "output/"), [run?.files, run?.runId]);
  useEffect(() => { setStandaloneOntologyDrawing(false); setPreviewFullscreen(false); }, [run?.runId]);

  const loadRuns = async () => {
    const result = await standaloneApi("/api/modeling-runs", "");
    if (!result.error) setRuns(result.runs || []);
    else if (result._status !== 401) setError(result.error);
  };
  const loadDatabaseSources = async () => {
    const result = await standaloneApi("/api/modeling-data-sources", "");
    if (!result.error) {
      const sources = result.sources || [];
      setDatabaseSources(sources);
      setDatabaseSourceId((current) => current || sources[0]?.id || "");
    } else if (result._status !== 401) setError(result.error);
  };
  const loadStandaloneModels = async () => {
    const result = await standaloneApi("/api/modeling-models", "");
    if (!result.error) {
      setStandaloneModels(result.models || []);
      setStandaloneModel((current) => current || result.model || result.models?.[0]?.id || "");
    } else if (result._status !== 401) setError(result.error);
  };
  const loadDatabaseSchemas = async (sourceId) => {
    if (!sourceId) return;
    const result = await standaloneApi(`/api/modeling-data-sources/${encodeURIComponent(sourceId)}/schemas`, "");
    if (!result.error) {
      const schemas = (result.schemas || []).filter(Boolean);
      const defaultSchema = result.defaultSchema && schemas.includes(result.defaultSchema)
        ? [result.defaultSchema] : [];
      setDatabaseSchemas(schemas);
      setSelectedSchemas(defaultSchema);
    } else if (result._status !== 401) setError(result.error);
  };
  const loadDatabaseTables = async (sourceId, schemas = selectedSchemas) => {
    if (!sourceId) return;
    setTablesLoading(true);
    const query = (schemas || []).map((schema) => `schemas=${encodeURIComponent(schema)}`).join("&");
    const result = await standaloneApi(`/api/modeling-data-sources/${encodeURIComponent(sourceId)}/tables${query ? `?${query}` : ""}`, "");
    if (!result.error) {
      const tables = (result.tables || []).map((item) => `${item.schema}.${item.name}`).filter(Boolean);
      setDatabaseSchema((result.schemas || []).join(", ") || result.schema || "");
      setDatabaseTables(tables);
      setSelectedTables((current) => current.filter((item) => tables.includes(item)));
    } else if (result._status !== 401) setError(result.error);
    setTablesLoading(false);
  };
  const beginRunRequest = () => {
    runRequestRef.current.controller?.abort();
    const request = {
      generation: runRequestRef.current.generation + 1,
      controller: new AbortController(),
    };
    runRequestRef.current = request;
    return request;
  };
  const isCurrentRunRequest = (runId, generation) => (
    selectedRunIdRef.current === runId && runRequestRef.current.generation === generation
  );
  const updateRunSummary = (summary) => {
    setRuns((current) => current.map((item) => item.runId === summary.runId
      ? { ...item, ...summary, events: undefined }
      : item));
  };
  useLayoutEffect(() => {
    const anchor = standaloneFeedPrependAnchorRef.current;
    if (!anchor || !run) return;
    standaloneFeedPrependAnchorRef.current = null;
    const feed = document.querySelector(".standalone-agent-feed");
    if (feed) feed.scrollTop = Math.max(0, anchor.top + feed.scrollHeight - anchor.height);
  }, [run?.events, run?.runId]);
  const loadRunFiles = async (runId) => {
    if (!runId || selectedRunIdRef.current !== runId) return;
    setRunFilesLoading(true);
    try {
      const result = await standaloneApi(`/api/modeling-runs/${encodeURIComponent(runId)}/files`, "");
      if (result._aborted || selectedRunIdRef.current !== runId || result.error) return;
      setRun((current) => current?.runId === runId ? { ...current, files: result.files || [] } : current);
    } finally {
      if (selectedRunIdRef.current === runId) setRunFilesLoading(false);
    }
  };
  const loadRun = async (runId, showError = true) => {
    if (!runId) return null;
    selectedRunIdRef.current = runId;
    const request = beginRunRequest();
    const encodedId = encodeURIComponent(runId);
    const summary = await standaloneApi(
      `/api/modeling-runs/${encodedId}?includeEvents=false`, "",
      { signal: request.controller.signal },
    );
    if (summary._aborted || selectedRunIdRef.current !== runId) return null;
    // A successful run-detail response legitimately contains `error` for
    // BLOCKED/FAILED runs (for example MODEL_GATE_RETRY_LIMIT). Only treat it
    // as a transport/API failure when the HTTP request itself failed.
    if (standaloneRequestFailed(summary)) { if (showError) setError(summary.error); return null; }
    const cachedRun = runs.find((item) => item.runId === runId);
    const visibleRun = run?.runId === runId ? run : cachedRun;
    const cachedEvents = Array.isArray(visibleRun?.events) && visibleRun.events.length
      ? visibleRun.events
      : (standaloneEventCacheRef.current.get(runId)
        || (Array.isArray(summary.events) ? summary.events : []));
    // Switch the visible session as soon as its lightweight summary arrives.
    // Loading a large historical event journal must never block selecting a
    // different run, and selecting a run is view-only: it does not stop or
    // mutate any server-side execution.
    // The run-detail payload already carries the file tree. Keep it so the
    // file panel is usable immediately instead of waiting for the event
    // journal replay, which can take many seconds on long runs.
    const summaryRun = {
      ...summary,
      files: Array.isArray(summary.files) ? summary.files : (visibleRun?.files || []),
      events: cachedEvents,
    };
    setRun(summaryRun);
    updateRunSummary(summary);
    const events = await standaloneApi(
      `/api/modeling-runs/${encodedId}/events?tail=1&limit=80`, "",
    );
    if (events._aborted || selectedRunIdRef.current !== runId) return null;
    let eventPayload = events;
    let latestEvents = Array.isArray(events.events) ? events.events : [];
    if (events.error && !cachedEvents.length) {
      // Keep compatibility with older standalone servers that do not expose
      // the paged journal route yet; the detail payload is still authoritative
      // and lets a blocked historical session render its chain.
      const detail = await standaloneApi(
        `/api/modeling-runs/${encodedId}?includeEvents=true`, "",
        { signal: request.controller.signal },
      );
      if (detail._aborted || selectedRunIdRef.current !== runId) return null;
      if (!detail.error && Array.isArray(detail.events)) {
        eventPayload = detail;
        latestEvents = detail.events;
      }
    }
    if (events.error && !latestEvents.length) {
      if (showError && !cachedEvents.length) setError(events.error);
      return cachedEvents.length ? summaryRun : null;
    }
    // A run can be restored from an older inline index while its journal is
    // still being migrated. If the summary says history exists but the tail
    // endpoint returned no rows, use the canonical detail payload once rather
    // than leaving a historical session permanently blank.
    if (!latestEvents.length && !events.error && Number(summary.eventsCount) > 0 && !cachedEvents.length) {
      const detail = await standaloneApi(
        `/api/modeling-runs/${encodedId}?includeEvents=true`, "",
        { signal: request.controller.signal },
      );
      if (detail._aborted || selectedRunIdRef.current !== runId) return null;
      if (!detail.error && Array.isArray(detail.events)) {
        eventPayload = detail;
        latestEvents = detail.events;
      }
    }
    const total = Number(eventPayload.eventTotal ?? summary.eventsCount) || latestEvents.length;
    const start = Number(eventPayload.eventStart ?? Math.max(0, total - latestEvents.length));
    // Cursor = next unread absolute seq, taken from the server's journal
    // position instead of a locally counted length.
    eventCursorRef.current.set(runId, nextCursor(eventPayload, latestEvents));
    eventWindowRef.current.set(runId, { start, total });
    // Merge rather than replace: the persisted cache may already hold a fuller
    // window than the tail request, and re-selecting a run must never shrink
    // or duplicate the visible chain.
    const mergedEvents = mergeEvents(cachedEvents, latestEvents, `run:${runId}`);
    const result = {
      ...summary,
      files: Array.isArray(summary.files) ? summary.files : [],
      events: mergedEvents,
    };
    standaloneEventCacheRef.current.set(runId, mergedEvents);
    if (selectedRunIdRef.current === runId) setRun(result);
    scheduleIdle(async () => {
      // The file tree is a single cheap request; populate the panel first so
      // the user can browse and download artifacts while the remaining old
      // journal replays in the background.
      await loadRunFiles(runId);
      const historyHasMore = await loadOlderStandaloneEvents(runId, 10);
      if (historyHasMore) await loadOlderStandaloneEvents(runId);
    });
    return result;
  };
  const loadOlderStandaloneEvents = async (runId, maxViewportPages = Infinity) => {
    if (!runId || selectedRunIdRef.current !== runId || olderEventsLoadingRef.current.has(runId)) return;
    const initialWindow = eventWindowRef.current.get(runId);
    if (!initialWindow || initialWindow.start <= 0) return;
    olderEventsLoadingRef.current.add(runId);
    let loadedHeight = 0;
    try {
      while (selectedRunIdRef.current === runId) {
        const window = eventWindowRef.current.get(runId);
        if (!window || window.start <= 0) break;
        const encodedId = encodeURIComponent(runId);
        const result = await standaloneApi(
          `/api/modeling-runs/${encodedId}/events?before=${window.start}&limit=160`, "",
        );
        if (result._aborted || selectedRunIdRef.current !== runId || result.error) break;
        const older = Array.isArray(result.events) ? result.events : [];
        const nextStart = Number(result.eventStart ?? Math.max(0, window.start - older.length));
        eventWindowRef.current.set(runId, { start: nextStart, total: window.total });
        if (older.length) {
          const feed = document.querySelector(".standalone-agent-feed");
          const beforeHeight = feed?.scrollHeight || 0;
          if (feed) {
            standaloneFeedPrependAnchorRef.current = {
              top: feed.scrollTop,
              height: feed.scrollHeight,
            };
          }
          setRun((current) => current?.runId === runId
            ? { ...current, events: mergeEvents(older, current.events || [], `run:${runId}`) }
            : current);
          const cached = standaloneEventCacheRef.current.get(runId) || [];
          standaloneEventCacheRef.current.set(runId, mergeEvents(older, cached, `run:${runId}`));
          await waitForNextPaint();
          const renderedFeed = document.querySelector(".standalone-agent-feed");
          if (renderedFeed && beforeHeight) {
            loadedHeight += Math.max(0, renderedFeed.scrollHeight - beforeHeight);
            if (renderedFeed.clientHeight > 0
                && loadedHeight >= renderedFeed.clientHeight * maxViewportPages) {
              return true;
            }
          }
        }
        if (!older.length || nextStart >= window.start) break;
        await new Promise((resolve) => globalThis.setTimeout(resolve, 0));
      }
    } finally {
      olderEventsLoadingRef.current.delete(runId);
    }
    return Boolean(eventWindowRef.current.get(runId)?.start > 0);
  };
  const selectRun = (runId) => {
    setError("");
    setStandaloneComposerText("");
    setStandalonePendingFiles([]);
    const cached = runs.find((item) => item.runId === runId);
    if (cached) {
      // The list already has enough metadata to enter view mode. Switch
      // immediately instead of leaving the user on the new-task form while
      // a historical event payload is fetched.
      selectedRunIdRef.current = runId;
      setRun({ ...cached, events: Array.isArray(cached.events) ? cached.events : [] });
    }
    void loadRun(runId);
  };
  const refreshRun = async (runId) => {
    if (!runId || selectedRunIdRef.current !== runId || pollInFlightRef.current.has(runId)) return null;
    // Do not let the first status poll abort the detail request before its
    // historical event window has been fetched. This race was most visible
    // for BLOCKED runs, which otherwise showed only the header and never sent
    // the `/events` request until Continue was clicked.
    if (!eventWindowRef.current.has(runId)) return null;
    pollInFlightRef.current.set(runId, true);
    const request = beginRunRequest();
    const encodedId = encodeURIComponent(runId);
    try {
      const summary = await standaloneApi(
        `/api/modeling-runs/${encodedId}?includeEvents=false`, "",
        { signal: request.controller.signal },
      );
      if (summary._aborted || !isCurrentRunRequest(runId, request.generation)
          || standaloneRequestFailed(summary)) return null;
      const cursor = eventCursorRef.current.get(runId) || 0;
      const events = await standaloneApi(
        `/api/modeling-runs/${encodedId}/events?since=${cursor}`, "",
        { signal: request.controller.signal },
      );
      if (events._aborted || !isCurrentRunRequest(runId, request.generation) || events.error) return null;
      const delta = Array.isArray(events.events) ? events.events : [];
      const visibleEvents = Array.isArray(run?.events) ? run.events : [];
      const reportedEventCount = Number(summary.eventsCount) || 0;
      const historyGap = reportedEventCount > visibleEvents.length + delta.length;
      if (historyGap && !eventWindowRef.current.has(runId)) {
        // The first status poll can race the initial detail load. Retry the
        // historical window instead of committing an incomplete chain and
        // waiting for the user to press Continue before it is fetched again.
        void loadRun(runId, false);
        return summary;
      }
      // Advance the cursor to the server-absolute next-read position. The
      // client never computes `cursor + delta.length` alone because filtered
      // or truncated windows could skip or repeat events.
      eventCursorRef.current.set(runId, nextCursor(events, delta));
      const window = eventWindowRef.current.get(runId);
      const reportedTotal = Number(events.eventTotal);
      if (window) {
        eventWindowRef.current.set(runId, {
          ...window,
          total: Number.isFinite(reportedTotal) ? reportedTotal : window.total + delta.length,
        });
      }
      setRun((current) => {
        if (current?.runId !== runId) return current;
        const currentEvents = Array.isArray(current.events) ? current.events : [];
        // A status refresh must never erase a journal that is still loading.
        // If the server reports history but this poll has no delta, retain the
        // visible chain and let the detail loader finish it. Any real delta is
        // merged idempotently by event identity (runId + seq).
        const nextEvents = delta.length || !summary.eventsCount
          ? mergeEvents(currentEvents, delta, `run:${runId}`)
          : currentEvents;
        standaloneEventCacheRef.current.set(runId, nextEvents);
        return { ...summary, files: current.files || [], events: nextEvents };
      });
      updateRunSummary(summary);
      return summary;
    } finally {
      pollInFlightRef.current.delete(runId);
    }
  };
  const startNewTask = () => {
    selectedRunIdRef.current = "";
    runRequestRef.current.controller?.abort();
    setRun(null);
    setPreview(null);
    setError("");
    setStandaloneTitle("");
    setPrompt("");
    setInputFiles([]);
    setSelectedSchemas([]);
    setSelectedTables([]);
    setSelectedArtifacts(STANDALONE_ARTIFACTS);
    setSelectedRunFiles([]);
    setStandaloneComposerText("");
    setStandalonePendingFiles([]);
    setRunFilesLoading(false);
    setRunFilesOpen(true);
  };
  useEffect(() => {
    void loadRuns();
    void loadDatabaseSources();
    // Model selection is secondary to the task/input shell. Load it after the
    // first browser idle period so it cannot delay the initial form.
    const handle = scheduleIdle(() => { void loadStandaloneModels(); });
    return () => cancelScheduledIdle(handle);
  }, []);
  useEffect(() => {
    // Keep queued/background runs' status visible in the history list while
    // detailed events continue to poll only for the selected run.
    const timer = window.setInterval(() => { void loadRuns(); }, 3000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => { void loadDatabaseSchemas(databaseSourceId); }, [databaseSourceId]);
  useEffect(() => { void loadDatabaseTables(databaseSourceId, selectedSchemas); }, [databaseSourceId, selectedSchemas]);
  useEffect(() => {
    if (!run?.runId) return undefined;
    const activeStatuses = new Set(["QUEUED", "ANALYZING", "VALIDATING"]);
    if (!activeStatuses.has(run.status)) return undefined;
    const timer = window.setInterval(() => { void refreshRun(run.runId); }, 1800);
    return () => window.clearInterval(timer);
  }, [run?.runId, run?.status]);

  const readFiles = async (files) => Promise.all(files.map((file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ name: file.name, contentBase64: String(reader.result).split(",")[1] || "" });
    reader.onerror = reject;
    reader.readAsDataURL(file);
  })));
  const startModeling = async () => {
    setError("");
    if (!selectedArtifacts.length) { setError("至少选择一个正式产物"); return; }
    if (sourceMode === "DATABASE" && !databaseSourceId) { setError("请选择数据库"); return; }
    if (sourceMode === "DATABASE" && !selectedSchemas.length) { setError("至少选择一个 Schema"); return; }
    if (sourceMode === "DATABASE" && !selectedTables.length) { setError("至少选择一张数据表"); return; }
    setBusy(true);
    try {
      const payload = {
        sourceMode,
        title: standaloneTitle.trim(),
        prompt: prompt.trim(),
        requestedArtifacts: selectedArtifacts,
        files: await readFiles(inputFiles),
      };
      if (sourceMode === "DATABASE") {
        payload.databaseSourceId = databaseSourceId;
        payload.selectedSchemas = selectedSchemas;
        payload.selectedTables = selectedTables;
      }
      const created = await standaloneApi("/api/modeling-runs", "", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      if (standaloneRequestFailed(created)) { setError(created.error); return; }
      selectedRunIdRef.current = created.runId;
      // The create response is metadata only; do not treat eventsCount as a
      // client read cursor because it does not contain the event payload.
      eventCursorRef.current.delete(created.runId);
      setRun(created);
      setRuns((current) => [created, ...current.filter((item) => item.runId !== created.runId)]);
      const started = await standaloneApi(`/api/modeling-runs/${created.runId}/execute`, "", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...(standaloneModel ? { model: standaloneModel } : {}), intent: "execute" }),
      });
      if (standaloneRequestFailed(started)) {
        setError(started.error);
        return;
      }
      // /execute may finish or become BLOCKED before this response arrives.
      // Reload the persisted event window so already-produced thinking is not
      // skipped by initializing the cursor from a summary-only response. The
      // 202 payload is summary-only (no event array), so events always come
      // from the journal route.
      eventCursorRef.current.delete(started.runId);
      setRun(started);
      setRuns((current) => current.map((item) => item.runId === started.runId ? { ...item, ...started } : item));
      void loadRun(started.runId);
      messageApi.success("建模已开始，可在右侧查看运行状态和产物");
    } catch (requestError) {
      setError(requestError?.message || "请求失败");
    } finally {
      setBusy(false);
    }
  };
  const continueRun = async (nextPrompt = "", selectedModel = standaloneModel) => {
    if (!run?.runId || !["CREATED", "INPUT_READY", "FAILED", "BLOCKED", "CANCELLED"].includes(run.status)) return;
    if (continueInFlightRef.current) return;
    setError("");
    setBusy(true);
    continueInFlightRef.current = true;
    try {
      const started = await standaloneApi(`/api/modeling-runs/${encodeURIComponent(run.runId)}/execute`, "", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(nextPrompt.trim() ? { prompt: nextPrompt.trim() } : {}),
          ...(selectedModel ? { model: selectedModel } : {}),
          intent: "auto",
        }),
      });
      // HTTP 202 is an accepted-status response: `started.error` is the
      // run's domain state (e.g. a previous FAILED/BLOCKED reason), not an
      // API/transport failure. Only a real 4xx/5xx response rejects here.
      if (standaloneRequestFailed(started)) {
        setError(started.error);
        return;
      }
      selectedRunIdRef.current = started.runId;
      // Keep the persisted event cursor: a continue appends to the same run,
      // so only pull the delta instead of reloading the whole journal window.
      // The full window is re-established only when this browser never loaded
      // it (e.g. the run was continued from another client).  Preserve the
      // already-rendered file tree and event chain until refresh replaces it.
      setRun((current) => {
        if (current?.runId !== started.runId) {
          return { ...started, files: Array.isArray(run.files) ? run.files : [] };
        }
        return {
          ...started,
          files: Array.isArray(current.files) ? current.files : [],
          events: current.events,
        };
      });
      setRuns((current) => current.map((item) => item.runId === started.runId
        ? { ...item, ...started } : item));
      if (eventWindowRef.current.has(started.runId)) {
        void refreshRun(started.runId);
      } else {
        eventCursorRef.current.delete(started.runId);
        void loadRun(started.runId);
      }
      messageApi.success("已继续运行建模任务");
    } catch (requestError) {
      setError(requestError?.message || "请求失败");
    } finally {
      setBusy(false);
      continueInFlightRef.current = false;
    }
  };
  const onStandaloneAttach = () => standaloneFileInputRef.current?.click();
  const onStandaloneFilesSelected = (event) => {
    setStandalonePendingFiles(Array.from(event.target.files || []));
    event.target.value = "";
  };
  const sendStandaloneMessage = async () => {
    if (!run || busy || ["QUEUED", "ANALYZING", "VALIDATING"].includes(run.status)) return;
    const nextPrompt = standaloneComposerText.trim();
    if (run.status === "SUCCEEDED") {
      setError("该会话已经完成，如需重新建模请点击“新任务”");
      return;
    }
    if (!nextPrompt && !standalonePendingFiles.length) return;
    setError("");
    if (standalonePendingFiles.length) {
      setBusy(true);
      try {
        const result = await standaloneApi(`/api/modeling-runs/${encodeURIComponent(run.runId)}/inputs`, "", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ files: await readFiles(standalonePendingFiles) }),
        });
        if (standaloneRequestFailed(result)) { setError(result.error); return; }
        setStandalonePendingFiles([]);
      } catch (requestError) {
        setError(requestError?.message || "上传文件失败");
        return;
      } finally {
        setBusy(false);
      }
    }
    setStandaloneComposerText("");
    await continueRun(nextPrompt, standaloneModel);
  };
  const openFile = async (path) => {
    // Keep standalone file access on its own API, but reuse the shared
    // workbook reader instead of decoding XLSX bytes as text.
    const fetched = await standaloneFileResponse(`/api/modeling-runs/${encodeURIComponent(run.runId)}/files/content?path=${encodeURIComponent(path)}`);
    const response = fetched.response;
    if (fetched.error || !response) { setError(fetched.error || "无法读取文件"); return; }
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try { const body = await response.json(); detail = body.error || detail; } catch (_) { /* keep HTTP status */ }
      setError(detail);
      return;
    }
    if (/\.(xlsx?|xlsm)$/i.test(path)) {
      const [buffer, XLSX] = await Promise.all([response.arrayBuffer(), import("xlsx")]);
      const workbook = XLSX.read(buffer, { type: "array", cellDates: true });
      const sheets = workbook.SheetNames.map((name) => ({
        name,
        rows: XLSX.utils.sheet_to_json(workbook.Sheets[name], { header: 1, defval: "", raw: false }),
      }));
      setPreview({ path, xlsx: true, sheets });
      return;
    }
    const text = await response.text();
    setPreview({ path, text, csv: /\.csv$/i.test(path) });
  };
  const downloadRunFiles = async (paths) => {
    const selected = Array.isArray(paths) && paths.length ? paths : selectedRunFiles;
    if (!selected.length || !run) return;
    const failed = [];
    for (const path of selected) {
      try {
        const fetched = await standaloneFileResponse(`/api/modeling-runs/${encodeURIComponent(run.runId)}/files/content?path=${encodeURIComponent(path)}`);
        const response = fetched.response;
        if (fetched.error || !response || !response.ok) { failed.push(path); continue; }
        const blob = await response.blob();
        const name = path.split("/").pop() || "download";
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = name;
        link.rel = "noopener";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (requestError) {
        failed.push(path);
      }
    }
    const okCount = selected.length - failed.length;
    if (okCount > 0) messageApi.success(`已开始下载 ${okCount} 个文件`);
    if (failed.length) messageApi.error(`下载失败 ${failed.length} 个文件：${failed.map((path) => path.split("/").pop()).join("、")}`);
  };
  const drawStandaloneOntology = async () => {
    const runId = run?.runId || "";
    if (!standaloneOntologyFiles || !runId) {
      setError("缺少逻辑实体 CSV，不能进行本体可视化");
      return;
    }
    setStandaloneOntologyDrawing(true);
    setError("");
    try {
      const artifacts = [...standaloneOntologyFiles.entries()];
      const responses = await Promise.all(artifacts.map(([, artifact]) => standaloneFileResponse(`/api/modeling-runs/${encodeURIComponent(runId)}/files/content?path=${encodeURIComponent(artifact.path)}`)));
      const failedIndex = responses.findIndex((result) => result.error || !result.response?.ok);
      if (failedIndex >= 0) throw new Error(`${artifacts[failedIndex][1].name} 读取失败`);
      const texts = await Promise.all(responses.map((result) => result.response.text()));
      if (selectedRunIdRef.current !== runId) return;
      const records = new Map(artifacts.map(([layer], index) => [layer, csvRecords(texts[index])]));
      const graph = buildOntologyGraph(records);
      if (!graph.availability.logicalEntity) throw new Error("逻辑实体产物中没有可展示的数据");
      setPreview({ path: "本体可视化", ontologyGraph: graph });
    } catch (drawError) {
      if (selectedRunIdRef.current === runId) setError(`本体可视化失败：${drawError.message}`);
    } finally {
      if (selectedRunIdRef.current === runId) setStandaloneOntologyDrawing(false);
    }
  };
  const statusColor = { CREATED: "default", INPUT_READY: "blue", QUEUED: "processing", ANALYZING: "processing", VALIDATING: "processing", SUCCEEDED: "success", FAILED: "default", BLOCKED: "default", CANCELLED: "warning" }[run?.status] || "default";
  return <ConfigProvider theme={{ token: { colorPrimary: "#2563eb", borderRadius: 8, fontFamily: '"PingFang SC", -apple-system, sans-serif' } }}>
    {contextHolder}
    <div className="standalone-shell">
      <header className="standalone-header"><div className="brand"><span className="brand-logo">硕</span><strong>硕磐智能建模</strong><Tag color="blue">v0.0.1</Tag></div><Tag color="green">服务已连接</Tag></header>
      <div className={`standalone-layout ${run ? "standalone-layout-running" : ""}`}>
        <aside className="standalone-history"><Button type="primary" block className="standalone-new-task" onClick={startNewTask}>＋ 新任务</Button><div className="standalone-section-title">历史运行</div>{runs.length ? <List size="small" dataSource={runs} renderItem={(item) => <List.Item role="button" tabIndex={0} className={run?.runId === item.runId ? "standalone-run-active" : "standalone-run"} onClick={() => selectRun(item.runId)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectRun(item.runId); } }}><div><strong>{standaloneRunTitle(item)}</strong><small>{formatRunCreatedAt(item.createdAt)} · {statusLabel(item.status)}</small></div></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无运行记录" />}</aside>
        <main className="standalone-main">
          {!run && <div className="standalone-title"><div><h1>独立智能建模</h1><p>上传输入资料或连接已有数据库，完成建模并查看可追溯产物。</p></div></div>}
          {error && <Alert type="error" showIcon closable onClose={() => setError("")} message={error} />}
          {!run ? <StandaloneInputCard sourceMode={sourceMode} setSourceMode={setSourceMode} title={standaloneTitle} setTitle={setStandaloneTitle} prompt={prompt} setPrompt={setPrompt} inputFiles={inputFiles} setInputFiles={setInputFiles} databaseSourceId={databaseSourceId} setDatabaseSourceId={setDatabaseSourceId} databaseSources={databaseSources} databaseSchemas={databaseSchemas} selectedSchemas={selectedSchemas} setSelectedSchemas={setSelectedSchemas} databaseSchema={databaseSchema} tablesLoading={tablesLoading} databaseTables={databaseTables} selectedTables={selectedTables} setSelectedTables={setSelectedTables} selectedArtifacts={selectedArtifacts} setSelectedArtifacts={setSelectedArtifacts} busy={busy} startModeling={startModeling} /> : <StandaloneAgentWorkspace run={run} busy={busy || ["QUEUED", "ANALYZING", "VALIDATING"].includes(run.status)} filesOpen={runFilesOpen} filesLoading={runFilesLoading} selectedFiles={selectedRunFiles} onToggleFiles={() => setRunFilesOpen((value) => !value)} onSelectFile={(path) => setSelectedRunFiles((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path])} onSelectGroup={(paths) => setSelectedRunFiles((current) => paths.every((path) => current.includes(path)) ? current.filter((item) => !paths.includes(item)) : [...new Set([...current, ...paths])])} onOpenFile={openFile} onDownload={downloadRunFiles} onDrawOntology={drawStandaloneOntology} drawingOntology={standaloneOntologyDrawing} ontologyAvailable={Boolean(standaloneOntologyFiles)} onRefresh={() => void loadRun(run.runId)} onContinue={continueRun} composerValue={standaloneComposerText} onComposerChange={setStandaloneComposerText} onComposerSend={sendStandaloneMessage} onComposerAttach={onStandaloneAttach} pendingComposerFiles={standalonePendingFiles} model={standaloneModel || "默认模型"} models={standaloneModels} onModel={setStandaloneModel} onOpenSettings={() => {}} />}
        </main>
      </div>
      <input ref={standaloneFileInputRef} type="file" multiple hidden onChange={onStandaloneFilesSelected} />
      {preview && <Modal open centered={!previewFullscreen} wrapClassName={previewFullscreen ? "preview-modal-wrap-fullscreen" : ""} className={previewFullscreen ? "preview-modal preview-modal-fullscreen" : "preview-modal"} title={<PreviewModalTitle title={preview.path} fullscreen={previewFullscreen} onToggle={() => setPreviewFullscreen((value) => !value)} />} footer={null} width={previewFullscreen ? "100vw" : "82vw"} onCancel={() => { setPreview(null); setPreviewFullscreen(false); }}>{preview.ontologyGraph ? <OntologyTreePreview data={preview.ontologyGraph} /> : preview.xlsx ? <SpreadsheetPreview sheets={preview.sheets} /> : preview.csv ? <CsvPreview text={preview.text} /> : <pre className="preview-text">{preview.text}</pre>}</Modal>}
    </div>
  </ConfigProvider>;
}

function StandaloneInputCard({ sourceMode, setSourceMode, title, setTitle, prompt, setPrompt, inputFiles, setInputFiles,
  databaseSourceId, setDatabaseSourceId, databaseSources, databaseSchemas, selectedSchemas,
  setSelectedSchemas, databaseSchema, tablesLoading, databaseTables, selectedTables, setSelectedTables,
  selectedArtifacts, setSelectedArtifacts, busy, startModeling }) {
  return <div className="standalone-card"><h2>建模输入</h2><div className="standalone-form-row"><Input size="large" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="任务名称（可选），不填时用建模要求作为会话名" /><Input size="large" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="建模要求可选；不填写时直接使用四份 v0.0.1 规范/模板建模" /></div><div className="standalone-form-row"><Select size="large" value={sourceMode} onChange={setSourceMode} options={[{ value: "DATABASE", label: "数据库建模" }, { value: "DOCUMENT", label: "文档建模" }, { value: "NATURAL_LANGUAGE", label: "自然语言建模" }]} /></div><div className="standalone-upload"><input type="file" multiple onChange={(event) => setInputFiles(Array.from(event.target.files || []))} /><span>{inputFiles.length ? inputFiles.map((file) => file.name).join("、") : "可上传 schema、文档或其他输入文件"}</span></div>{sourceMode === "DATABASE" && <><Divider orientation="left">选择数据源</Divider><div className="standalone-database-row"><Select className="standalone-database-select" value={databaseSourceId || undefined} onChange={(value) => { setDatabaseSourceId(value); setSelectedSchemas([]); setSelectedTables([]); }} placeholder="请选择数据库" loading={!databaseSources.length} options={databaseSources.map((item) => ({ value: item.id, label: item.name }))} notFoundContent="暂无可用数据库" /><Select mode="multiple" allowClear className="standalone-database-select" value={selectedSchemas} onChange={(value) => { setSelectedSchemas(value); setSelectedTables([]); }} placeholder="选择 Schema（可多选）" loading={!databaseSchemas.length && !!databaseSourceId} options={databaseSchemas.map((schema) => ({ value: schema, label: schema }))} notFoundContent="暂无可用 Schema" /></div><Divider orientation="left">选择数据表</Divider><div className="standalone-table-toolbar"><span>Schema：{databaseSchema || "-"}</span><Checkbox checked={databaseTables.length > 0 && selectedTables.length === databaseTables.length} indeterminate={selectedTables.length > 0 && selectedTables.length < databaseTables.length} disabled={tablesLoading || !databaseTables.length} onChange={(event) => setSelectedTables(event.target.checked ? databaseTables : [])}>全选</Checkbox></div>{tablesLoading ? <div className="standalone-table-loading">正在读取数据表…</div> : <Checkbox.Group className="standalone-table-list" value={selectedTables} onChange={setSelectedTables} options={databaseTables.map((item) => ({ value: item, label: item }))} />}<div className="standalone-selected-count">已选 {selectedTables.length} 张表</div></>}<Divider orientation="left">解析要素</Divider><Checkbox.Group value={selectedArtifacts} onChange={setSelectedArtifacts} options={STANDALONE_ARTIFACTS.map((item) => ({ value: item, label: STANDALONE_ARTIFACT_LABELS[item] }))} /><Button type="primary" size="large" loading={busy} disabled={busy} onClick={startModeling} className="standalone-start">开始建模</Button></div>;
}

const BLOCKED_REASON_TEXT = {
  MODEL_GATE_RETRY_LIMIT: "模型反复尝试修复仍未通过门禁校验，已达到自动修复次数上限（10 次），系统为避免无限消耗已自动暂停",
  MODEL_GATE_REPEATED_WITHOUT_NEW_EVIDENCE: "模型重复提交了相同的门禁错误且没有带来新的证据，触发安全阀已自动暂停",
  MODEL_EXECUTION_TIMEOUT: "本次运行达到单轮执行时长上限，已保留当前 checkpoint 自动暂停，可继续运行",
  MODEL_TOOL_CALL_LIMIT: "本次运行达到工具调用次数上限，已保留当前 checkpoint 自动暂停，可继续运行",
  MODEL_TOKEN_BUDGET_EXCEEDED: "本次运行达到 Token 预算上限，已保留当前 checkpoint 自动暂停，可继续运行",
};

function blockedAdviceText(run) {
  const reason = String(run?.error || "").trim() || "MODEL_GATE";
  const reasonText = BLOCKED_REASON_TEXT[reason] || `建模门禁校验未通过（${reason}）`;
  const journal = Array.isArray(run?.events) ? run.events : [];
  let blockers = "";
  for (let index = journal.length - 1; index >= 0; index -= 1) {
    const event = journal[index];
    if (event?.type === "execution_gate" && event.message) {
      const marker = "当前未通过项：";
      const start = String(event.message).indexOf(marker);
      blockers = (start >= 0 ? String(event.message).slice(start + marker.length) : String(event.message)).trim();
      break;
    }
    if (event?.type === "execution_guard" && event.message) {
      const marker = "未通过的门禁校验项：";
      const start = String(event.message).indexOf(marker);
      blockers = (start >= 0 ? String(event.message).slice(start + marker.length) : String(event.message)).trim();
      break;
    }
  }
  if (blockers.length > 500) blockers = `${blockers.slice(0, 500)}…`;
  const blockerLine = blockers
    ? `未通过的门禁校验项：${blockers}`
    : "具体未通过的门禁校验项请查看下方执行审计或文件面板中的校验报告。";
  return [
    "【建模已暂停】",
    "",
    ":::details 暂停详情（点击展开）",
    `暂停原因：${reasonText}。`,
    blockerLine,
    ":::",
    "",
    "当前产物其实已经基本完成：模型已生成 work/output 中的建模结果文件，这些结果现在就可以下载使用。",
    "",
    "你可以这样处理：",
    "1. 点击上方“继续运行”，让模型基于当前产物继续修复并重新校验；",
    "2. 或者直接使用当前产物，在“文件”面板中下载已生成的结果文件。",
  ].join("\n");
}

function StandaloneAgentWorkspace({ run, busy, filesOpen, filesLoading, selectedFiles, onToggleFiles, onSelectFile, onSelectGroup, onOpenFile, onDownload, onDrawOntology, drawingOntology, ontologyAvailable, onRefresh, onContinue, composerValue, onComposerChange, onComposerSend, onComposerAttach, pendingComposerFiles, model, models, onModel, onOpenSettings }) {
  const statusColor = { CREATED: "default", INPUT_READY: "blue", QUEUED: "processing", ANALYZING: "processing", VALIDATING: "processing", SUCCEEDED: "success", FAILED: "default", BLOCKED: "default", CANCELLED: "warning" }[run?.status] || "default";
  const files = run?.files || [];
  // The standalone API persists every streamed thinking token. Reuse the
  // shared workbench normalization so one continuous reasoning block renders
  // as one node instead of dozens of token-sized "思考中" nodes.
  const events = useMemo(() => {
    const scope = `run:${run.runId}`;
    const journal = mergeEvents([], run.events || [], scope);
    const normalized = normalizeEvents({ events: journal });
    const base = [...normalized];
    // The initial prompt is synthesized only when the journal has no formal
    // user event (a fresh run). Continued runs persist their own user events,
    // so the synthetic bubble must not duplicate them.
    const hasUserEvent = normalized.some((event) => event.type === "user");
    if (!hasUserEvent) {
      base.unshift({
        type: "user",
        text: run.prompt || "开始智能建模",
        _key: `prompt:${run.runId}`,
      });
    }
    if (run?.status === "BLOCKED") {
      // Deterministic client-derived notice. Its stable `_key` means refresh,
      // status polls and history backfill can never render a second copy.
      base.push({
        type: "assistant",
        text: blockedAdviceText(run),
        _key: `blocked-advice:${run.runId}`,
      });
    }
    return base;
  }, [run.events, run.prompt, run.status, run.runId]);
  return <section className="task-view standalone-agent-task-view">
    <header className="task-header"><span className={busy ? "status-dot working" : "status-dot"} /><strong title="Agent 建模执行">Agent 建模执行</strong><Tag>{run.runId}</Tag><span className="header-spacer" /><Tag color={statusColor}>{statusLabel(run.status)}</Tag>{["FAILED", "BLOCKED", "CANCELLED"].includes(run.status) && <Button type="primary" loading={busy} onClick={() => onContinue()}>继续运行</Button>}<Button onClick={onRefresh}>刷新</Button><Button icon={<TaskFilesIcon />} onClick={onToggleFiles}>文件</Button></header>
    <div className="standalone-agent-task-body"><div className="standalone-agent-conversation"><div className="feed standalone-agent-feed"><EventFeed events={events} onApprove={() => {}} files={files} onFile={onOpenFile} busy={busy} scope={`run:${run.runId}`} /></div><div className="task-composer standalone-agent-task-composer"><Composer value={composerValue} onChange={onComposerChange} onSend={onComposerSend} onAttach={onComposerAttach} pendingFiles={pendingComposerFiles} mission={null} busy={busy} hasConversation={true} model={model} models={models} onModel={onModel} onOpenSettings={onOpenSettings} placeholder="继续对这个任务下指令…" projects={[]} project="" onProject={() => {}} /></div></div><FilePanel open={filesOpen} files={files} loading={filesLoading} selected={selectedFiles} onSelect={onSelectFile} onSelectGroup={onSelectGroup} onOpen={onOpenFile} onDownload={onDownload} onUploadToMinio={() => {}} uploadingToMinio={false} uploadBlocked={busy} onDrawOntology={onDrawOntology} drawingOntology={drawingOntology} ontologyAvailable={ontologyAvailable} onClose={onToggleFiles} onRefresh={onRefresh} mission={false} workspaceFolders resetKey={run.runId} /></div>
  </section>;
}

function SendArrowIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fill="#fff" d="m1 7 13-5-2 11-6.97-3.802L13 3 3.794 8.523 1 7Zm4 8v-4.734L8 12l-3 3Z" />
    </svg>
  );
}

function CurrentMissionIcon() {
  return (
    <svg className="current-mission-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M10.152.857a.487.487 0 0 1 .2.124l3.324 3.323a.487.487 0 0 1 .156.407v8.623c0 .253-.044.488-.134.704-.09.216-.224.414-.403.593a1.821 1.821 0 0 1-.592.402c-.216.09-.45.135-.704.135h-8c-.253 0-.488-.045-.704-.134a1.823 1.823 0 0 1-.592-.403 1.82 1.82 0 0 1-.403-.593 1.822 1.822 0 0 1-.134-.704V2.668c0-.254.044-.488.134-.704.09-.216.224-.414.403-.593A1.82 1.82 0 0 1 3.295.97c.216-.09.45-.135.704-.135h5.956a.49.49 0 0 1 .197.023Zm2.68 4.31v8.167c0 .278-.069.486-.208.625-.139.14-.347.209-.625.209h-8c-.278 0-.486-.07-.625-.209-.139-.139-.208-.347-.208-.625V2.668c0-.278.07-.487.208-.625.139-.14.347-.209.625-.209h5.5v2.167c0 .161.028.31.085.448.057.137.143.263.257.377.114.114.24.2.377.256.137.057.287.086.448.086h2.166ZM10.5 4.002v-1.46l1.626 1.627h-1.46c-.055 0-.096-.014-.124-.042-.028-.028-.042-.07-.042-.125Zm-.132 3.317H5.634a.491.491 0 0 1-.5-.5.49.49 0 0 1 .277-.45.488.488 0 0 1 .223-.05h4.733a.492.492 0 0 1 .5.5.491.491 0 0 1-.5.5ZM5.634 9.684h4.733a.491.491 0 0 0 .5-.5.49.49 0 0 0-.278-.449.488.488 0 0 0-.222-.05H5.634a.492.492 0 0 0-.5.5.491.491 0 0 0 .5.5Z" />
    </svg>
  );
}

function UploadFileIcon() {
  return (
    <svg className="composer-upload-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="m4.646 4.646 2.955-2.954a.491.491 0 0 1 .396-.192H8a.48.48 0 0 1 .359.152l2.995 2.994.002.003a.495.495 0 0 1-.004.707.49.49 0 0 1-.512.12.49.49 0 0 1-.192-.121l-.002-.001-2.149-2.15v7.465a.49.49 0 0 1-.5.498h-.002a.49.49 0 0 1-.498-.5V3.21L5.354 5.354h-.002a.495.495 0 0 1-.706-.001l-.001-.001a.495.495 0 0 1 .002-.705ZM2.5 8.003v4.664c0 .277.07.486.208.625.14.139.348.208.625.208h9.334c.277 0 .486-.069.625-.208.139-.14.208-.348.208-.625v-4.67A.49.49 0 0 1 14 7.5l.002.001a.495.495 0 0 1 .498.5v4.667c0 .253-.045.488-.134.703a1.82 1.82 0 0 1-.403.593c-.179.18-.377.313-.593.403a1.82 1.82 0 0 1-.703.134H3.333c-.253 0-.487-.045-.703-.134a1.821 1.821 0 0 1-.593-.403 1.82 1.82 0 0 1-.403-.593 1.82 1.82 0 0 1-.134-.703V8.003a.49.49 0 0 1 .5-.5.49.49 0 0 1 .5.5Z" />
    </svg>
  );
}

function DownloadSelectedIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M8.002 11.167a.488.488 0 0 0 .397-.193l2.954-2.954a.495.495 0 0 0 .002-.705l-.002-.002a.495.495 0 0 0-.705-.001l-.002.001-2.143 2.144V2a.491.491 0 0 0-.498-.5h-.002a.49.49 0 0 0-.45.277.487.487 0 0 0-.05.22v7.466l-2.15-2.15v-.001a.49.49 0 0 0-.513-.12.489.489 0 0 0-.192.12l-.002.001a.495.495 0 0 0-.002.705l.002.002 2.994 2.994a.49.49 0 0 0 .36.153h.002ZM2.5 8.003v4.664c0 .278.07.486.208.625.14.138.348.208.625.208h9.334c.277 0 .486-.07.625-.208.139-.14.208-.347.208-.625v-4.67A.491.491 0 0 1 14 7.5l.002.001a.495.495 0 0 1 .498.5v4.667c0 .253-.045.488-.134.703-.09.217-.224.414-.403.593a1.821 1.821 0 0 1-.592.403 1.82 1.82 0 0 1-.704.134H3.333a1.82 1.82 0 0 1-.703-.134 1.822 1.822 0 0 1-.593-.403 1.822 1.822 0 0 1-.403-.593 1.82 1.82 0 0 1-.134-.703V8.003a.491.491 0 0 1 .5-.5.49.49 0 0 1 .45.277c.033.067.05.142.05.223Z" />
    </svg>
  );
}

function CollapseFilePanelIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M13.335 3H2.666a.49.49 0 0 0-.5.5.49.49 0 0 0 .5.5h10.667a.492.492 0 0 0 .5-.498V3.5a.489.489 0 0 0-.277-.45.488.488 0 0 0-.22-.05Zm-2.404 7.09 2.667-1.666a.5.5 0 0 0 0-.848L10.93 5.91a.498.498 0 0 0-.618.07.482.482 0 0 0-.147.354v3.334a.499.499 0 0 0 .388.487c.134.03.26.01.377-.063ZM2.666 6H8a.49.49 0 0 1 .449.277c.034.067.05.142.05.223v.002a.489.489 0 0 1-.277.447A.49.49 0 0 1 8 7H2.666a.49.49 0 0 1-.5-.5.49.49 0 0 1 .5-.5Zm8.5 2v-.765 1.53V8Zm-8.5 1H8a.49.49 0 0 1 .449.277c.034.067.05.142.05.223v.002a.489.489 0 0 1-.277.447A.49.49 0 0 1 8 10H2.666a.49.49 0 0 1-.5-.5.49.49 0 0 1 .5-.5Zm10.67 3H2.665a.49.49 0 0 0-.5.5.489.489 0 0 0 .277.45c.068.033.142.05.223.05h10.667a.49.49 0 0 0 .45-.277.487.487 0 0 0 .05-.22V12.5a.49.49 0 0 0-.277-.45.489.489 0 0 0-.22-.05Z" />
    </svg>
  );
}

function RefreshFilePanelIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M12.078 4.328c.326.365.602.774.828 1.228a.495.495 0 0 0 .668.226h.002a.495.495 0 0 0 .226-.669v-.002a6.49 6.49 0 0 0-.981-1.453 6.499 6.499 0 0 0-1.373-1.155 6.444 6.444 0 0 0-1.611-.738 6.476 6.476 0 0 0-1.86-.265c-.667 0-1.305.095-1.913.284a6.341 6.341 0 0 0-1.537.72 6.484 6.484 0 0 0-1.38 1.184V2.667a.49.49 0 0 0-.5-.5.49.49 0 0 0-.5.5v2.632a.492.492 0 0 0 .19.43c.025.02.053.037.082.051l.005.003h.001c.035.017.07.03.109.038a.467.467 0 0 0 .154.012h2.219a.495.495 0 0 0 .5-.497v-.003a.495.495 0 0 0-.498-.5H3.52a5.406 5.406 0 0 1 1.546-1.486 5.34 5.34 0 0 1 1.28-.602A5.396 5.396 0 0 1 7.977 2.5c.55 0 1.077.076 1.581.227.472.14.923.348 1.355.621.441.28.83.606 1.165.98Zm-8.984 6.116c.226.454.502.863.828 1.228.335.374.724.7 1.165.98.432.273.883.48 1.355.621a5.478 5.478 0 0 0 1.581.227c.57 0 1.113-.082 1.631-.245.446-.14.872-.34 1.28-.602a5.476 5.476 0 0 0 1.546-1.486h-1.387a.49.49 0 0 1-.449-.277.488.488 0 0 1-.05-.223.491.491 0 0 1 .5-.5h2.219a.493.493 0 0 1 .263.05.491.491 0 0 1 .204.185.492.492 0 0 1 .073.305v2.629a.495.495 0 0 1-.5.497h-.002a.495.495 0 0 1-.498-.5v-1.02a6.415 6.415 0 0 1-1.38 1.182 6.33 6.33 0 0 1-1.537.72 6.39 6.39 0 0 1-1.913.285 6.47 6.47 0 0 1-1.86-.265 6.444 6.444 0 0 1-1.61-.738 6.5 6.5 0 0 1-1.374-1.155 6.49 6.49 0 0 1-.98-1.453.49.49 0 0 1 .048-.525.487.487 0 0 1 .177-.145.49.49 0 0 1 .526.048c.06.045.108.104.144.177Z" />
    </svg>
  );
}

function TaskEditIcon() {
  return (
    <svg className="task-action-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="m9.822 8.776 4.225-3.974c.184-.173.325-.367.42-.58.097-.213.149-.446.156-.7a1.82 1.82 0 0 0-.112-.707 1.82 1.82 0 0 0-.385-.605l-.183-.195a1.82 1.82 0 0 0-.58-.42 1.824 1.824 0 0 0-.7-.156 1.82 1.82 0 0 0-.707.112c-.219.083-.42.211-.605.385L7.13 5.906a1.158 1.158 0 0 0-.342.606l-.4 1.876a.824.824 0 0 0 .007.402c.035.125.104.24.205.347.1.106.213.18.336.22.123.042.257.05.402.027l1.873-.307a1.163 1.163 0 0 0 .61-.301Zm4.554 4.286v-5a.491.491 0 0 0-.498-.5h-.002a.491.491 0 0 0-.5.498v5.002c0 .167-.042.292-.125.375-.083.084-.208.125-.375.125h-10c-.167 0-.292-.041-.375-.125-.084-.083-.125-.208-.125-.375v-10c0-.166.041-.291.125-.375.083-.083.208-.125.375-.125h5a.491.491 0 0 0 .5-.498v-.002a.491.491 0 0 0-.5-.5h-5c-.207 0-.4.037-.576.11a1.487 1.487 0 0 0-.485.33 1.487 1.487 0 0 0-.33.484c-.073.177-.11.37-.11.576v10c0 .207.037.4.11.576.074.177.184.339.33.485.146.146.308.256.485.33.177.073.369.11.576.11h10c.207 0 .399-.037.576-.11.176-.074.338-.184.484-.33.147-.146.257-.308.33-.485a1.49 1.49 0 0 0 .11-.576Zm-.823-9.252a.83.83 0 0 1-.191.264L9.137 8.047a.17.17 0 0 1-.087.043l-1.633.268.35-1.637a.167.167 0 0 1 .048-.087l4.221-3.97c.203-.19.402-.282.598-.276.197.006.39.11.58.312l.184.196a.828.828 0 0 1 .175.274c.037.1.054.207.05.322a.827.827 0 0 1-.07.318Z" />
    </svg>
  );
}

function TaskCompleteIcon() {
  return (
    <svg className="task-action-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#fff" d="M14.698 3.933 6.46 12.132a1.16 1.16 0 0 1-.376.254 1.158 1.158 0 0 1-.447.085c-.16 0-.31-.028-.447-.085a1.154 1.154 0 0 1-.376-.254L1.326 8.66a.495.495 0 0 1 0-.709.493.493 0 0 1 .705 0l3.488 3.472c.04.039.079.058.118.058.039 0 .078-.02.117-.058l8.238-8.199a.495.495 0 0 1 .709.003.491.491 0 0 1-.003.705Z" />
    </svg>
  );
}

function TaskFilesIcon() {
  return (
    <svg className="task-action-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M12.654 14.497v.003h-10a1.82 1.82 0 0 1-.704-.134 1.82 1.82 0 0 1-.592-.403 1.823 1.823 0 0 1-.403-.593 1.82 1.82 0 0 1-.134-.703V3.333c0-.253.044-.487.134-.703.09-.216.224-.414.402-.593.18-.18.377-.313.593-.403.216-.09.45-.134.704-.134h2.709c.286 0 .546.055.781.165.235.11.444.275.627.495l1.067 1.28c.017.02.036.035.057.045.022.01.045.015.071.015h4.688c.253 0 .488.045.704.134.216.09.413.224.592.403.18.179.314.377.403.593.09.216.134.45.134.703V7.23a2 2 0 0 1 .272.275c.184.224.307.463.37.716.064.254.067.523.01.806l-.8 4c-.043.214-.117.41-.223.586a1.822 1.822 0 0 1-.412.473c-.17.138-.35.242-.544.311-.16.057-.329.09-.506.1ZM1.821 11.09V3.333c0-.278.069-.486.208-.625.139-.139.347-.208.625-.208h2.709c.13 0 .248.025.355.075.107.05.202.125.285.225L7.07 4.08c.117.14.25.245.399.315.15.07.315.105.497.105h4.688c.278 0 .486.07.625.208.139.14.208.348.208.625v1.505a2.13 2.13 0 0 0-.146-.005H4.29c-.481 0-.87.117-1.168.351-.297.234-.502.586-.614 1.054L1.82 11.09Zm12.338-2.26a.826.826 0 0 0-.005-.366.828.828 0 0 0-.168-.326.827.827 0 0 0-.286-.228.828.828 0 0 0-.358-.077H4.288c-.219 0-.396.054-.53.16-.136.106-.229.266-.28.479l-.962 4a.828.828 0 0 0-.009.374c.026.118.08.23.164.336.084.106.18.186.289.239.11.053.231.079.366.079h9.214c.228 0 .41-.056.546-.168.137-.111.227-.279.272-.502l.8-4Z" />
    </svg>
  );
}

function FolderPanelIcon() {
  return (
    <svg className="file-group-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M1.167 3.333c0-.253.044-.487.134-.703.09-.216.224-.414.403-.593.179-.18.376-.313.592-.403.216-.09.45-.134.704-.134h2.709c.286 0 .546.055.781.165.235.11.444.275.627.495l1.067 1.28c.017.02.036.035.057.045.022.01.045.015.071.015H13c.253 0 .488.045.704.134.216.09.413.224.592.403.18.18.314.377.403.593.09.216.134.45.134.704v7.333c0 .253-.044.487-.134.703-.09.216-.224.414-.403.593-.179.18-.376.313-.592.403-.216.09-.45.134-.704.134H3c-.253 0-.488-.044-.704-.134a1.815 1.815 0 0 1-.592-.403 1.822 1.822 0 0 1-.403-.593 1.821 1.821 0 0 1-.134-.703V3.333Zm1.06-.32a.828.828 0 0 0-.06.32v3.574h11.666V5.333a.828.828 0 0 0-.06-.32.826.826 0 0 0-.184-.269.83.83 0 0 0-.27-.183A.83.83 0 0 0 13 4.5H8.312c-.182 0-.348-.035-.497-.105a1.156 1.156 0 0 1-.399-.315L6.349 2.8a.829.829 0 0 0-.285-.225.83.83 0 0 0-.355-.075H3a.826.826 0 0 0-.32.061.83.83 0 0 0-.27.183.826.826 0 0 0-.182.27Zm11.606 4.894H2.167v4.76c0 .115.02.221.06.32.041.098.102.188.184.269a.83.83 0 0 0 .269.183c.098.04.205.061.32.061h10c.115 0 .222-.02.32-.061a.83.83 0 0 0 .27-.183.826.826 0 0 0 .182-.27.828.828 0 0 0 .061-.32v-4.76Z" />
    </svg>
  );
}

function FileGroupChevronIcon({ collapsed }) {
  return (
    <svg className="file-group-chevron" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d={collapsed ? "m6 3.75 4.25 4.25L6 12.25" : "m3.75 6 4.25 4.25L12.25 6"} stroke="#8F9299" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ReadFileIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M10.152.857a.487.487 0 0 1 .2.124l3.324 3.323a.487.487 0 0 1 .156.407v8.623c0 .253-.044.488-.134.704-.09.216-.224.414-.403.593a1.821 1.821 0 0 1-.592.402c-.216.09-.45.135-.704.135h-8c-.253 0-.488-.045-.704-.134a1.823 1.823 0 0 1-.592-.403 1.82 1.82 0 0 1-.403-.593 1.822 1.822 0 0 1-.134-.704V2.668c0-.254.044-.488.134-.704.09-.216.224-.414.403-.593A1.82 1.82 0 0 1 3.295.97c.216-.09.45-.135.704-.135h5.956a.49.49 0 0 1 .197.023Zm2.68 4.31v8.167c0 .278-.069.486-.208.625-.139.14-.347.209-.625.209h-8c-.278 0-.486-.07-.625-.209-.139-.139-.208-.347-.208-.625V2.668c0-.278.07-.487.208-.625.139-.14.347-.209.625-.209h5.5v2.167c0 .161.028.31.085.448.057.137.143.263.257.377.114.114.24.2.377.256.137.057.287.086.448.086h2.166ZM10.5 4.002v-1.46l1.626 1.627h-1.46c-.055 0-.096-.014-.124-.042-.028-.028-.042-.07-.042-.125Zm-.132 3.317H5.634a.491.491 0 0 0-.5.5.49.49 0 0 0 .277.45.488.488 0 0 0 .223.05h4.733a.492.492 0 0 0 .5-.5.491.491 0 0 0-.5-.5ZM5.634 9.684h4.733a.491.491 0 0 0 .5-.5.49.49 0 0 0-.278-.449.488.488 0 0 0-.222-.05H5.634a.492.492 0 0 0-.5.5.491.491 0 0 0 .5.5Z" />
    </svg>
  );
}

function WriteFileIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M9.751 1.494c-.207.109-.391.26-.553.454l-6.971 8.364a1.821 1.821 0 0 0-.415.982l-.261 2.48a.826.826 0 0 0 .05.404c.05.121.132.23.246.324a.828.828 0 0 0 .364.182.827.827 0 0 0 .406-.024l2.393-.714c.177-.052.34-.127.486-.224.148-.098.28-.217.399-.359l6.97-8.362c.162-.194.277-.404.347-.627.07-.224.093-.462.07-.714a1.822 1.822 0 0 0-.199-.69 1.82 1.82 0 0 0-.456-.553l-.85-.706a1.821 1.821 0 0 0-.626-.346 1.82 1.82 0 0 0-.712-.069 1.822 1.822 0 0 0-.688.198Zm-6.756 9.458 6.971-8.364a.828.828 0 0 1 .251-.206.825.825 0 0 1 .313-.09c.115-.01.223 0 .324.031a.827.827 0 0 1 .285.158l.85.705a.83.83 0 0 1 .207.252c.05.094.08.199.09.313a.83.83 0 0 1-.032.325.83.83 0 0 1-.158.285l-6.97 8.362a.823.823 0 0 1-.402.265l-2.153.642.236-2.232a.827.827 0 0 1 .188-.446Z" />
      <path fillRule="evenodd" fill="#8F9299" d="m9.433 2.737 2.644 2.196a.492.492 0 0 1 .065.704.49.49 0 0 1-.704.065L8.795 3.507a.489.489 0 0 1-.169-.5.49.49 0 0 1 .104-.204.49.49 0 0 1 .5-.168.492.492 0 0 1 .204.103Z" />
      <path fillRule="evenodd" fill="#8F9299" d="m3.003 10.527 2.538 2.109a.49.49 0 0 1 .169.5.489.489 0 0 1-.103.204l-.002.002a.489.489 0 0 1-.499.166.487.487 0 0 1-.203-.103l-2.54-2.108a.488.488 0 0 1-.168-.5.488.488 0 0 1 .104-.204.493.493 0 0 1 .704-.065Z" />
      <path fillRule="evenodd" fill="#8F9299" d="M13.955 13.498H6.916a.49.49 0 0 0-.5.5.49.49 0 0 0 .278.45c.067.034.141.05.222.05h7.04a.49.49 0 0 0 .5-.498V14a.49.49 0 0 0-.278-.45.488.488 0 0 0-.223-.05Z" />
    </svg>
  );
}

function UploadMinioIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="M8.5 10.5v3h2.75q.992-.03 1.775-.448.475-.255.873-.653.399-.399.654-.874.419-.783.448-1.775-.02-.914-.387-1.656-.223-.45-.574-.836-.373-.41-.826-.686-.68-.413-1.541-.525-.18-.869-.656-1.52-.27-.369-.633-.667-.38-.312-.811-.511Q8.857 3.019 8 3q-.86.02-1.575.35-.43.199-.808.51-.363.297-.631.664-.478.653-.658 1.523-.863.113-1.542.526-.453.276-.825.685-.35.385-.573.833Q1.02 8.834 1 9.75q.03.992.448 1.775.255.475.654.873.398.399.873.654.783.419 1.775.448H7.5v-3h-.932a.5.5 0 0 1-.385-.82l1.433-1.72a.5.5 0 0 1 .768 0l1.433 1.72a.5.5 0 0 1-.385.82H8.5Z" />
    </svg>
  );
}

function AuditIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M9.75 10V7.437a2.983 2.983 0 0 0 1.235-2.218 3.024 3.024 0 0 0-.149-1.133A2.938 2.938 0 0 0 9.169 2.24 3.008 3.008 0 0 0 8 2.015c-.42 0-.81.075-1.17.225a2.915 2.915 0 0 0-1.667 1.846 2.908 2.908 0 0 0-.008 1.851 2.986 2.986 0 0 0 1.095 1.5V10H4a2.071 2.071 0 0 0-.887.205 1.986 1.986 0 0 0-.527.381c-.38.38-.576.851-.586 1.414h12a2.07 2.07 0 0 0-.205-.887 1.987 1.987 0 0 0-.381-.527c-.38-.38-.851-.576-1.414-.586H9.75ZM2 13v1h12v-1H2Z" />
    </svg>
  );
}

function ModelSettingsIcon() {
  return (
    <svg className="model-settings-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="m14.7 8.93-2.549 4.333a1.821 1.821 0 0 1-.66.678 1.82 1.82 0 0 1-.92.225H5.429a1.82 1.82 0 0 1-.919-.225 1.82 1.82 0 0 1-.66-.678L1.3 8.929A1.818 1.818 0 0 1 1.027 8c0-.31.09-.62.273-.93l2.55-4.333a1.82 1.82 0 0 1 .66-.678c.263-.15.57-.226.92-.226h5.14c.35 0 .657.076.92.226.263.15.484.377.661.678L14.7 7.07c.182.31.273.62.273.93 0 .31-.09.62-.273.93Zm-.862-.508A.827.827 0 0 0 13.962 8a.828.828 0 0 0-.124-.423L11.29 3.244a.827.827 0 0 0-.3-.308.827.827 0 0 0-.418-.103H5.429a.825.825 0 0 0-.418.103.825.825 0 0 0-.3.308L2.16 7.577A.828.828 0 0 0 2.039 8c0 .14.041.281.124.422l2.549 4.334c.08.137.18.24.3.308s.26.102.418.102h5.142a.83.83 0 0 0 .418-.102.83.83 0 0 0 .3-.308l2.55-4.334ZM10.167 8c0 .3-.053.576-.159.832a2.157 2.157 0 0 1-.476.7c-.211.211-.445.37-.7.476a2.152 2.152 0 0 1-.832.159c-.3 0-.576-.053-.832-.159a2.16 2.16 0 0 1-.7-.476 2.152 2.152 0 0 1-.476-.7A2.152 2.152 0 0 1 5.833 8c0-.3.053-.576.159-.832.106-.255.264-.489.476-.7.211-.212.445-.37.7-.476.256-.106.533-.159.832-.159.3 0 .576.053.832.159.255.106.489.264.7.476.211.211.37.445.476.7.106.256.159.533.159.832Zm-1 0c0-.161-.029-.31-.086-.448a1.158 1.158 0 0 0-.256-.377c-.114-.114-.24-.2-.377-.256A1.16 1.16 0 0 0 8 6.833c-.161 0-.31.029-.448.086a1.155 1.155 0 0 0-.377.256c-.114.114-.2.24-.256.377A1.16 1.16 0 0 0 6.833 8c0 .16.029.31.086.448.057.137.142.263.256.377.114.114.24.2.377.256.137.057.287.086.448.086.16 0 .31-.029.448-.086.137-.057.263-.142.377-.256.114-.114.2-.24.256-.377.057-.138.086-.287.086-.448Z" />
    </svg>
  );
}

function HistoryIcon() {
  return (
    <svg className="model-settings-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="M15.167 8c0 .99-.175 1.907-.525 2.751a7.118 7.118 0 0 1-1.574 2.317c-.7.7-1.472 1.224-2.317 1.574A7.12 7.12 0 0 1 8 15.167c-.99 0-1.907-.175-2.751-.525a7.122 7.122 0 0 1-2.317-1.574 7.118 7.118 0 0 1-1.574-2.317 7.116 7.116 0 0 1-.525-2.75c0-.99.175-1.907.525-2.752a7.117 7.117 0 0 1 1.574-2.316c.7-.7 1.472-1.225 2.317-1.575a7.118 7.118 0 0 1 2.75-.525c.99 0 1.907.175 2.752.525.845.35 1.617.875 2.317 1.575.7.7 1.224 1.471 1.574 2.316.35.845.525 1.762.525 2.751Zm-1 0c0-.851-.15-1.64-.452-2.367A6.126 6.126 0 0 0 12.36 3.64a6.124 6.124 0 0 0-1.993-1.355A6.125 6.125 0 0 0 8 1.833c-.852 0-1.64.151-2.367.452A6.124 6.124 0 0 0 3.639 3.64a6.124 6.124 0 0 0-1.354 1.993A6.126 6.126 0 0 0 1.833 8c0 .852.15 1.64.452 2.367a6.125 6.125 0 0 0 1.354 1.994 6.124 6.124 0 0 0 1.994 1.354A6.123 6.123 0 0 0 8 14.167c.851 0 1.64-.15 2.367-.452a6.124 6.124 0 0 0 1.993-1.354 6.124 6.124 0 0 0 1.355-1.994A6.125 6.125 0 0 0 14.167 8ZM8.4 8.244h3.5a.5.5 0 0 1 0 1h-4a.5.5 0 0 1-.5-.5v-4.5a.5.5 0 0 1 1 0v4Z" />
    </svg>
  );
}

function TaskUpdateIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="M12.078 4.328c.326.365.602.774.828 1.228a.495.495 0 0 0 .668.226h.002a.495.495 0 0 0 .226-.669v-.002a6.49 6.49 0 0 0-.981-1.453 6.499 6.499 0 0 0-1.373-1.155 6.444 6.444 0 0 0-1.611-.738 6.476 6.476 0 0 0-1.86-.265c-.667 0-1.305.095-1.913.284a6.341 6.341 0 0 0-1.537.72 6.484 6.484 0 0 0-1.38 1.184V2.667a.49.49 0 0 0-.5-.5.49.49 0 0 0-.5.5v2.632a.492.492 0 0 0 .19.43c.025.02.053.037.082.051l.005.003h.001c.035.017.07.03.109.038a.467.467 0 0 0 .154.012h2.219a.495.495 0 0 0 .5-.497v-.003a.495.495 0 0 0-.498-.5H3.52a5.406 5.406 0 0 1 1.546-1.486 5.34 5.34 0 0 1 1.28-.602A5.396 5.396 0 0 1 7.977 2.5c.55 0 1.077.076 1.581.227.472.14.923.348 1.355.621.441.28.83.606 1.165.98Zm-8.984 6.116c.226.454.502.863.828 1.228.335.374.724.7 1.165.98.432.273.883.48 1.355.621a5.478 5.478 0 0 0 1.581.227c.57 0 1.113-.082 1.631-.245.446-.14.872-.34 1.28-.602a5.476 5.476 0 0 0 1.546-1.486h-1.387a.49.49 0 0 1-.449-.277.488.488 0 0 1-.05-.223.491.491 0 0 1 .5-.5h2.219a.493.493 0 0 1 .263.05.491.491 0 0 1 .204.185.492.492 0 0 1 .073.305v2.629a.495.495 0 0 1-.5.497h-.002a.495.495 0 0 1-.498-.5v-1.02a6.415 6.415 0 0 1-1.38 1.182 6.33 6.33 0 0 1-1.537.72 6.39 6.39 0 0 1-1.913.285 6.47 6.47 0 0 1-1.86-.265 6.444 6.444 0 0 1-1.61-.738 6.5 6.5 0 0 1-1.374-1.155 6.49 6.49 0 0 1-.98-1.453.49.49 0 0 1 .048-.525.487.487 0 0 1 .177-.145.49.49 0 0 1 .526.048c.06.045.108.104.144.177Z" />
    </svg>
  );
}

function ThinkingIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="M8 1c.146 0 .266.047.36.14.093.094.14.214.14.36v3a.487.487 0 0 1-.14.36A.487.487 0 0 1 8 5a.487.487 0 0 1-.36-.14.487.487 0 0 1-.14-.36v-3c0-.146.047-.266.14-.36A.487.487 0 0 1 8 1Zm0 10c.146 0 .266.047.36.14.093.094.14.214.14.36v3a.487.487 0 0 1-.14.36A.487.487 0 0 1 8 15a.487.487 0 0 1-.36-.14.487.487 0 0 1-.14-.36v-3c0-.146.047-.266.14-.36A.487.487 0 0 1 8 11Zm7-3a.487.487 0 0 1-.14.36.487.487 0 0 1-.36.14h-3a.487.487 0 0 1-.36-.14A.487.487 0 0 1 11 8c0-.146.047-.266.14-.36a.487.487 0 0 1 .36-.14h3c.146 0 .266.047.36.14.093.094.14.214.14.36ZM5 8a.487.487 0 0 1-.14.36.487.487 0 0 1-.36.14h-3a.487.487 0 0 1-.36-.14A.487.487 0 0 1 1 8c0-.146.047-.266.14-.36a.487.487 0 0 1 .36-.14h3c.146 0 .266.047.36.14.093.094.14.214.14.36ZM3.047 3.047a.522.522 0 0 1 .36-.14c.135 0 .25.046.343.14l2.125 2.125c.094.104.141.222.141.351 0 .13-.05.245-.148.344a.47.47 0 0 1-.344.15.516.516 0 0 1-.352-.142L3.047 3.75a.468.468 0 0 1-.14-.344.52.52 0 0 1 .14-.359Zm7.078 7.078a.487.487 0 0 1 .351-.156c.13 0 .248.052.352.156l2.125 2.125c.094.094.14.208.14.344a.48.48 0 0 1-.148.352.482.482 0 0 1-.351.148.467.467 0 0 1-.345-.14l-2.125-2.125a.486.486 0 0 1-.156-.352c0-.13.052-.247.156-.351l.001-.001Zm2.828-7.078c.094.104.14.224.14.36a.47.47 0 0 1-.14.343l-2.125 2.125a.513.513 0 0 1-.352.141.473.473 0 0 1-.344-.149.47.47 0 0 1-.148-.344c0-.13.047-.247.14-.35l2.125-2.126a.468.468 0 0 1 .345-.14c.135 0 .255.046.359.14Zm-7.078 7.078a.485.485 0 0 1 .156.352c0 .13-.052.247-.156.35L3.75 12.954a.468.468 0 0 1-.344.14.48.48 0 0 1-.352-.148.484.484 0 0 1-.148-.351c0-.136.047-.25.14-.345l2.126-2.125a.486.486 0 0 1 .351-.156c.13 0 .247.052.352.156v.001Z" />
    </svg>
  );
}

function CommandIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M30.4417 5C32.406 5 34.265 5.44776 35.9207 6.24607L32.7172 9.42668C30.8706 11.2601 30.8706 14.2327 32.7172 16.0661C34.5638 17.8995 37.5578 17.8995 39.4044 16.0661L42.2571 13.2337C42.7379 14.5558 43 15.9818 43 17.4685C43 24.3547 37.3775 29.937 30.4417 29.937C28.7825 29.937 27.1985 29.6176 25.7486 29.0373L13.07 41.6253C11.2238 43.4582 8.2307 43.4582 6.38459 41.6253C4.53847 39.7924 4.53847 36.8207 6.38459 34.9877L18.9523 22.5099C18.2651 20.9684 17.8834 19.2627 17.8834 17.4685C17.8834 10.5823 23.5059 5 30.4417 5Z" fill="none" stroke="currentColor" strokeWidth="4" strokeLinejoin="round" />
    </svg>
  );
}

function isExpiredApprovalError(error) {
  const text = String(error || "");
  return /没有待确认.*(?:请求|操作)|请求已过期/.test(text);
}

function normalizeFiles(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => (typeof item === "string" ? item : item?.path || item?.filename)).filter(Boolean);
}

function eventClock(event) {
  const raw = event?._receivedAt ?? event?.timestamp;
  if (raw == null || raw === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  return value > 1e11 ? value : value > 1e9 ? value * 1000 : value;
}

function stampEvent(event) {
  if (!event || typeof event !== "object") return { type: "text", text: String(event ?? ""), _receivedAt: Date.now() };
  const clock = eventClock(event);
  return clock == null ? { ...event, _receivedAt: Date.now() } : { ...event, _receivedAt: clock };
}

function normalizeEvents(task) {
  const source = Array.isArray(task?.log) ? task.log : Array.isArray(task?.events) ? task.events : [];
  return source.reduce((events, event) => {
    if (!event || typeof event !== "object") {
      events.push({ type: "text", text: String(event ?? "") });
      return events;
    }
    const content = event.text ?? event.content;
    const normalized = { ...event, text: typeof content === "string" ? content : content == null ? "" : $json(content) };
    const last = events[events.length - 1];
    if ((normalized.type === "text" || normalized.type === "thinking") && last?.type === normalized.type) {
      events[events.length - 1] = { ...last, text: `${last.text || ""}${normalized.text || ""}` };
    } else {
      events.push(normalized);
    }
    return events;
  }, []);
}

function formatDuration(durationMs) {
  const milliseconds = Math.max(0, Number(durationMs) || 0);
  if (milliseconds < 1000) return `${Math.max(1, Math.round(milliseconds))}ms`;
  const seconds = milliseconds / 1000;
  return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
}

function eventDuration(events, index) {
  const event = events[index];
  const start = eventClock(event);
  if (start == null || ["done", "tool_result", "approval_result", "audit", "error"].includes(event.type)) return null;
  let endEvent = null;
  if (event.type === "tool_use" && event.id) {
    endEvent = events.slice(index + 1).find((candidate) => candidate.type === "tool_result" && candidate.tool_use_id === event.id);
  } else if (event.type === "approval_request" && event.id) {
    endEvent = events.slice(index + 1).find((candidate) => candidate.type === "approval_result" && candidate.id === event.id);
  } else if (event.type === "thinking") {
    endEvent = events.slice(index + 1).find((candidate) => candidate.type !== "thinking");
  } else {
    endEvent = events[index + 1];
  }
  const end = eventClock(endEvent);
  return end != null && end > start ? end - start : null;
}

function eventTitle(event) {
  const names = { Read: "读取文件", Write: "写入文件", Edit: "修改文件", Bash: "执行命令", Glob: "查找文件", Grep: "搜索内容", Agent: "调用子智能体", TaskCreate: "创建任务" };
  if (event.type === "error" || event.is_error) return "提示";
  if (event.type === "run_queued") return "排队中";
  if (event.type === "run_started") return "开始执行";
  if (event.type === "thinking") return "思考中";
  if (event.type === "model_switch") return "模型切换";
  if (event.type === "tool_result") return "工具结果";
  return names[event.name] || event.name || event.type || "执行步骤";
}

function eventStatus(event) {
  if (event.type === "error" || event.is_error) return "error";
  if (event.type === "approval_request") return "warning";
  if (event.type === "done" || event.type === "approval_result") return "success";
  return "process";
}

function eventDescription(event) {
  if (event.type === "thinking" || event.type === "text" || event.type === "assistant") return event.text || "";
  if (event.type === "tool_result") return String(event.content || "").slice(0, 1200);
  if (event.type === "run_queued") return event.position
    ? `当前第 ${event.position} 位，队列共 ${event.queueLength ?? "—"} 个任务`
    : "任务已排队，等待空闲执行槽";
  if (event.type === "run_started") return "已获得执行槽，开始本轮执行";
  if (event.type === "error") return `提示：${event.error || "本轮执行未完成，可继续执行"}`;
  if (event.type === "approval_request") return `${event.summary || "需要确认"}${event.detail ? `：${event.detail}` : ""}`;
  if (event.type === "approval_result") return event.approved ? "已允许执行" : "已拒绝执行";
  if (event.type === "model_switch") return `${event.from || "当前模型"} → ${event.to || "备用模型"}（${event.reason || "自动切换"}）`;
  if (event.input) return typeof event.input === "string" ? event.input : $json(event.input);
  return event.text || "";
}

function EventFileText({ text, files, onFile }) {
  const source = String(text || "");
  const paths = (files || []).map((file) => file.path).filter(Boolean).sort((a, b) => b.length - a.length);
  if (!paths.length || !onFile) return <>{source}</>;
  const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`(${paths.map(escapeRegExp).join("|")})`, "g");
  return <>{source.split(pattern).map((part, index) => paths.includes(part)
    ? <button type="button" className="event-file-link" key={`${part}-${index}`} onClick={(clickEvent) => { clickEvent.stopPropagation(); onFile(part); }}>{part}</button>
    : <React.Fragment key={index}>{part}</React.Fragment>)}</>;
}

function compactEventSummary(value) {
  const source = String(value || "");
  const trimmed = source.trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      const first = Array.isArray(parsed) ? parsed[0] : Object.entries(parsed)[0];
      if (Array.isArray(first)) return `${first[0]}: ${typeof first[1] === "string" ? first[1] : JSON.stringify(first[1])}`;
      if (first !== undefined) return typeof first === "string" ? first : JSON.stringify(first);
    } catch { /* 多行非标准 JSON，继续按首行处理 */ }
  }
  const firstLine = trimmed.split(/\r?\n/).map((line) => line.trim()).find((line) => line && !/^[{}[\],]+$/.test(line)) || "";
  return firstLine.replace(/^[{"'`\s]+|[}"'`,\s]+$/g, "").replace(/^([^:]+):\s*["']?(.*?)["']?$/, "$1: $2");
}

function ThoughtEvent({ event, onApprove, files, onFile, loading = false, approvalResult = null, completed = false, durationMs = null }) {
  const [expanded, setExpanded] = useState(false);
  const isReadTool = event.type === "tool_use" && event.name === "Read";
  const isWriteTool = event.type === "tool_use" && event.name === "Write";
  const isEditTool = event.type === "tool_use" && event.name === "Edit";
  const isAudit = event.type === "audit";
  const isTaskUpdate = event.type === "tool_use" && event.name === "TaskUpdate";
  const isCommand = event.type === "tool_use" && event.name === "Bash";
  const kind = event.type === "thinking" ? "thinking" : event.type === "model_switch" ? "model-switch" : event.type === "tool_result" ? "tool-result" : event.type === "approval_result" ? "approval-result" : event.type === "error" || event.is_error ? "error" : event.type === "run_queued" ? "queued" : event.type === "run_started" ? "started" : event.name === "TaskCreate" ? "task-create" : event.type === "approval_request" ? "approval" : isReadTool ? "read-file" : isWriteTool ? "write-file" : isEditTool ? "edit-file" : isAudit ? "audit" : isTaskUpdate ? "task-update" : isCommand ? "command" : "tool-use";
  const icon = event.type === "thinking" ? <ThinkingIcon /> : event.type === "model_switch" ? "↻" : event.type === "tool_result" ? "✓" : event.type === "approval_result" && event.approved ? "✓" : event.type === "error" || event.is_error ? "ℹ" : event.type === "run_queued" ? "⏳" : event.type === "run_started" ? "▶" : event.name === "TaskCreate" ? "＋" : event.type === "approval_request" ? "?" : isReadTool ? <ReadFileIcon /> : isWriteTool || isEditTool ? <WriteFileIcon /> : isAudit ? <AuditIcon /> : isTaskUpdate ? <TaskUpdateIcon /> : isCommand ? <CommandIcon /> : "·";
  const detail = eventDescription(event);
  const approved = event.type === "approval_request" && approvalResult?.approved === true;
  const durationLabel = durationMs != null && !loading ? event.type === "thinking" ? `已思考 ${formatDuration(durationMs)}` : formatDuration(durationMs) : "";
  const toggleExpanded = () => setExpanded((value) => !value);
  const collapsedRowProps = {
    className: "thought-collapsed-row thought-collapsed-row-clickable",
    onClick: toggleExpanded,
    onKeyDown: (keyboardEvent) => {
      if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") {
        keyboardEvent.preventDefault();
        toggleExpanded();
      }
    },
    role: "button",
    tabIndex: 0,
  };
  return (
    <div className={`chain-event chain-event-${kind}`}>
      <div {...collapsedRowProps}>
        <div className="thought-header">
          <span className={`thought-icon thought-icon-${kind}`}>{icon}</span>
          <button type="button" className="thought-toggle" onClick={(clickEvent) => { clickEvent.stopPropagation(); toggleExpanded(); }}>{eventTitle(event)}</button>
        </div>
        {!expanded && detail && <div className="thought-summary"><EventFileText text={compactEventSummary(detail)} files={files} onFile={onFile} /></div>}
        {durationLabel && <span className="thought-duration">{durationLabel}</span>}
      </div>
      {expanded && <div className="thought-detail"><EventFileText text={detail} files={files} onFile={onFile} /></div>}
      {event.type === "approval_request" && !completed && (
        <div className="approval-actions">
          {approved ? <Button type="primary" size="small" disabled>✓ 已允许执行</Button> : <>
            <Button type="primary" size="small" onClick={() => onApprove(event.id, true)}>允许执行</Button>
            <Button size="small" onClick={() => onApprove(event.id, false)}>拒绝</Button>
          </>}
        </div>
      )}
    </div>
  );
}

function inlineMarkdown(value) {
  const text = String(value || "");
  const token = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|`[^`]+`|\[[^\]]+\]\([^\)]+\))/g;
  return text.split(token).map((part, index) => {
    if (/^\*\*.*\*\*$|^__.*__$/.test(part)) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (/^\*.*\*$|^_.*_$/.test(part)) return <em key={index}>{part.slice(1, -1)}</em>;
    if (/^`.*`$/.test(part)) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = part.match(/^\[([^\]]+)\]\(([^\)]+)\)$/);
    if (link) return <a key={index} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    return <React.Fragment key={index}>{part.split("\n").map((line, lineIndex) => <React.Fragment key={lineIndex}>{lineIndex ? <br /> : null}{line}</React.Fragment>)}</React.Fragment>;
  });
}

function markdownTableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function AssistantText({ text }) {
  const source = String(text || "").split("\n");
  const renderLines = (lines) => {
    const blocks = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      const trimmed = line.trim();
      if (!trimmed) { index += 1; continue; }
      if (/^```/.test(trimmed)) {
        const code = []; index += 1;
        while (index < lines.length && !/^```/.test(lines[index].trim())) code.push(lines[index++]);
        if (index < lines.length) index += 1;
        blocks.push(<pre className="markdown-code" key={`code-${index}`}><code>{code.join("\n")}</code></pre>); continue;
      }
      if (/^\|/.test(trimmed) && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
        const head = markdownTableRow(line); index += 2; const rows = [];
        while (index < lines.length && /^\s*\|/.test(lines[index])) rows.push(markdownTableRow(lines[index++]));
        blocks.push(<table className="markdown-table" key={`table-${index}`}><thead><tr>{head.map((cell, cellIndex) => <th key={cellIndex}>{inlineMarkdown(cell)}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{head.map((_, cellIndex) => <td key={cellIndex}>{inlineMarkdown(row[cellIndex] || "")}</td>)}</tr>)}</tbody></table>); continue;
      }
      if (/^#{1,3}\s/.test(trimmed)) { blocks.push(<h3 key={`heading-${index}`}>{inlineMarkdown(trimmed.replace(/^#{1,3}\s*/, ""))}</h3>); index += 1; continue; }
      if (/^[-*]\s/.test(trimmed)) { const items = []; while (index < lines.length && /^\s*[-*]\s/.test(lines[index])) items.push(lines[index++].replace(/^\s*[-*]\s+/, "")); blocks.push(<ul key={`list-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inlineMarkdown(item)}</li>)}</ul>); continue; }
      if (/^:::/.test(trimmed)) {
        if (trimmed !== ":::") {
          const title = trimmed.replace(/^:::(?:details)?\s*/, "") || "详情（点击展开）";
          index += 1; const inner = [];
          while (index < lines.length && !/^:::/.test(lines[index].trim())) inner.push(lines[index++]);
          if (index < lines.length) index += 1;
          blocks.push(<details className="assistant-details" key={`details-${index}`}><summary>{title}</summary>{renderLines(inner)}</details>);
        } else index += 1;
        continue;
      }
      const paragraph = [line]; index += 1;
      while (index < lines.length && lines[index].trim() && !/^```|^#{1,3}\s|^\s*[-*]\s|^\s*\||^:::/.test(lines[index])) paragraph.push(lines[index++]);
      blocks.push(<p key={`paragraph-${index}`}>{inlineMarkdown(paragraph.join("\n"))}</p>);
    }
    return blocks;
  };
  return <div className="assistant-text">{renderLines(source)}</div>;
}

function EventFeed({ events, onApprove, files, onFile, busy = false, scope = "events" }) {
  // Keep the synchronization journal lossless (every seq remains available
  // for cursor/dedupe), but collapse adjacent display deltas after all SSE,
  // polling and history pages have been merged. Normalizing individual
  // response batches is insufficient because one reasoning block commonly
  // crosses many two-second polling windows.
  const displayEvents = normalizeEvents({ events });
  const lastEvent = displayEvents[displayEvents.length - 1];
  const waitingForNextEvent = busy && !["done", "error", "approval_request"].includes(lastEvent?.type);
  const approvalResults = displayEvents.reduce((result, event) => {
    if (event.type === "approval_result" && event.id) result[event.id] = event;
    return result;
  }, {});
  return (
    <div className="feed-list">
      {displayEvents.map((event, index) => {
        // React keys use the same event identity as the merge (task/run + seq
        // or clientMessageId); array indexes are only the legacy fallback.
        const key = eventKey(event, scope, index);
        if (event.type === "user") return <div className="user-message" key={key}>{event.text}</div>;
        if (["text", "assistant"].includes(event.type)) return <div className="assistant-message" key={key}><AssistantText text={event.text} /></div>;
        if (event.type === "done") return <div className="done-note" key={key}>{event.status === "error" ? "本轮执行结束 · 未完成（可继续执行）" : `本轮执行结束 · ${event.status || "完成"}`}</div>;
        const loading = busy && index === displayEvents.length - 1 && event.type === "thinking";
        const executionFinished = event.type === "approval_request" && displayEvents.slice(index + 1).some((candidate) => candidate.type === "done");
        return <ThoughtEvent event={event} approvalResult={event.type === "approval_request" ? approvalResults[event.id] : null} completed={executionFinished} durationMs={eventDuration(displayEvents, index)} onApprove={onApprove} files={files} onFile={onFile} loading={loading} key={key} />;
      })}
      {waitingForNextEvent && lastEvent?.type !== "thinking" && (
        <ThoughtEvent event={{ type: "thinking", text: "" }} files={files} onFile={onFile} loading />
      )}
    </div>
  );
}

function parseCsv(text) {
  const source = String(text || "").replace(/^\uFEFF/, "");
  const rows = []; let row = []; let cell = ""; let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (char === '"') {
      if (quoted && source[index + 1] === '"') { cell += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === "," && !quoted) { row.push(cell); cell = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && source[index + 1] === "\n") index += 1;
      row.push(cell); cell = "";
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
    } else cell += char;
  }
  if (cell || row.length) { row.push(cell); if (row.some((value) => value !== "")) rows.push(row); }
  return rows;
}

function csvRecords(text) {
  const rows = parseCsv(text);
  const headers = rows[0] || [];
  return rows.slice(1).filter((row) => row.some((value) => String(value || "").trim())).map((row) => Object.fromEntries(headers.map((header, index) => [String(header || "").trim(), String(row[index] || "").trim()])));
}

function OntologyFilterIcon() {
  return <svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" aria-hidden="true"><path d="M0 0h16v16H0z"/><path fillRule="evenodd" fill="currentColor" d="m2.826 4.602 3.138 3.665a.826.826 0 0 1 .2.542v3.363c0 .38.086.706.256.98.17.275.425.496.766.664l.966.477c.194.096.385.139.574.13.189-.01.375-.071.559-.185a1.16 1.16 0 0 0 .413-.42c.092-.164.138-.355.138-.571V8.809a.827.827 0 0 1 .2-.542l3.138-3.665c.254-.297.404-.61.45-.936.045-.326-.014-.667-.178-1.023-.163-.355-.384-.622-.661-.8-.278-.178-.612-.267-1.004-.267H4.22c-.392 0-.726.09-1.004.267-.277.178-.498.445-.662.8-.163.356-.222.697-.177 1.023.046.327.196.639.45.936Zm4.228 3.57a1.82 1.82 0 0 0-.33-.556L3.586 3.952a.828.828 0 0 1-.205-.426.828.828 0 0 1 .08-.465.827.827 0 0 1 .302-.363.828.828 0 0 1 .456-.122h7.562c.178 0 .33.04.456.122.126.08.227.202.301.363a.828.828 0 0 1 .08.465.828.828 0 0 1-.204.426L9.276 7.616a1.82 1.82 0 0 0-.33.556c-.074.199-.11.41-.11.637v4.438a.165.165 0 0 1-.02.082.166.166 0 0 1-.059.06.163.163 0 0 1-.08.026.167.167 0 0 1-.082-.019l-.966-.477a.827.827 0 0 1-.348-.301.828.828 0 0 1-.117-.446V8.809c0-.226-.036-.438-.11-.637Z"/></svg>;
}

function defaultOntologyLayers(availability) {
  return ONTOLOGY_LAYER_DEFINITIONS.map((layer) => layer.key).filter((layer) => availability[layer]);
}

function OntologyEChartsPreview({ data, appliedLayers, prepared, onError, onRendered, onViewportChange }) {
  const scrollRef = useRef(null);
  const containerRef = useRef(null);
  const [ready, setReady] = useState(false);
  const preparedRef = useRef(prepared);
  preparedRef.current = prepared;
  useEffect(() => {
    let disposed = false;
    let chart = null;
    let observer = null;
    let wheelTarget = null;
    let wheelHandler = null;
    let renderPrepared = null;
    setReady(false);
    void import("echarts").then((echarts) => {
      if (disposed || !containerRef.current || !scrollRef.current) return;
      chart = echarts.init(containerRef.current);
      const viewport = readViewport(scrollRef.current);
      const renderGraph = (layoutPrepared) => {
        const viewportWidth = viewport.width;
        const viewportHeight = viewport.height;
        containerRef.current.style.width = `${viewportWidth}px`;
        containerRef.current.style.height = `${viewportHeight}px`;
        chart.resize({ width: viewportWidth, height: viewportHeight });
        if (!layoutPrepared || !layoutIsForViewport(layoutPrepared, viewport)) {
          chart.clear();
          setReady(false);
          return;
        }
        chart.setOption(radialGraphOption(layoutPrepared), { notMerge: true });
        const displayScale = layoutPrepared.fitScale;
        let roamZoom = 1;
        chart.off("graphRoam");
        chart.on("graphRoam", (event) => {
          if (!event.zoom) return;
          roamZoom *= event.zoom;
          chart.setOption({ series: [{ id: "ontology-graph", label: { fontSize: Math.max(6, 13 * displayScale * Math.min(Math.max(0.1, roamZoom), 1.8)) } }] });
        });
        setReady(true);
        onRendered?.("radial");
      };
      renderPrepared = renderGraph;
      renderGraph(preparedRef.current);
      wheelTarget = containerRef.current;
      wheelHandler = (event) => {
        if (event.ctrlKey) return;
        event.preventDefault();
        event.stopPropagation();
        chart.dispatchAction({ type: "graphRoam", seriesIndex: 0, dx: -event.deltaX, dy: -event.deltaY });
      };
      wheelTarget.addEventListener("wheel", wheelHandler, { passive: false, capture: true });
      observer = new ResizeObserver(() => {
        const next = readViewport(scrollRef.current);
        renderGraph(preparedRef.current);
        if (next.width !== viewport.width || next.height !== viewport.height) {
          viewport.width = next.width;
          viewport.height = next.height;
          onViewportChange?.(next);
        }
      });
      observer.observe(scrollRef.current);
    }).catch((error) => {
      console.error("语义环形布局加载失败", error);
      onError?.(error);
    });
    return () => {
      disposed = true;
      renderPrepared = null;
      observer?.disconnect();
      if (wheelTarget && wheelHandler) wheelTarget.removeEventListener("wheel", wheelHandler, { capture: true });
      chart?.dispose();
    };
  }, [data, appliedLayers]);
  useEffect(() => {
    if (prepared && renderPrepared) renderPrepared(prepared);
  }, [prepared]);
  return <div className="ontology-tree-scroll" ref={scrollRef}><div className="ontology-tree-preview" ref={containerRef} />{!ready && <div className="ontology-tree-loading-overlay"><Spin tip="正在加载语义环形布局…" /></div>}</div>;
}

class OntologyPreviewErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error) {
    this.props.onError?.(error);
  }
  componentDidUpdate(prevProps) {
    if (this.props.resetKey !== prevProps.resetKey && this.state.failed) {
      this.setState({ failed: false });
    }
  }
  render() {
    if (this.state.failed) {
      return <div className="ontology-sigma-loading"><Empty description="关系布局加载失败，请稍后重试" /></div>;
    }
    return this.props.children;
  }
}

function OntologyLayoutSelector({ value, onChange }) {
  const selected = ontologyLayoutOption(value) || ONTOLOGY_LAYOUT_OPTIONS[0];
  const options = ONTOLOGY_LAYOUT_OPTIONS.map((option) => ({
    ...option,
    label: <Tooltip title={option.hint} placement="left" mouseEnterDelay={0}><span>{option.label}</span></Tooltip>,
  }));
  return <div className="ontology-layout-selector"><span className="ontology-layout-label">布局</span><Select aria-label="布局" size="small" value={value} popupMatchSelectWidth={false} style={{ width: 148 }} options={options} onChange={onChange} /><Tooltip title={selected.hint} placement="bottom"><span className="ontology-layout-hint-icon" role="img" aria-label={`${selected.label}说明`}>?</span></Tooltip></div>;
}

function OntologyTreePreview({ data }) {
  const availability = data.availability || {};
  const [appliedLayers, setAppliedLayers] = useState(() => defaultOntologyLayers(availability));
  const [draftLayers, setDraftLayers] = useState(() => defaultOntologyLayers(availability));
  const [filterOpen, setFilterOpen] = useState(false);
  const [layoutMode, setLayoutMode] = useState("network");
  const [layoutError, setLayoutError] = useState(null);
  const [radialPrepared, setRadialPrepared] = useState(null);
  const [viewport, setViewport] = useState(() => normalizeViewport(0, 0));
  const lastGoodLayoutRef = useRef("network");
  const shellRef = useRef(null);
  const cacheRef = useRef(null);
  if (!cacheRef.current) cacheRef.current = createRadialLayoutCache({ maxEntries: 8 });
  const fingerprint = useMemo(() => ontologyDataFingerprint(data), [data]);
  const layerKey = appliedLayers.join("|");
  const prepareKey = radialCacheKey({
    fingerprint,
    layerKey,
    width: viewport.width,
    height: viewport.height,
  });
  useEffect(() => {
    let cancelled = false;
    const updateViewport = () => setViewport(readViewport(shellRef.current));
    updateViewport();
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(updateViewport) : null;
    if (observer && shellRef.current) observer.observe(shellRef.current);
    return () => {
      cancelled = true;
      observer?.disconnect();
    };
  }, []);
  const ensureRadialReady = useCallback(async () => {
    if (!prepareKey || !viewport.width || !viewport.height) return null;
    const cached = cacheRef.current.get(prepareKey);
    if (cached) return cached;
    let promise = cacheRef.current.getInFlight(prepareKey);
    if (!promise) {
      promise = Promise.resolve()
        .then(() => prepareRadialLayout(data, appliedLayers, viewport))
        .then((prepared) => {
          if (!prepared) throw new Error("RADIAL_LAYOUT_EMPTY");
          cacheRef.current.set(prepareKey, prepared);
          return prepared;
        })
        .finally(() => cacheRef.current.clearInFlight(prepareKey));
      cacheRef.current.putInFlight(prepareKey, promise);
    }
    return promise;
  }, [prepareKey, data, appliedLayers, viewport.width, viewport.height]);
  useEffect(() => {
    if (!prepareKey || !viewport.width || !viewport.height) return;
    let cancelled = false;
    const preload = () => {
      if (cancelled) return;
      void import("echarts");
      ensureRadialReady().catch((error) => {
        if (!cancelled) console.error("语义环形布局后台预计算失败", error);
      });
    };
    const idleId = typeof window.requestIdleCallback === "function"
      ? window.requestIdleCallback(preload, { timeout: 1500 })
      : window.setTimeout(preload, 600);
    return () => {
      cancelled = true;
      if (typeof window.cancelIdleCallback === "function") window.cancelIdleCallback(idleId);
      else window.clearTimeout(idleId);
    };
  }, [ensureRadialReady, prepareKey]);
  const switchLayout = (next) => {
    if (next === layoutMode || !ontologyLayoutOption(next)) return;
    setLayoutError(null);
    setLayoutMode(next);
  };
  const handleLayoutError = () => {
    setLayoutError("布局加载失败，已恢复上一个可用布局。");
    setLayoutMode(lastGoodLayoutRef.current);
    setRadialPrepared(null);
  };
  const handleLayoutRendered = (mode) => {
    lastGoodLayoutRef.current = mode;
  };
  useEffect(() => {
    if (layoutMode !== "radial") return;
    let cancelled = false;
    ensureRadialReady().then((prepared) => {
      if (cancelled || !prepared) return;
      setRadialPrepared(prepared);
    }).catch(() => {
      if (cancelled) return;
      setLayoutError("语义环形布局加载失败，已恢复上一个可用布局。");
      if (lastGoodLayoutRef.current !== "radial") setLayoutMode(lastGoodLayoutRef.current);
      else setRadialPrepared(null);
    });
    return () => { cancelled = true; };
  }, [layoutMode, ensureRadialReady]);
  const handleApplyLayers = (nextLayers) => {
    setAppliedLayers(nextLayers);
    setFilterOpen(false);
    setRadialPrepared(null);
  };
  const handleRadialViewportChange = (next) => {
    setViewport(next);
  };
  const filterContent = <div className="ontology-layer-menu">
    <div className="ontology-layer-options">{ONTOLOGY_LAYER_DEFINITIONS.map((layer) => <Checkbox key={layer.key} disabled={!availability[layer.key]} checked={draftLayers.includes(layer.key)} onChange={(event) => setDraftLayers((current) => event.target.checked ? [...current, layer.key] : current.filter((item) => item !== layer.key))}>{layer.label}</Checkbox>)}</div>
    <div className="ontology-layer-actions"><Button size="small" onClick={() => { setDraftLayers(appliedLayers); setFilterOpen(false); }}>取消</Button><Button size="small" type="primary" disabled={!draftLayers.length} onClick={() => { handleApplyLayers(ONTOLOGY_LAYER_DEFINITIONS.map((layer) => layer.key).filter((layer) => draftLayers.includes(layer))); }}>确认</Button></div>
  </div>;
  const radialLayout = layoutMode === "radial";
  return <div className="ontology-tree-shell" ref={shellRef}>
    <div className="ontology-toolbar"><OntologyLayoutSelector value={layoutMode} onChange={switchLayout} /><Popover open={filterOpen} placement="leftTop" trigger="click" content={filterContent} onOpenChange={(open) => { if (open) setDraftLayers(appliedLayers); setFilterOpen(open); }}><button type="button" className="ontology-layer-filter-button" aria-label="筛选可视化层级" title="筛选可视化层级"><OntologyFilterIcon /></button></Popover></div>
    {layoutError && <div className="ontology-layout-error" role="alert">{layoutError}</div>}
    {radialLayout ? <OntologyEChartsPreview key={`radial:${layerKey}`} data={data} appliedLayers={appliedLayers} prepared={radialPrepared} onError={handleLayoutError} onRendered={handleLayoutRendered} onViewportChange={handleRadialViewportChange} /> : <React.Suspense fallback={<div className="ontology-sigma-loading"><Spin tip="正在加载关系布局…" /></div>}><OntologyPreviewErrorBoundary key={`network:${layerKey}`} resetKey={`network:${layerKey}`} onError={handleLayoutError}><OntologySigmaPreview data={data} appliedLayers={appliedLayers} onError={handleLayoutError} onRendered={handleLayoutRendered} /></OntologyPreviewErrorBoundary></React.Suspense>}
  </div>;
}

function PreviewModalTitle({ title, fullscreen, onToggle }) {
  return <div className="preview-modal-title"><span title={title}>{title}</span><button type="button" onClick={onToggle} aria-label={fullscreen ? "退出全屏" : "全屏"} title={fullscreen ? "退出全屏" : "全屏"}>{fullscreen ? <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.5 1v4.5H2M9.5 1v4.5H14M6.5 15v-4.5H2M9.5 15v-4.5H14" /></svg> : <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 2H2v4M10 2h4v4M6 14H2v-4M10 14h4v-4" /></svg>}</button></div>;
}

function CsvPreview({ text }) {
  const rows = parseCsv(text);
  const headers = rows[0] || [];
  const body = rows.slice(1);
  return <div className="csv-preview"><div className="csv-preview-meta">CSV 表格预览 · {body.length} 行 · {headers.length} 列</div><div className="csv-preview-scroll"><table className="csv-preview-table"><thead><tr>{headers.map((header, index) => <th className={body.some((row) => isNumericDisplayValue(row[index], header)) ? "numeric-header" : ""} key={index}>{header || `列 ${index + 1}`}</th>)}</tr></thead><tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((header, columnIndex) => { const value = row[columnIndex] || ""; const numeric = isNumericDisplayValue(value, header); return <td className={numeric ? "numeric-cell" : ""} key={columnIndex}>{numeric ? formatDisplayValue(value, header) : value}</td>; })}</tr>)}</tbody></table></div></div>;
}

function SpreadsheetPreview({ sheets }) {
  const [active, setActive] = useState(0);
  const current = sheets[active] || { name: "Sheet1", rows: [] };
  const headers = current.rows[0] || [];
  const body = current.rows.slice(1);
  return <div className="csv-preview"><div className="sheet-tabs">{sheets.map((sheet, index) => <button type="button" className={index === active ? "sheet-tab active" : "sheet-tab"} key={sheet.name} onClick={() => setActive(index)}>{sheet.name}</button>)}</div><div className="csv-preview-meta">Excel 表格预览 · {body.length} 行 · {headers.length} 列</div><div className="csv-preview-scroll"><table className="csv-preview-table"><thead><tr>{headers.map((header, index) => <th className={body.some((row) => isNumericDisplayValue(row[index], header)) ? "numeric-header" : ""} key={index}>{String(header || `列 ${index + 1}`)}</th>)}</tr></thead><tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((header, columnIndex) => { const value = String(row[columnIndex] ?? ""); const numeric = isNumericDisplayValue(value, header); return <td className={numeric ? "numeric-cell" : ""} key={columnIndex}>{numeric ? formatDisplayValue(value, header) : value}</td>; })}</tr>)}</tbody></table></div></div>;
}

function formatFileSize(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0B";
  if (bytes < 1000) return `${bytes}B`;
  const units = ["K", "M", "G"]; let size = bytes; let index = -1;
  while (size >= 1000 && index < units.length - 1) { size /= 1000; index += 1; }
  return `${size.toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1")}${units[index]}`;
}

const MISSION_LABELS = {
  repositoryId: "本体库 ID", taskCode: "任务编码", taskName: "任务名称", modelName: "模型名称",
  taskType: "任务类型", prompt: "提示词", parseElements: "解析要素", expectedFiles: "期望输出文件",
  outputPrefix: "输出路径前缀", sourceMode: "来源模式", checkTypes: "校验类型", dbType: "数据库类型",
  host: "主机", port: "端口", database: "数据库", username: "用户名", password: "密码",
  sourceSchema: "Schema", selectedTables: "选中数据表", databaseSourceId: "数据源 ID",
  fileSourceId: "文件源 ID", fileType: "文件类型", objectKey: "对象存储 Key", items: "条目",
  mode: "模式", generateAlignmentReport: "生成对齐报告", generate_alignment_report: "生成对齐报告",
  autoMergeStrategy: "自动合并策略", auto_merge_strategy: "自动合并策略", alignmentStrategy: "对齐策略",
  mergeStrategy: "整合策略", conflictResolutionStrategy: "冲突处理策略", pendingConfirmationStrategy: "待确认策略",
  modelingPlan: "分层建模计划", identity: "任务身份", artifacts: "Artifact 清单",
  artifactType: "Artifact 类型", layer: "层级", requested: "是否请求", source: "来源",
  status: "状态", dependsOn: "依赖", outputs: "输出文件", key: "身份键",
  modelVersion: "模型版本", inputFingerprint: "输入指纹", requestedElements: "请求解析要素",
  executionOrder: "执行顺序", valid: "依赖校验通过", dependencyErrors: "依赖错误",
};
const MISSION_SECTION_LABELS = {
  database: "数据源", document: "文档", sourceModels: "来源模型", integrationStrategy: "整合策略",
  validationRules: "校验规则",
};
const missionLabel = (key) => MISSION_LABELS[key] || MISSION_SECTION_LABELS[key] || key;

function RecursiveInfo({ value, level = 0, field = "" }) {
  if (value === null || value === undefined || value === "") return null;
  if (Array.isArray(value)) return <div className="info-tags">{value.map((item, index) => <Tag key={index}>{typeof item === "object" ? $json(item) : String(item)}</Tag>)}</div>;
  if (typeof value === "object") return <div className="info-nested">{Object.entries(value).map(([key, item]) => <div className="info-row" key={`${level}-${key}`}><span className="info-key">{missionLabel(key)}</span><div className="info-value"><RecursiveInfo value={item} level={level + 1} field={key} /></div></div>)}</div>;
  if (field === "password") return <span>••••••••</span>;
  const numeric = isNumericDisplayValue(value, field);
  return <span className={numeric ? "numeric-value" : ""}>{numeric ? formatDisplayValue(value, field) : String(value)}</span>;
}

function MissionInfo({ open, context, loading, onClose }) {
  return (
    <Modal open={open} title="当前任务信息" footer={null} onCancel={onClose} width={680} destroyOnClose>
      {loading ? <Spin /> : context ? <div className="mission-info"><RecursiveInfo value={context} /></div> : <Empty description="暂未获取到任务信息" />}
    </Modal>
  );
}

function SettingsModal({ open, onClose, meta, model, onModel, params, onParams, provider, keyValue, setKeyValue, onSaveKey }) {
  const models = (meta?.models || []).map((item) => ({ value: item.id, label: `${item.label || item.id} · ${item.provider || ""}` }));
  return (
    <Modal open={open} title="大语言模型设置" footer={null} onCancel={onClose} width={560}>
      <div className="settings-section"><div className="settings-label">模型</div><Select showSearch value={model} options={models} onChange={onModel} /></div>
      <Divider />
      <div className="settings-section"><div className="settings-label">模型参数</div>
        <div className="settings-grid">
          <label>最大输出 token<InputNumber min={1} value={params.max_tokens} onChange={(value) => onParams({ max_tokens: value })} /></label>
          <label>温度<Slider min={0} max={2} step={0.1} value={params.temperature ?? 0} onChange={(value) => onParams({ temperature: value })} /></label>
          <label>扩展思考<Switch checked={Boolean(params.thinking)} onChange={(value) => onParams({ thinking: value })} /></label>
          <label>思考预算 token<InputNumber min={1024} step={512} value={params.thinking_budget} onChange={(value) => onParams({ thinking_budget: value })} /></label>
        </div>
      </div>
      <Divider />
      <div className="settings-section"><div className="settings-label">当前用户模型密钥 · {provider || "—"}</div>
        <Input.Password value={keyValue} onChange={(event) => setKeyValue(event.target.value)} placeholder="粘贴该模型对应的 API Key" addonAfter={<Button type="link" onClick={onSaveKey}>保存</Button>} />
      </div>
    </Modal>
  );
}

function ModelPicker({ model, models, onModel, onOpenSettings }) {
  const [open, setOpen] = useState(false);
  const content = <div className="model-picker">
    <div className="model-picker-list">{(models || []).map((item) => <button type="button" className={item.id === model ? "model-option active" : "model-option"} key={item.id} onClick={() => { onModel(item.id); setOpen(false); }}><span>{item.label || item.id}</span><small>{item.provider || ""}</small></button>)}</div>
    <Button type="link" className="model-params-link" onClick={() => { setOpen(false); onOpenSettings(); }}><ModelSettingsIcon /> 修改模型参数</Button>
  </div>;
  const modelText = String(model || "模型");
  return <Popover open={open} onOpenChange={setOpen} trigger="click" placement="topRight" content={content} title="选择大语言模型"><button type="button" className="model-hint" aria-label={`当前模型：${model || "未选择"}`} title={model || "未选择模型"}><span className="model-name"><ModelSettingsIcon /> {modelText.length > 15 ? `${modelText.slice(0, 15)}...` : modelText}</span></button></Popover>;
}

function Composer({ value, onChange, onSend, onAttach, pendingFiles, mission, busy, hasConversation, model, models, onModel, onOpenSettings, placeholder, projects, project, onProject, autoApprove, onToggleAutoApprove, showAutoApprove = false }) {
  const start = mission && !hasConversation && !value.trim();
  return (
    <div className="composer">
      <Input.TextArea value={value} onChange={(event) => onChange(event.target.value)} onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); onSend(); } }} autoSize={{ minRows: 1, maxRows: 8 }} placeholder={placeholder} disabled={busy} />
      {!!pendingFiles.length && <div className="pending-files">{pendingFiles.map((file) => <Tag key={file.name}>📎 {file.name}</Tag>)}</div>}
      <div className="composer-row">
        <Button type="text" onClick={onAttach} title="上传文件到项目"><UploadFileIcon /> <span>上传文件</span></Button>
        {showAutoApprove && <Button className="auto-approve-toggle" type={autoApprove ? "primary" : "default"} aria-pressed={autoApprove} title="切换自动确认" onClick={onToggleAutoApprove}>{autoApprove ? "自动确认：开" : "自动确认：关"}</Button>}
        {!mission && projects?.length > 0 && <Select size="small" value={project} options={projects.map((item) => ({ value: item.name, label: item.name }))} onChange={onProject} className="project-select" placeholder="选择项目" />}
        <ModelPicker model={model} models={models} onModel={onModel} onOpenSettings={onOpenSettings} />
        <Button type={start ? "primary" : "default"} className={start ? "start-button" : "send-button"} onClick={onSend} disabled={busy}>{start ? (mission?.taskType === "integration" ? "开始智能消歧与整合" : "开始智能建模") : <SendArrowIcon />}</Button>
      </div>
    </div>
  );
}

function FilePanel({ open, files, loading, selected, onSelect, onSelectGroup, onOpen, onDownload, onUploadToMinio, uploadingToMinio, uploadBlocked = false, onDrawOntology, drawingOntology = false, ontologyAvailable = false, onClose, onRefresh, mission, workspaceFolders = false, focusPath, platformStatus, resetKey }) {
  const defaultCollapsedDirs = () => new Set(["root", "input"]);
  const [collapsedDirs, setCollapsedDirs] = useState(defaultCollapsedDirs);
  const displayPath = (file) => String(file?.displayPath || file?.path || "").replaceAll("\\", "/");
  const displayDir = (file) => displayPath(file).split("/")[0] || "";
  const displaySubdir = (file) => {
    const parts = displayPath(file).split("/");
    return parts.length > 2 ? parts.slice(1, -1).join("/") : "";
  };
  const groups = useMemo(() => {
    const map = new Map();
    if (mission || workspaceFolders) {
      ["root", "input", "work", "output"].forEach((dir) => map.set(dir, new Map()));
    }
    files.forEach((file) => {
      const dir = displayDir(file);
      if (!map.has(dir)) map.set(dir, new Map());
      const subdir = displaySubdir(file);
      if (!map.get(dir).has(subdir)) map.get(dir).set(subdir, []);
      map.get(dir).get(subdir).push(file);
    });
    const order = ["root", "input", "work", "output"];
    return [...map.entries()].sort(([a], [b]) => (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 99 : order.indexOf(b)));
  }, [files, mission]);
  const toggleDir = (dir) => setCollapsedDirs((current) => {
    const next = new Set(current);
    if (next.has(dir)) next.delete(dir); else next.add(dir);
    return next;
  });
  const GROUP_LABELS = { root: "项目公共区", input: "输入", work: "工作", output: "输出" };
  const groupLabel = (dir) => <><FolderPanelIcon /> {dir ? `${GROUP_LABELS[dir] || dir}/` : "项目公共区/"}</>;
  const renderFiles = (items) => items.map((file) => <div className={`file-row ${focusPath === file.path ? "file-row-focused" : ""}`} key={file.path}><input type="checkbox" checked={selected.includes(file.path)} onChange={() => onSelect(file.path)} /><button onClick={() => onOpen(file.path)}>{displayPath(file).split("/").pop()}</button><small>{formatFileSize(file.size)}</small></div>);
  const renderSubgroup = (dir, subdir, items) => {
    const key = `${dir}/${subdir}`;
    const collapsed = collapsedDirs.has(key);
    const paths = items.map((file) => file.path);
    const allSelected = paths.length > 0 && paths.every((path) => selected.includes(path));
    const partiallySelected = !allSelected && paths.some((path) => selected.includes(path));
    const label = subdir.split("/").pop() || dir;
    return <div className="file-subgroup" key={key}>
      <div className="file-subgroup-title"><input className="folder-select" type="checkbox" checked={allSelected} ref={(node) => { if (node) node.indeterminate = partiallySelected; }} onChange={() => onSelectGroup(paths)} aria-label={`选择 ${label} 下全部文件`} /><button type="button" className="file-group-toggle" onClick={() => toggleDir(key)} aria-expanded={!collapsed}><FileGroupChevronIcon collapsed={collapsed} /><FolderPanelIcon /> {label}/</button><span>({items.length})</span></div>
      {!collapsed && renderFiles(items)}
    </div>;
  };
  useEffect(() => {
    if (!open) return;
    // root/input are grouped reference areas; work/output remain visible.
    setCollapsedDirs(defaultCollapsedDirs());
  }, [open, resetKey]);
  if (!open) return null;
  return <aside className="file-panel">
    <div className="panel-head"><strong>项目文件</strong><Button size="small" aria-label="刷新文件" title="刷新文件" onClick={onRefresh}><RefreshFilePanelIcon /></Button><Button size="small" aria-label="折叠文件面板" title="折叠文件面板" onClick={onClose}><CollapseFilePanelIcon /></Button></div>
    <div className="file-actions"><Button size="small" icon={<DownloadSelectedIcon />} disabled={!selected.length} onClick={() => onDownload(selected)}>下载所选</Button>{mission && <Tooltip title={uploadBlocked ? "任务执行或状态变更期间不能上传" : platformStatus === "COMPLETED" ? "上传新结果将恢复任务为执行中" : "上传选中的任务结果"}><Button size="small" type="primary" icon={<UploadMinioIcon />} loading={uploadingToMinio} disabled={!selected.length || uploadingToMinio || uploadBlocked} onClick={onUploadToMinio}>上传到 MinIO</Button></Tooltip>}{(mission || workspaceFolders) && <Tooltip title={ontologyAvailable ? "根据当前任务已有产物生成本体树图" : "缺少逻辑实体 CSV，不能进行本体可视化"}><Button size="small" loading={drawingOntology} disabled={!ontologyAvailable || drawingOntology} onClick={onDrawOntology}>本体可视化</Button></Tooltip>}{mission && platformStatus === "COMPLETED" && <span className="panel-note">上传新结果将恢复执行</span>}</div>
    {loading ? <Spin /> : !files.length && !mission && !workspaceFolders ? <Empty description="暂无文件" /> : <div className="file-list">{groups.map(([dir, subgroups]) => {
      const collapsed = collapsedDirs.has(dir);
      const items = [...subgroups.values()].flat();
      const paths = items.map((file) => file.path);
      const allSelected = paths.length > 0 && paths.every((path) => selected.includes(path));
      const partiallySelected = !allSelected && paths.some((path) => selected.includes(path));
      return <div className="file-group" key={dir || "root"}>
        <div className="file-group-title">
          <input className="folder-select" type="checkbox" checked={allSelected} ref={(node) => { if (node) node.indeterminate = partiallySelected; }} onChange={() => onSelectGroup(paths)} aria-label={`选择 ${dir || "项目根目录"} 下全部文件`} />
          <button type="button" className="file-group-toggle" onClick={() => toggleDir(dir)} aria-expanded={!collapsed}><FileGroupChevronIcon collapsed={collapsed} /> {groupLabel(dir)}</button>
          <span>({items.length})</span>
        </div>
        {!collapsed && (items.length ? [...subgroups.entries()].map(([subdir, subitems]) => subdir ? renderSubgroup(dir, subdir, subitems) : renderFiles(subitems)) : <div className="file-group-empty">暂无文件</div>)}
      </div>;
    })}</div>}
  </aside>;
}

function App() {
  const [meta, setMeta] = useState({ models: [], projects: [], params: {} });
  const [tasks, setTasks] = useState([]);
  const [active, setActive] = useState(null);
  const [events, setEvents] = useState([]);
  const [view, setView] = useState(MISSION ? "home" : "home");
  const [text, setText] = useState("");
  const [pendingFiles, setPendingFiles] = useState([]);
  const [files, setFiles] = useState([]);
  const [filesTaskId, setFilesTaskId] = useState("");
  const [filesOpen, setFilesOpen] = useState(true);
  const [filesLoading, setFilesLoading] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [focusFile, setFocusFile] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewFullscreen, setPreviewFullscreen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [minioUploading, setMinioUploading] = useState(false);
  const [uploadIssues, setUploadIssues] = useState(null);
  const [ontologyDrawing, setOntologyDrawing] = useState(false);
  const [platformActionLoading, setPlatformActionLoading] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [missionInfoOpen, setMissionInfoOpen] = useState(false);
  const [missionContext, setMissionContext] = useState(null);
  const [missionLoading, setMissionLoading] = useState(Boolean(MISSION));
  const [keyValue, setKeyValue] = useState("");
  const [selectedProject, setSelectedProject] = useState("");
  const [autoApprove, setAutoApprove] = useState(() => localStorage.getItem("oc_auto_approve") === "1");
  const autoApproveRef = useRef(autoApprove);
  const approvalInFlightRef = useRef(new Set());
  const activeTaskIdRef = useRef("");
  // Busy is request-scoped: an old request's `finally` must not clear the
  // busy flag of a newer request started after a session switch/retry.
  const busyRequestRef = useRef(0);
  const logWindowRef = useRef(new Map());
  const olderLogLoadingRef = useRef(new Set());
  // Task-level event poll lock (per task id) so session A's polling can never
  // block or release session B's first poll after a quick switch.
  const taskPollInFlightRef = useRef(new Set());
  const previewImageUrlRef = useRef("");
  const previewRequestRef = useRef(0);
  const filesRequestRef = useRef(0);
  const [messageApi, contextHolder] = message.useMessage();
  const fileInput = useRef(null);
  const feedRef = useRef(null);
  const feedPinnedRef = useRef(true);
  const feedScrollEpochRef = useRef(0);
  const feedPrependAnchorRef = useRef(null);

  const model = meta.model || "";
  const params = meta.params || { temperature: null, max_tokens: null, thinking: false, thinking_budget: 8000 };
  const provider = meta.provider || "";
  useEffect(() => {
    setOntologyDrawing(false);
    setPreviewFullscreen(false);
  }, [active?.id]);
  const currentMission = missionIdentity(active);
  const isMissionTask = Boolean(currentMission);
  const hasConversation = Boolean(active?.hasConversation || events.some((event) => ["user", "assistant"].includes(event.type) && String(event.text || "").trim()));
  const placeholder = view === "task" ? "继续对这个任务下指令…" : MISSION ? "点击开始任务，或者描述一个任务" : "描述一个任务，例如：帮我分析这个项目…";

  const loadMeta = async () => { const result = await api("/api/meta"); if (!result.error) setMeta(result); else messageApi.error(result.error); };
  const loadTasks = async () => { const result = await api(`/api/tasks${MISSION ? `?repositoryId=${encodeURIComponent(MISSION.repositoryId)}&taskCode=${encodeURIComponent(MISSION.taskCode)}` : ""}`); if (!result.error) { setTasks(result.tasks || []); return result.tasks || []; } return []; };
  const loadMission = async (mission = MISSION) => {
    if (!mission?.repositoryId || !mission?.taskCode) return;
    setMissionLoading(true);
    const query = new URLSearchParams({ repositoryId: mission.repositoryId, taskCode: mission.taskCode, ...(mission.taskType ? { taskType: mission.taskType } : {}) });
    const result = await api(`/api/mission/task?${query}`);
    // 任务信息只是侧栏的辅助内容；上游任务已完成、删除或暂不可查时，
    // 保持空态即可，不能在打开历史对话时弹出错误打断用户。
    if (!result.error) {
      setMissionContext(result.task);
    } else {
      setMissionContext(null);
    }
    setMissionLoading(false);
    return result.error ? null : result;
  };

  useLayoutEffect(() => {
    const anchor = feedPrependAnchorRef.current;
    if (!anchor || view !== "task" || !feedRef.current) return;
    feedPrependAnchorRef.current = null;
    const feed = feedRef.current;
    // Older events are inserted above the current viewport. Compensate for
    // the added height before paint so background history replay is invisible
    // to the user instead of moving the conversation under their cursor.
    if (anchor.epoch === feedScrollEpochRef.current) {
      feed.scrollTop = Math.max(0, anchor.top + feed.scrollHeight - anchor.height);
    }
  }, [events, view, filesOpen]);
  useEffect(() => {
    // The input shell and task list should become usable together. Mission
    // metadata and task summaries are independent reads; only opening a
    // conversation waits for the selected task detail.
    const bootstrap = async () => {
      await loadMeta();
      await Promise.all([
        MISSION ? loadMission() : Promise.resolve(),
        loadTasks(),
      ]);
    };
    void bootstrap();
  }, []);
  useEffect(() => { if (!selectedProject && meta.projects?.length) setSelectedProject(meta.projects[0].name); }, [meta.projects, selectedProject]);
  useEffect(() => {
    if (!MISSION || !tasks.length || active) return;
    const saved = localStorage.getItem(`oc_active_task_${MISSION.repositoryId}_${MISSION.taskCode}`);
    const task = tasks.find((item) => item.id === saved) || tasks[0];
    if (task) openTask(task);
  }, [tasks, active]);
  useEffect(() => { if (active && filesOpen) loadFiles(); }, [active, filesOpen]);
  useEffect(() => {
    activeTaskIdRef.current = active?.id || "";
    setFiles([]);
    setFilesTaskId("");
    setSelectedFiles([]);
    setFocusFile("");
    closePreview();
  }, [active?.id]);
  useEffect(() => {
    if (view !== "task" || !feedRef.current) return undefined;
    const frame = window.requestAnimationFrame(() => {
      const feed = feedRef.current;
      if (feed && feedPinnedRef.current) feed.scrollTop = feed.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [events, busy, view]);
  useEffect(() => () => {
    if (previewImageUrlRef.current) URL.revokeObjectURL(previewImageUrlRef.current);
  }, []);

  const handleFeedScroll = () => {
    const feed = feedRef.current;
    if (!feed) return;
    feedScrollEpochRef.current += 1;
    // Follow the live stream only while the user is already at the bottom.
    // Once they scroll up, incoming thought-chain events must not pull them
    // back down; returning to the bottom resumes live following automatically.
    feedPinnedRef.current = feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 56;
  };

  const loadOlderTaskEvents = async (task, generation = 0, maxViewportPages = Infinity) => {
    if (!task?.id || olderLogLoadingRef.current.has(task.id)) return false;
    const initialWindow = logWindowRef.current.get(task.id);
    if (!initialWindow || initialWindow.start <= 0) return false;
    olderLogLoadingRef.current.add(task.id);
    let loadedHeight = 0;
    try {
      while (!generation || generation === logWindowRef.current.get(task.id)?.generation) {
        const window = logWindowRef.current.get(task.id);
        if (!window || window.start <= 0) break;
        const taskMission = missionIdentity(task);
        const identity = taskMission
          ? `&repositoryId=${encodeURIComponent(taskMission.repositoryId)}&taskCode=${encodeURIComponent(taskMission.taskCode)}`
          : "";
        const result = await api(`/api/tasks/${task.id}?before=${window.start}&limit=160${identity}`);
        if (generation && generation !== logWindowRef.current.get(task.id)?.generation) break;
        if (result.error) break;
        const older = normalizeEvents(result);
        const nextStart = Number(result.logStart ?? Math.max(0, window.start - older.length));
        logWindowRef.current.set(task.id, { ...window, start: nextStart });
        if (older.length) {
          const feed = feedRef.current;
          const beforeHeight = feed?.scrollHeight || 0;
          if (feed) {
            feedPrependAnchorRef.current = {
              top: feed.scrollTop,
              height: feed.scrollHeight,
              epoch: feedScrollEpochRef.current,
            };
          }
          setEvents((current) => activeTaskIdRef.current === task.id
            ? mergeEvents(older, current, `task:${task.id}`)
            : current);
          await waitForNextPaint();
          const renderedFeed = feedRef.current;
          if (renderedFeed && beforeHeight) {
            loadedHeight += Math.max(0, renderedFeed.scrollHeight - beforeHeight);
            if (renderedFeed.clientHeight > 0
                && loadedHeight >= renderedFeed.clientHeight * maxViewportPages) {
              return true;
            }
          }
        }
        if (!older.length || nextStart >= window.start) break;
        await new Promise((resolve) => globalThis.setTimeout(resolve, 0));
      }
    } finally {
      olderLogLoadingRef.current.delete(task.id);
    }
    return Boolean(logWindowRef.current.get(task.id)?.start > 0);
  };

  const pollTaskEvents = async (taskId) => {
    if (!taskId || activeTaskIdRef.current !== taskId || taskPollInFlightRef.current.has(taskId)) return;
    const window = logWindowRef.current.get(taskId);
    if (!window) return;
    taskPollInFlightRef.current.add(taskId);
    try {
      const cursor = Number(window.cursor ?? window.total ?? 0);
      const taskMission = missionIdentity(active || { id: taskId });
      const identity = taskMission
        ? `&repositoryId=${encodeURIComponent(taskMission.repositoryId)}&taskCode=${encodeURIComponent(taskMission.taskCode)}`
        : "";
      const result = await api(`/api/tasks/${taskId}/events?since=${cursor}${identity}`);
      if (activeTaskIdRef.current !== taskId || result.error) return;
      let liveModel = result.model;
      // Older 47313 processes do not include the task model in event-window
      // responses. Fall back to the existing meta endpoint so a hot-published
      // frontend still reflects an API-side model switch without waiting for
      // the backend process to restart.
      if (!liveModel) {
        const liveMeta = await api("/api/meta");
        if (!liveMeta.error) liveModel = liveMeta.model;
      }
      if (liveModel) {
        setMeta((previous) => ({
          ...previous,
          model: liveModel,
          provider: (previous.models || []).find((item) => item.id === liveModel)?.provider || previous.provider,
        }));
      }
      const delta = normalizeEvents(result);
      if (delta.length) {
        setEvents((current) => activeTaskIdRef.current === taskId
          ? mergeEvents(current, delta, `task:${taskId}`)
          : current);
      }
      const currentWindow = logWindowRef.current.get(taskId);
      const next = nextCursor(result, delta);
      logWindowRef.current.set(taskId, {
        ...(currentWindow || window),
        total: Number(result.eventTotal ?? window.total ?? next),
        cursor: next,
      });
    } finally {
      taskPollInFlightRef.current.delete(taskId);
    }
  };

  const openTask = async (task) => {
    const taskMission = missionIdentity(task);
    const identityQuery = taskMission ? `&repositoryId=${encodeURIComponent(taskMission.repositoryId)}&taskCode=${encodeURIComponent(taskMission.taskCode)}` : "";
    const detailQuery = `?tail=1&limit=80${identityQuery}`;
    const result = await api(`/api/tasks/${task.id}${detailQuery}`);
    if (result.error) { messageApi.error(`打开历史会话失败：${result.error}`); return; }
    const current = { ...result };
    if (current.model) {
      setMeta((previous) => ({
        ...previous,
        model: current.model,
        provider: (previous.models || []).find((item) => item.id === current.model)?.provider || previous.provider,
      }));
    }
    if (taskMission && !MISSION) {
      const missionResult = await loadMission({ ...taskMission, taskType: current.taskType || task.taskType || "" });
      if (missionResult?.platformStatus) current.platformStatus = missionResult.platformStatus;
    }
    feedPinnedRef.current = true;
    const recentEvents = normalizeEvents(current);
    const logStart = Number(result.logStart ?? 0);
    const logTotal = Number(result.logTotal ?? recentEvents.length);
    // The tail window ends at the journal end, so the next unread cursor is
    // the server-absolute logTotal; never derive it from client node counts.
    logWindowRef.current.set(current.id, { start: logStart, total: logTotal, cursor: logTotal, generation: Date.now() });
    activeTaskIdRef.current = current.id;
    setFiles([]);
    setFilesTaskId("");
    setActive(current);
    setEvents(mergeEvents([], recentEvents, `task:${current.id}`));
    setView("task"); setText("");
    if (MISSION) localStorage.setItem(`oc_active_task_${MISSION.repositoryId}_${MISSION.taskCode}`, current.id);
    // 页面刷新或重新打开历史会话时，审批请求可能已经在服务端挂起，
    // 不会再次经过 SSE；自动确认开启时要主动恢复这类请求。
    if (autoApproveRef.current) {
      const pending = normalizeEvents(current).find((event) => event.type === "approval_request");
      if (pending) void approve(pending.id, true, current);
    }
    // The newest thought-chain is rendered first. Older history and the full
    // workspace listing are deliberately filled after that first viewport is
    // usable, so a large replay log or file tree cannot block task input.
    scheduleIdle(async () => {
      // Stop after roughly ten viewport heights so the user gets meaningful
      // recent history first; files are loaded next, then the old journal
      // resumes in the background.
      const historyHasMore = await loadOlderTaskEvents(current, 0, 10);
      const loadedFiles = await loadFiles(current);
      if (activeTaskIdRef.current === current.id) {
        // The file panel is open by default; reopening a session with
        // generated results only ever opens it (never auto-closes a panel the
        // user kept open), while loading contents must not block the
        // conversation.
        const shouldOpenFiles = hasMissionOutputFiles(loadedFiles);
        const feed = feedRef.current;
        if (feed && shouldOpenFiles !== filesOpen) {
          feedPrependAnchorRef.current = {
            top: feed.scrollTop,
            height: feed.scrollHeight,
            epoch: feedScrollEpochRef.current,
          };
        }
        if (shouldOpenFiles) setFilesOpen(true);
      }
      if (historyHasMore) await loadOlderTaskEvents(current);
    });
  };

  useEffect(() => {
    // Poll the active task's journal with the absolute since-cursor while a
    // turn is active but no SSE stream is open (e.g. after refresh), so a
    // dropped stream cannot stall the visible progress.  While `busy` is true
    // the live SSE already carries streamed `text` tokens, which are not
    // persisted as seq'd events; merging the journal's `assistant` events on
    // top of them would duplicate the text, so polling is gated on `!busy`.
    // The idempotent merge keeps every other path exactly once.
    if (!active?.id || view !== "task" || busy) return undefined;
    if (!["working", "queued", "blocked", "error"].includes(active.status)) return undefined;
    const taskId = active.id;
    const timer = window.setInterval(() => { void pollTaskEvents(taskId); }, 2000);
    return () => window.clearInterval(timer);
  }, [active?.id, active?.status, view, busy]);

  const loadFiles = async (task = active) => {
    const taskId = task?.id || "";
    const requestId = ++filesRequestRef.current;
    setFilesLoading(true);
    const project = task?.project || "";
    const query = `/api/files?project=${encodeURIComponent(project)}${missionQuery({ taskId: task?.id || "" }, task)}`;
    const result = await api(query);
    if (!result.error) {
      const loadedFiles = (result.files || []).filter((file) => !String(file.path).includes("-sheets/") && !String(file.path).endsWith("manifest.json"));
      if (activeTaskIdRef.current !== taskId || filesRequestRef.current !== requestId) return [];
      setFiles(loadedFiles);
      setFilesTaskId(taskId);
      setFilesLoading(false);
      return loadedFiles;
    }
    if (filesRequestRef.current === requestId) setFilesLoading(false);
    return [];
  };

  const createTask = async () => {
    const result = await api("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: MISSION ? "" : selectedProject || meta.projects?.[0]?.name || "", repositoryId: MISSION?.repositoryId || "", taskCode: MISSION?.taskCode || "", taskType: MISSION?.taskType || "" }) });
    if (result.error) { messageApi.error(result.error); return null; }
    feedPinnedRef.current = true;
    setTasks((previous) => [result, ...previous.filter((task) => task.id !== result.id)]); setActive(result); setEvents([]); setView("task"); return result;
  };

  const reuseMissionTask = async () => {
    const task = active || tasks[0];
    setHistoryOpen(true);
    if (!task) {
      messageApi.info("当前任务还没有本地会话，请先开始任务");
      return null;
    }
    await openTask(task);
    messageApi.success("已复用当前任务，不会新建会话");
    return task;
  };

  const handleNewSession = async () => {
    if (MISSION) {
      await reuseMissionTask();
      return;
    }
    setActive(null); setEvents([]); setText(""); setView("home");
    await createTask();
  };

  const appendEvent = (event) => setEvents((previous) => {
    const stamped = stampEvent(event);
    const taskId = activeTaskIdRef.current || active?.id || "";
    return appendStreamEvent(previous, stamped, `task:${taskId}`);
  });

  const approve = async (id, approved, taskOverride = null) => {
    const task = taskOverride || active;
    if (!task || !id) return false;
    const key = `${task.id}:${id}`;
    if (approvalInFlightRef.current.has(key)) return false;
    approvalInFlightRef.current.add(key);
    try {
      const result = await api(`/api/tasks/${task.id}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, approved }) });
      if (result.error) {
        // 自动恢复历史审批时，服务端可能已处理同一个请求；这不是用户需要
        // 处理的异常。其他审批失败（鉴权、网络等）仍然保留明确提示。
        if (!isExpiredApprovalError(result.error)) messageApi.error(result.error);
        return false;
      }
      appendEvent({ type: "approval_result", id, approved });
      return true;
    } finally {
      approvalInFlightRef.current.delete(key);
    }
  };

  const uploadFiles = async (task, selected) => {
    const names = [];
    const taskMission = missionIdentity(task);
    for (const file of selected) {
      const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1] || ""); reader.onerror = reject; reader.readAsDataURL(file); });
      const result = await api("/api/upload", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: task.project, name: file.name, data, ...(taskMission ? { repositoryId: taskMission.repositoryId, taskCode: taskMission.taskCode, taskId: task.id } : {}) }) });
      if (result.error) messageApi.error(`${file.name}: ${result.error}`); else names.push(file.name);
    }
    setPendingFiles([]); return names;
  };

  const sendToTask = async (task, content, displayMessage = content, startTask = false, intent = "auto") => {
    // An explicit new request is a user action that should start at the latest
    // message even if the previous turn was left scrolled up.
    feedPinnedRef.current = true;
    const taskId = task.id;
    const requestId = (busyRequestRef.current = busyRequestRef.current + 1);
    // Optimistic bubble carries a clientMessageId so the server-persisted user
    // event (echoed back on the stream with the same id) replaces it instead
    // of duplicating it on refresh.
    const clientMessageId = `cm-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    setBusy(true); appendEvent({ type: "user", text: displayMessage, clientMessageId });
    const finishBusy = () => { if (busyRequestRef.current === requestId) setBusy(false); };
    let response;
    try {
      response = await fetch(`/api/tasks/${taskId}/send`, { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ message: content, displayMessage, startTask, intent, clientMessageId }) });
    } catch (error) { if (busyRequestRef.current === requestId) appendEvent({ type: "error", error: error.message }); finishBusy(); return; }
    if (!response.ok || !response.body) {
      let payload = null;
      try { payload = await response.json(); } catch { /* non-JSON error body */ }
      if (busyRequestRef.current === requestId) {
        if (payload?.code === "ACTIVE_RUN_EXISTS") {
          // Another execution already owns this task: drop the optimistic
          // bubble, keep the existing execution's progress and resume syncing
          // from the persisted cursor instead of showing a generic failure.
          setEvents((current) => current.filter((event) => event.clientMessageId !== clientMessageId));
          messageApi.info("任务正在执行，已恢复当前进度");
          void loadTasks();
          void pollTaskEvents(taskId);
        } else {
          appendEvent({ type: "error", error: payload?.error || `请求失败(${response.status})` });
        }
      }
      finishBusy();
      return;
    }
    // P1/P2: the server accepts the execution with HTTP 202 and runs it on a
    // background worker pool.  The response carries the queue position and
    // the journal cursor; progress is delivered through /events polling, so
    // the browser never blocks an HTTP thread and a refresh cannot lose the
    // running turn.  The 202 body may contain a stale historical run.error
    // from a previous attempt; it is a domain field, not an API failure.
    if (response.status === 202) {
      let payload = null;
      try { payload = await response.json(); } catch { /* non-JSON body */ }
      finishBusy();
      if (activeTaskIdRef.current !== taskId) return;
      if (payload) {
        setActive((previous) => previous && previous.id === taskId
          ? { ...previous, status: payload.status || previous.status, queuePosition: payload.queuePosition || 0 }
          : previous);
        if (!logWindowRef.current.get(taskId)) {
          const cursor = Number(payload.nextCursor ?? payload.eventTotal ?? 0);
          logWindowRef.current.set(taskId, { start: 0, total: cursor, cursor, generation: Date.now() });
        }
        if (payload.status === "queued" && payload.queuePosition) {
          messageApi.info(`任务已排队（第 ${payload.queuePosition} 位），将在空闲后自动执行`);
        }
      }
      void loadTasks();
      if (logWindowRef.current.get(taskId)) void pollTaskEvents(taskId);
      return;
    }
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    const consume = (chunk) => {
      if (activeTaskIdRef.current !== taskId) return;
      buffer += decoder.decode(chunk, { stream: true });
      const packets = buffer.split("\n\n"); buffer = packets.pop() || "";
      packets.forEach((packet) => {
        const line = packet.split("\n").find((item) => item.startsWith("data: "));
        if (!line) return;
        try {
          const event = JSON.parse(line.slice(6));
          appendEvent(event);
          if (event.type === "approval_request" && autoApproveRef.current) approve(event.id, true, task);
          if (event.type === "done") finishBusy();
        } catch { /* ignore malformed SSE packet */ }
      });
    };
    try {
      while (true) { const { value, done } = await reader.read(); if (done) break; consume(value); }
      if (buffer) consume(new Uint8Array());
    } catch (error) {
      if (activeTaskIdRef.current === taskId && busyRequestRef.current === requestId) appendEvent({ type: "error", error: error.message });
    }
    finishBusy();
    const refreshedTasks = await loadTasks();
    const refreshed = refreshedTasks.find((item) => item.id === task.id);
    if (refreshed && activeTaskIdRef.current === taskId) setActive((previous) => previous && previous.id === refreshed.id ? { ...previous, ...refreshed } : previous);
    await loadFiles(task);
  };

  const send = async () => {
    if (busy) return;
    let task = active;
    const start = MISSION && !hasConversation && !text.trim();
    const userText = text.trim();
    if (!userText && !start) return;
    if (!task) task = await createTask();
    if (!task) return;
    const names = pendingFiles.length ? await uploadFiles(task, pendingFiles) : [];
    const messageText = start ? "请直接开始执行当前任务\n不需要等待我补充提示词。严格按照当前 execution-context 和系统规则完成全部工作。" : `${userText}${names.length ? `\n\n[用户上传了文件: ${names.join(", ")}]` : ""}`;
    const display = start ? "请直接开始执行当前任务" : userText;
    const intent = start ? "execute" : task.platformStatus === "COMPLETED" ? "chat" : "auto";
    setText(""); await sendToTask(task, messageText, display, start, intent);
  };

  const onAttach = () => {
    if (active?.platformStatus === "COMPLETED") {
      messageApi.info("任务已完成，请先点击“修改”再上传新的输入文件");
      return;
    }
    if (busy || active?.status === "working" || active?.status === "queued" || platformActionLoading) {
      messageApi.info("任务执行或状态变更期间不能修改输入文件");
      return;
    }
    fileInput.current?.click();
  };
  const onFilesSelected = (event) => { setPendingFiles(Array.from(event.target.files || [])); event.target.value = ""; };
  const onParams = async (patch) => { const result = await api("/api/params", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) }); if (result.error) messageApi.error(result.error); else setMeta((previous) => ({ ...previous, params: result })); };
  const onModel = async (value) => { const result = await api("/api/model", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: value }) }); if (result.error) messageApi.error(result.error); else setMeta((previous) => ({ ...previous, model: result.model, provider: (previous.models || []).find((item) => item.id === result.model)?.provider || previous.provider })); };
  const onSaveKey = async () => { const result = await api("/api/apikey", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider, key: keyValue }) }); if (result.error) messageApi.error(result.error); else messageApi.success("模型密钥已保存"); };

  const fileUrl = (path, task = active) => { const project = task?.project || ""; return `/p/${encodeURIComponent(project)}/${path.split("/").map(encodeURIComponent).join("/")}${missionSearch({ taskId: task?.id || "" }, task)}`; };
  const ontologyFiles = useMemo(() => filesTaskId === active?.id ? selectOntologyArtifacts(files, "output/") : null, [files, filesTaskId, active?.id]);
  const showPreview = (next) => {
    if (previewImageUrlRef.current) URL.revokeObjectURL(previewImageUrlRef.current);
    previewImageUrlRef.current = next?.image || "";
    setPreview(next);
  };
  const closePreview = () => {
    previewRequestRef.current += 1;
    showPreview(null);
  };
  const openFile = async (path) => {
    const requestId = ++previewRequestRef.current;
    setFilesOpen(true); setFocusFile(path);
    try {
      const response = await fetch(fileUrl(path), { credentials: "same-origin" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const type = response.headers.get("content-type") || "";
      if (type.startsWith("image/")) {
        const blob = await response.blob();
        if (requestId !== previewRequestRef.current) return;
        showPreview({ path, image: URL.createObjectURL(blob) });
      } else if (/\.(xlsx?|xlsm)$/i.test(path)) {
        const [buffer, XLSX] = await Promise.all([response.arrayBuffer(), import("xlsx")]);
        if (requestId !== previewRequestRef.current) return;
        const workbook = XLSX.read(buffer, { type: "array", cellDates: true });
        const sheets = workbook.SheetNames.map((name) => ({ name, rows: XLSX.utils.sheet_to_json(workbook.Sheets[name], { header: 1, defval: "", raw: false }) }));
        showPreview({ path, xlsx: true, sheets });
      } else {
        const content = await response.text();
        if (requestId !== previewRequestRef.current) return;
        showPreview({ path, text: content, csv: /\.csv$/i.test(path) || type.includes("text/csv") });
      }
    } catch (error) {
      if (requestId === previewRequestRef.current) messageApi.error(`打开文件失败: ${error.message}`);
    }
  };
  const drawOntology = async () => {
    const task = active;
    const taskId = task?.id || "";
    if (!ontologyFiles) {
      messageApi.warning("缺少逻辑实体 CSV，不能进行本体可视化");
      return;
    }
    setOntologyDrawing(true);
    try {
      const artifacts = [...ontologyFiles.entries()];
      const responses = await Promise.all(artifacts.map(([, artifact]) => fetch(fileUrl(artifact.path, task), { credentials: "same-origin" })));
      const failedIndex = responses.findIndex((response) => !response.ok);
      if (failedIndex >= 0) throw new Error(`${artifacts[failedIndex][1].name} 读取失败（HTTP ${responses[failedIndex].status}）`);
      const texts = await Promise.all(responses.map((response) => response.text()));
      const records = new Map(artifacts.map(([layer], index) => [layer, csvRecords(texts[index])]));
      const graph = buildOntologyGraph(records);
      if (!graph.availability.logicalEntity) throw new Error("逻辑实体产物中没有可展示的数据");
      if (activeTaskIdRef.current !== taskId) return;
      showPreview({ path: "本体可视化", ontologyGraph: graph });
    } catch (error) {
      messageApi.error(`本体可视化失败：${error.message}`);
    } finally {
      setOntologyDrawing(false);
    }
  };
  const download = () => { if (!selectedFiles.length) return; const project = active?.project || ""; const query = new URLSearchParams({ project }); selectedFiles.forEach((path) => query.append("path", path)); const taskMission = missionIdentity(active); if (taskMission) { query.set("repositoryId", taskMission.repositoryId); query.set("taskCode", taskMission.taskCode); query.set("taskId", active?.id || ""); } window.open(`/api/download?${query}`, "_blank"); };
  const uploadToMinio = async () => {
    const taskMission = missionIdentity(active);
    if (!taskMission || !active || !selectedFiles.length) return;
    setMinioUploading(true);
    setUploadIssues(null);
    try {
      const result = await api("/api/minio/upload", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: active.project, paths: selectedFiles, taskCode: taskMission.taskCode, repositoryId: taskMission.repositoryId, taskId: active.id, taskType: MISSION?.taskType || active.taskType || "" }) });
      const failed = (result.results || []).filter((item) => !item.ok);
      // 顶层 error 存在时也必须展示 results 中的逐文件原因：可能是部分文件
      // 校验失败（uploaded>0）或全部失败（顶层 422）。先按文件逐条展示，
      // 顶层 error 只作为补充提示，避免把“格式校验失败”误报成网络/存储错误。
      if (failed.length) {
        setUploadIssues(failed.map((item) => ({
          name: item.name, ok: false, stage: item.stage || "", code: item.code || "",
          error: item.error || "未知错误",
        })));
      } else {
        setUploadIssues(null);
      }
      if (result.uploaded) messageApi.success(`已上传 ${result.uploaded}/${result.total || selectedFiles.length} 个文件到 MinIO`);
      else if (failed.length) messageApi.warning(`没有可上传的合法文件（${failed.length} 个文件校验失败，详见明细）`);
      if (result.error && !failed.length) messageApi.error(result.error);
      if (result.task) {
        // 服务端是 completionReady 的单一权威来源：外层结果优先，内层
        // task.summary 不得用 true 覆盖外层的 false。
        const finalReady = typeof result.completionReady === "boolean"
          ? result.completionReady
          : result.task.completionReady;
        const mergedTask = { ...result.task, completionReady: finalReady };
        setActive(mergedTask);
        setTasks((previous) => previous.map((task) => task.id === mergedTask.id ? { ...task, ...mergedTask } : task));
      }
      if (result.completionReady === false) {
        // 仅系统性/文件完整性阻断才禁用完成；语义校验提示属于非阻断 warnings，
        // 由服务端 completionHint 与 completionWarnings 展示，不再要求“修复后”。
        messageApi.warning(result.completionHint || "结果已上传，但当前任务尚未满足完成条件，请检查上传明细。");
      } else if (result.completionHint) messageApi.info(result.completionHint);
      else if (result.callback?.skipped) messageApi.info(`尚未完成：${result.callback.error}`);
      else if (result.callback) messageApi.warning(`结果已上传，但完成回写失败：${result.callback.error || "未知错误"}`);
      await loadFiles(active);
    } finally {
      setMinioUploading(false);
    }
  };

  const performPlatformAction = async (completed) => {
    setPlatformActionLoading(true);
    try {
      const result = await api(`/api/tasks/${active.id}/platform-status`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: completed ? "edit" : "complete" }),
      });
      if (result.error) { messageApi.error(result.error); return; }
      if (result.task) {
        setActive(result.task);
        setTasks((previous) => previous.map((task) => task.id === result.task.id ? { ...task, ...result.task } : task));
      }
      messageApi.success(completed ? "已恢复为运行中，可继续修改并重新上传" : "已确认完成，结果已回写本体平台");
    } finally {
      setPlatformActionLoading(false);
    }
  };

  const changePlatformStatus = async () => {
    if (!currentMission || !active || platformActionLoading) return;
    const completed = active.platformStatus === "COMPLETED";
    if (!completed && (active.completionWarnings || []).length) {
      // 非阻断确认：语义校验提示不要求修复，用户确认后直接完成。
      Modal.confirm({
        title: "确认完成",
        content: "当前建模结果仍有校验提示（详见校验报告），是否继续完成？完成不会清除校验报告中的问题。",
        okText: "继续完成",
        cancelText: "取消",
        onOk: () => performPlatformAction(false),
      });
      return;
    }
    await performPlatformAction(completed);
  };

  const toggleAutoApprove = () => {
    const next = !autoApprove;
    autoApproveRef.current = next;
    setAutoApprove(next);
    localStorage.setItem("oc_auto_approve", next ? "1" : "0");
    messageApi.success(next ? "已开启自动确认" : "已关闭自动确认");
    if (next) {
      const pending = events.find((event) => event.type === "approval_request");
      if (pending) void approve(pending.id, true, active);
    }
  };

  const sidebarTasks = tasks.filter((task) => !MISSION || (task.repositoryId === MISSION.repositoryId && task.taskCode === MISSION.taskCode));
  return <ConfigProvider theme={{ token: { colorPrimary: "#5f7f9d", borderRadius: 8, fontFamily: '"PingFang SC", -apple-system, sans-serif' } }}>
    {contextHolder}
    <div className="workbench">
      <aside className="sidebar">
        <div className="brand"><span className="brand-logo">硕</span><strong>硕磐智能</strong><Tag>Agent</Tag></div>
        <div className="sidebar-scroll">
          <Button className="new-task" onClick={handleNewSession}>+ 新会话</Button>
          <button className="section-toggle" onClick={() => setHistoryOpen((value) => !value)}><HistoryIcon />历史会话</button>
          {historyOpen && <div className="task-list">{sidebarTasks.length ? sidebarTasks.map((task) => <button className={`task-row ${active?.id === task.id ? "active" : ""}`} key={task.id} onClick={() => openTask(task)}><span>{task.title || "新会话"}</span><small><i className={task.status === "working" ? "working" : task.status === "queued" ? "queued" : task.status === "error" ? "error" : ""} />{task.workspace || task.project} · {relativeTime(task.updated)}{task.status === "working" ? " · 执行中" : task.status === "queued" ? " · 排队中" : task.status === "blocked" ? " · 已阻断" : ""}</small></button>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有会话" />}</div>}
          <Button className="settings-button" onClick={() => setSettingsOpen(true)}><ModelSettingsIcon /> 大语言模型设置</Button>
          {MISSION && <div className="current-mission">
            <Button type="text" className="current-mission-trigger" onClick={() => setMissionInfoOpen(true)}><CurrentMissionIcon /> 当前任务信息</Button>
            <small>{MISSION.taskCode} · 本体库 {MISSION.repositoryId}</small>
            <div className="sidebar-mission-info">
              {missionLoading ? <Spin size="small" /> : missionContext ? <RecursiveInfo value={missionContext} /> : <span className="sidebar-mission-empty">暂未获取到完整任务信息</span>}
            </div>
          </div>}
        </div>
        <div className="sandbox-note">沙箱模式：智能体只能操作当前任务工作目录。<br /><span>{meta.sandbox || "sandbox/"}</span></div>
      </aside>
      <main className="main-content">
        {view === "home" ? <section className="home-view"><h1>{MISSION ? (MISSION.taskType === "integration" ? "智能消歧与整合" : "智能建模") : "本体智能体"}</h1><Composer value={text} onChange={setText} onSend={send} onAttach={onAttach} pendingFiles={pendingFiles} mission={MISSION} busy={busy} hasConversation={false} model={model} models={meta.models} onModel={onModel} onOpenSettings={() => setSettingsOpen(true)} placeholder={placeholder} projects={meta.projects} project={selectedProject} onProject={setSelectedProject} /></section> : <section className="task-view">
          <header className="task-header"><i className={active?.status === "working" || active?.status === "queued" || busy ? "status-dot working" : "status-dot"} /><strong title={active?.title || "当前任务"}>{truncateTitle(active?.title || "当前任务")}</strong><Tag>{active?.workspace || active?.project}</Tag><span className="header-spacer" />{isMissionTask && active?.platformStatus !== "FAILED" && <Button type={active?.platformStatus === "COMPLETED" ? "default" : "primary"} icon={active?.platformStatus === "COMPLETED" ? <TaskEditIcon /> : <TaskCompleteIcon />} loading={platformActionLoading} disabled={busy || active?.status === "working" || active?.status === "queued" || minioUploading || (active?.platformStatus !== "COMPLETED" && active?.completionReady === false)} title={active?.platformStatus !== "COMPLETED" && active?.completionReady === false ? "请先上传全部任务结果" : ""} onClick={changePlatformStatus}>{active?.platformStatus === "COMPLETED" ? "修改" : "完成"}</Button>}<Button icon={<TaskFilesIcon />} onClick={() => { setFilesOpen(true); loadFiles(); }}>文件</Button></header>
          <div ref={feedRef} className="feed" onScroll={handleFeedScroll}><EventFeed events={events} onApprove={approve} files={files} onFile={openFile} busy={busy} scope={`task:${active?.id || "task"}`} /></div>
          <div className="task-composer"><Composer value={text} onChange={setText} onSend={send} onAttach={onAttach} pendingFiles={pendingFiles} mission={MISSION} busy={busy} hasConversation={hasConversation} model={model} models={meta.models} onModel={onModel} onOpenSettings={() => setSettingsOpen(true)} placeholder={placeholder} projects={meta.projects} project={selectedProject} onProject={setSelectedProject} autoApprove={autoApprove} onToggleAutoApprove={toggleAutoApprove} showAutoApprove={isMissionTask} /></div>
        </section>}
      </main>
      <FilePanel open={filesOpen} files={files} loading={filesLoading} selected={selectedFiles} focusPath={focusFile} resetKey={active?.id} onSelect={(path) => setSelectedFiles((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path])} onSelectGroup={(paths) => setSelectedFiles((current) => paths.every((path) => current.includes(path)) ? current.filter((path) => !paths.includes(path)) : [...new Set([...current, ...paths])])} onOpen={openFile} onDownload={download} onUploadToMinio={uploadToMinio} uploadingToMinio={minioUploading} uploadBlocked={busy || active?.status === "working" || active?.status === "queued" || platformActionLoading} onDrawOntology={drawOntology} drawingOntology={ontologyDrawing} ontologyAvailable={Boolean(ontologyFiles)} onClose={() => setFilesOpen(false)} onRefresh={() => loadFiles()} mission={isMissionTask} platformStatus={active?.platformStatus} />
      <input ref={fileInput} type="file" multiple hidden onChange={onFilesSelected} />
      {preview && <Modal open centered={!previewFullscreen} wrapClassName={previewFullscreen ? "preview-modal-wrap-fullscreen" : ""} className={previewFullscreen ? "preview-modal preview-modal-fullscreen" : "preview-modal"} title={<PreviewModalTitle title={preview.path} fullscreen={previewFullscreen} onToggle={() => setPreviewFullscreen((value) => !value)} />} footer={null} width={previewFullscreen ? "100vw" : "88vw"} onCancel={() => { closePreview(); setPreviewFullscreen(false); }}>{preview.ontologyGraph ? <OntologyTreePreview data={preview.ontologyGraph} /> : preview.image ? <img className="preview-image" src={preview.image} alt={preview.path} /> : preview.xlsx ? <SpreadsheetPreview sheets={preview.sheets} /> : preview.csv ? <CsvPreview text={preview.text} /> : <pre className="preview-text">{preview.text}</pre>}</Modal>}
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} meta={meta} model={model} onModel={onModel} params={params} onParams={onParams} provider={provider} keyValue={keyValue} setKeyValue={setKeyValue} onSaveKey={onSaveKey} />
      <Modal open={Boolean(uploadIssues)} title="上传结果明细" footer={null} width={720} onCancel={() => setUploadIssues(null)} destroyOnClose>
        <div className="upload-issue-list">
          {uploadIssues && uploadIssues.map((issue, index) => (
            <div className="upload-issue-item" key={`${issue.name}-${index}`}>
              <div className="upload-issue-head"><strong>{issue.name}</strong>{issue.stage ? <Tag>{issue.stage}</Tag> : null}{issue.code ? <Tag color="red">{issue.code}</Tag> : null}</div>
              <pre className="upload-issue-error">{issue.error}</pre>
            </div>
          ))}
        </div>
      </Modal>
      {MISSION && <MissionInfo open={missionInfoOpen} context={missionContext} loading={missionLoading} onClose={() => setMissionInfoOpen(false)} />}
    </div>
  </ConfigProvider>;
}

createRoot(document.getElementById("root")).render(<AntApp>{STANDALONE ? <StandaloneApp /> : <App />}</AntApp>);
