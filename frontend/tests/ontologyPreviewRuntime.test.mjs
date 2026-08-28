import test, { after, before } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import TestRenderer from "react-test-renderer";
import { renderToString } from "react-dom/server";
import { createServer } from "vite";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const clientStub = fileURLToPath(new URL("./fixtures/react-dom-client-stub.mjs", import.meta.url));

let server;
let mod;

before(async () => {
  globalThis.window = { __MISSION__: undefined, __STANDALONE_MODELING__: false };
  globalThis.document = { getElementById: () => null };
  server = await createServer({
    root: frontendRoot,
    logLevel: "silent",
    server: { middlewareMode: true },
    appType: "custom",
    resolve: {
      alias: { "react-dom/client": clientStub },
    },
  });
  mod = await server.ssrLoadModule("/src/main.jsx");
});

after(async () => {
  await server?.close();
});

function graphData(availability, nodes = [], links = []) {
  return { nodes, links, availability };
}

const EMPTY_AVAILABILITY = {
  businessObject: false,
  logicalEntity: false,
  businessAttribute: false,
  entityRelation: false,
  metric: false,
  businessRule: false,
  action: false,
};

test("OntologyTreePreview 真实渲染不再抛出 useCallback is not defined", () => {
  const data = graphData({ ...EMPTY_AVAILABILITY, logicalEntity: true });
  let html = "";
  assert.doesNotThrow(() => {
    html = renderToString(React.createElement(mod.OntologyTreePreview, { data }));
  }, "OntologyTreePreview 渲染不应抛出 ReferenceError");
  assert.match(html, /ontology-tree-shell/);
  assert.match(html, /ontology-toolbar/);
});

test("不同数据形态都能渲染 OntologyTreePreview", () => {
  const shapes = [
    graphData({ ...EMPTY_AVAILABILITY, logicalEntity: true }),
    graphData({ ...EMPTY_AVAILABILITY, businessObject: true, logicalEntity: true }),
    graphData({ ...EMPTY_AVAILABILITY, businessObject: true, logicalEntity: true, businessAttribute: true }),
    graphData({
      businessObject: true,
      logicalEntity: true,
      businessAttribute: true,
      entityRelation: true,
      metric: true,
      businessRule: true,
      action: true,
    }, [{ id: "businessObject:BO000001", layer: "businessObject" }], []),
    graphData(EMPTY_AVAILABILITY),
  ];
  for (const data of shapes) {
    assert.doesNotThrow(() => renderToString(React.createElement(mod.OntologyTreePreview, { data })));
  }
});

function ThrowingChild() {
  throw new Error("visualization boom");
}

function GoodChild() {
  return React.createElement("div", { className: "good-child" }, "ok");
}

test("外层 ErrorBoundary 显示局部错误占位且不清空页面外壳", () => {
  const shell = React.createElement("div", { className: "standalone-shell" },
    React.createElement("aside", { className: "standalone-history" }, "历史运行"),
    React.createElement("main", { className: "standalone-main" },
      React.createElement(mod.OntologyPreviewErrorBoundary, { message: "本体可视化加载失败，请关闭后重试" },
        React.createElement(ThrowingChild))));
  const renderer = TestRenderer.create(shell);
  const text = JSON.stringify(renderer.toJSON());
  assert.match(text, /本体可视化加载失败，请关闭后重试/);
  assert.match(text, /standalone-shell/);
  assert.match(text, /standalone-history/);
  assert.match(text, /standalone-main/);
  renderer.unmount();
});

test("resetKey 改变后 ErrorBoundary 可以重试", () => {
  const renderer = TestRenderer.create(
    React.createElement(mod.OntologyPreviewErrorBoundary, { resetKey: "a", message: "本体可视化加载失败，请关闭后重试" }, React.createElement(ThrowingChild)),
  );
  assert.match(JSON.stringify(renderer.toJSON()), /本体可视化加载失败/);
  TestRenderer.act(() => {
    renderer.update(
      React.createElement(mod.OntologyPreviewErrorBoundary, { resetKey: "b" }, React.createElement(GoodChild)),
    );
  });
  assert.match(JSON.stringify(renderer.toJSON()), /good-child/);
  renderer.unmount();
});

test("关闭 Modal（卸载）后可以再次打开并正常渲染", () => {
  const renderer = TestRenderer.create(
    React.createElement(mod.OntologyPreviewErrorBoundary, { resetKey: "x", message: "本体可视化加载失败，请关闭后重试" }, React.createElement(ThrowingChild)),
  );
  assert.match(JSON.stringify(renderer.toJSON()), /本体可视化加载失败/);
  renderer.unmount();
  const reopened = TestRenderer.create(
    React.createElement(mod.OntologyPreviewErrorBoundary, { message: "本体可视化加载失败，请关闭后重试" }, React.createElement(GoodChild)),
  );
  assert.match(JSON.stringify(reopened.toJSON()), /good-child/);
  reopened.unmount();
});

test("内部 Sigma ErrorBoundary 默认文案保留且仍能捕获渲染错误", () => {
  const tree = React.createElement(React.Suspense, { fallback: React.createElement("div", { className: "sigma-fallback" }, "loading") },
    React.createElement(mod.OntologyPreviewErrorBoundary, {}, React.createElement(ThrowingChild)));
  const renderer = TestRenderer.create(tree);
  assert.match(JSON.stringify(renderer.toJSON()), /关系布局加载失败，请稍后重试/);
  renderer.unmount();
});

test("onError 回调收到真实渲染错误", () => {
  const errors = [];
  TestRenderer.create(
    React.createElement(mod.OntologyPreviewErrorBoundary, { onError: (error) => errors.push(error) }, React.createElement(ThrowingChild)),
  ).unmount();
  assert.equal(errors.length, 1);
  assert.ok(errors[0] instanceof Error);
  assert.equal(errors[0].message, "visualization boom");
});

test("PreviewModalTitle 全屏按钮真实切换 aria-label 与 onToggle 回调", () => {
  let toggles = 0;
  const renderer = TestRenderer.create(
    React.createElement(mod.PreviewModalTitle, { title: "x.csv", fullscreen: false, onToggle: () => { toggles += 1; } }),
  );
  let button = renderer.root.findByType("button");
  assert.equal(button.props["aria-label"], "全屏");
  TestRenderer.act(() => button.props.onClick());
  assert.equal(toggles, 1);
  renderer.update(
    React.createElement(mod.PreviewModalTitle, { title: "x.csv", fullscreen: true, onToggle: () => { toggles += 1; } }),
  );
  button = renderer.root.findByType("button");
  assert.equal(button.props["aria-label"], "退出全屏");
  TestRenderer.act(() => button.props.onClick());
  assert.equal(toggles, 2);
  renderer.unmount();
});

test("预览 Modal 全屏 class 契约在 47313 与 47314 两个入口一致", async () => {
  const { readFile } = await import("node:fs/promises");
  const code = await readFile(new URL("../src/main.jsx", import.meta.url), "utf-8");
  const fullscreenBindings = [...code.matchAll(/previewFullscreen \? "preview-modal preview-modal-fullscreen" : "preview-modal"/g)];
  assert.equal(fullscreenBindings.length, 2);
  const wrapBindings = [...code.matchAll(/wrapClassName=\{previewFullscreen \? "preview-modal-wrap-fullscreen" : ""\}/g)];
  assert.equal(wrapBindings.length, 2);
  assert.match(code, /centered=\{!previewFullscreen\}/);
  assert.match(code, /function PreviewModalTitle\(\{ title, fullscreen, onToggle \}\)/);
});

test("47313 mission 会话预加载与点击使用完全相同的 namespaced key", async () => {
  const { taskCacheKey, createOntologyGraphCache } = await import("../src/sessionCache.js");
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const cache = createOntologyGraphCache({
    loadText: async (entry) => { calls += 1; await gate; return `csv:${entry.path}`; },
    buildGraph: (entries) => ({ availability: { logicalEntity: Boolean(entries.length) }, nodes: [], links: [] }),
  });
  const task = { id: "t-1", repositoryId: "repo-a", taskCode: "task-code-a", project: "p" };
  const MISSION = { repositoryId: "repo-a", taskCode: "task-code-a" };
  const taskKey = taskCacheKey(task, MISSION);
  const artifacts = [["logicalEntity", { name: "logical_entities.csv", path: "output/logical_entities.csv", size: 10 }]];
  // 预加载（后台）与点击（用户操作）使用同一 key，共享同一个在途 Promise。
  const preload = cache.ensure(taskKey, artifacts, { task });
  const click = cache.ensure(taskKey, artifacts, { task });
  assert.equal(cache.getStatus(taskKey, artifacts).status, "loading");
  release();
  const [preloaded, clicked] = await Promise.all([preload, click]);
  assert.equal(preloaded, clicked);
  assert.equal(calls, 1, "同一批 CSV 只下载一次");
  assert.equal(cache.getStatus(taskKey, artifacts).status, "ready");
});

test("47313 非 mission 会话预加载与点击使用相同的 task:<id> key", async () => {
  const { taskCacheKey, createOntologyGraphCache } = await import("../src/sessionCache.js");
  let calls = 0;
  const cache = createOntologyGraphCache({
    loadText: async (entry) => { calls += 1; return `csv:${entry.path}`; },
    buildGraph: (entries) => ({ availability: { logicalEntity: Boolean(entries.length) }, nodes: [], links: [] }),
  });
  const task = { id: "t-2", project: "p" };
  const taskKey = taskCacheKey(task, null);
  assert.equal(taskKey, "task:t-2");
  const artifacts = [["logicalEntity", { name: "logical_entities.csv", path: "output/logical_entities.csv", size: 10 }]];
  await cache.ensure(taskKey, artifacts, { task });
  const status = cache.getStatus(taskKey, artifacts);
  assert.equal(status.status, "ready");
  assert.equal(calls, 1, "点击复用预加载结果，不重复下载");
  assert.equal(cache.getStatus("t-2", artifacts).status, "empty", "裸 taskId 查不到 namespaced 缓存");
});

test("47314 run 预加载与点击共享同一 runId scope 的在途 Promise", async () => {
  const { createOntologyGraphCache } = await import("../src/sessionCache.js");
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const cache = createOntologyGraphCache({
    loadText: async (entry) => { calls += 1; await gate; return `csv:${entry.path}`; },
    buildGraph: (entries) => ({ availability: { logicalEntity: Boolean(entries.length) }, nodes: [], links: [] }),
  });
  const runId = "run-42";
  const artifacts = [["logicalEntity", { name: "logical_entities.csv", path: "output/logical_entities.csv", size: 10 }]];
  const preload = cache.ensure(runId, artifacts, { runId });
  const click = cache.ensure(runId, artifacts, { runId });
  release();
  const [preloaded, clicked] = await Promise.all([preload, click]);
  assert.equal(preloaded, clicked);
  assert.equal(calls, 1);
  assert.equal(cache.getStatus(runId, artifacts).status, "ready");
});

test("LRU 同时保护 47313 namespaced active key 与 47314 active runId", async () => {
  const { commitSessionSnapshot, createSessionCache, taskCacheKey } = await import("../src/sessionCache.js");
  const sessionCache = createSessionCache({ maxEntries: 2 });
  const keyA = taskCacheKey({ id: "t-a", repositoryId: "repo-a", taskCode: "task-code-a" }, { repositoryId: "repo-a", taskCode: "task-code-a" });
  const keyB = taskCacheKey({ id: "t-b", repositoryId: "repo-a", taskCode: "task-code-a" }, { repositoryId: "repo-a", taskCode: "task-code-a" });
  const keyC = taskCacheKey({ id: "t-c", repositoryId: "repo-a", taskCode: "task-code-a" }, { repositoryId: "repo-a", taskCode: "task-code-a" });
  commitSessionSnapshot(sessionCache, keyA, { events: [] }, keyC);
  commitSessionSnapshot(sessionCache, keyB, { events: [] }, keyC);
  commitSessionSnapshot(sessionCache, keyC, { events: [] }, keyC);
  assert.equal(sessionCache.has(keyC), true, "namespaced 活动 key 不得被淘汰");
  assert.equal(sessionCache.has(keyA), false);
  // 47314: runId 是服务端唯一 scope，直接按 runId 保护。
  const runCache = createSessionCache({ maxEntries: 2 });
  runCache.set("run:1", { events: [] });
  runCache.set("run:2", { events: [] });
  runCache.set("run:3", { events: [] });
  runCache.evictToFit("run:3");
  assert.equal(runCache.has("run:3"), true);
  assert.equal(runCache.has("run:1"), false);
});

test("A → B → A 切换时立即恢复缓存快照，迟到响应被 generation 拦截", async () => {
  const { createOpenGate, restoreTaskPlan, sessionSnapshotFor, taskCacheKey, createSessionCache } = await import("../src/sessionCache.js");
  const cache = createSessionCache({ maxEntries: 10 });
  const keyA = taskCacheKey({ id: "t-a", repositoryId: "repo-a", taskCode: "task-code-a" }, { repositoryId: "repo-a", taskCode: "task-code-a" });
  cache.set(keyA, {
    detail: { id: "t-a", status: "completed" },
    events: [{ type: "assistant", seq: 1, text: "A 事件" }],
    files: [{ path: "output/business_objects.csv" }],
    logWindow: { start: 0, total: 3, cursor: 3 },
  });
  const gate = createOpenGate();
  const openA = () => {
    const task = { id: "t-a", repositoryId: "repo-a", taskCode: "task-code-a" };
    const taskKey = taskCacheKey(task, { repositoryId: "repo-a", taskCode: "task-code-a" });
    const snapshot = restoreTaskPlan(sessionSnapshotFor(cache, taskKey));
    const generation = gate.begin();
    return { snapshot, generation, isCurrent: () => gate.isCurrent(generation) };
  };
  const first = openA();
  assert.ok(first.snapshot, "A 缓存存在时立即得到快照，无需等待详情请求");
  assert.equal(first.snapshot.events[0].text, "A 事件");
  // 用户切到 B（无缓存），再切回 A：B 的 generation 已过期。
  const openB = () => {
    const task = { id: "t-b", repositoryId: "repo-a", taskCode: "task-code-a" };
    const taskKey = taskCacheKey(task, { repositoryId: "repo-a", taskCode: "task-code-a" });
    const snapshot = restoreTaskPlan(sessionSnapshotFor(cache, taskKey));
    const generation = gate.begin();
    return { snapshot, generation, isCurrent: () => gate.isCurrent(generation) };
  };
  const second = openB();
  assert.equal(second.snapshot, null);
  const third = openA();
  assert.equal(first.isCurrent(), false, "A 第一次的迟到响应不能覆盖 B");
  assert.equal(second.isCurrent(), false, "B 的迟到响应不能覆盖重新激活的 A");
  assert.equal(third.isCurrent(), true);
});

test("main.jsx 绘图与预加载统一使用 namespaced key，不再用裸 taskId 查询 graph 缓存", async () => {
  const { readFile } = await import("node:fs/promises");
  const code = await readFile(new URL("../src/main.jsx", import.meta.url), "utf-8");
  // 47313 drawOntology 与 preload 必须使用同一个 taskCacheKey(task, MISSION)，
  // LRU 保护也必须使用 namespaced active key（这是本任务修复的阻断缺陷）。
  const drawStart = code.indexOf("const drawOntology = async () => {");
  const drawBody = code.slice(drawStart, code.indexOf("const download =", drawStart));
  assert.match(drawBody, /const taskKey = taskCacheKey\(task, MISSION\);/);
  assert.match(drawBody, /graphCache\.getStatus\(taskKey, artifacts\)/);
  assert.match(drawBody, /graphCache\.ensure\(taskKey, artifacts, \{ task \}\)/);
  assert.match(drawBody, /graphCache\.evictToFit\(activeTaskCacheKeyRef\.current\)/);
  assert.doesNotMatch(drawBody, /graphCache\.getStatus\(taskId, artifacts\)/);
  // 47313 会话缓存与 graph 缓存共用同一 namespaced key；预加载入口接收
  // 调用方已计算好的 taskKey，而不是自己用裸 taskId 重新构造。
  assert.match(code, /const taskKey = taskCacheKey\(task, MISSION\);/);
  assert.match(code, /activeTaskCacheKeyRef\.current = active\?\.id \? taskCacheKey\(active, MISSION\) : ""/);
  // 47314 使用服务端唯一 runId 作为 scope，preload 与点击保持一致。
  assert.match(code, /preloadStandaloneOntologyGraph\(runId, loadedFiles\)/);
  assert.match(code, /graphCache\.getStatus\(runId, artifacts\)/);
  assert.match(code, /graphCache\.ensure\(runId, artifacts, \{ runId \}\)/);
  assert.match(code, /graphCache\.evictToFit\(selectedRunIdRef\.current\)/);
  // 不写入任何持久化存储。
  assert.doesNotMatch(code, /taskSessionCacheRef.*(localStorage|sessionStorage|indexedDB|IndexedDB)/);
  assert.doesNotMatch(code, /standaloneSessionCacheRef.*(localStorage|sessionStorage|indexedDB|IndexedDB)/);
});

test("openTask 在 mission await 后重新校验当前请求且 setMeta 位于最终守卫之后", async () => {
  const { readFile } = await import("node:fs/promises");
  const code = await readFile(new URL("../src/main.jsx", import.meta.url), "utf-8");
  const openStart = code.indexOf("const openTask = async (task) => {");
  const openBody = code.slice(openStart, code.indexOf("const loadFiles = async", openStart));
  // mission 请求共享 open 请求的 AbortSignal 与当前判定。
  assert.match(openBody, /loadMission\(\s*\{ \.\.\.taskMission, taskType: /);
  assert.match(openBody, /signal: openRequest\.controller\.signal, isCurrent: isCurrentOpen/);
  // mission await 之后、任何可见 state commit 之前必须重新校验。
  const missionBlockStart = openBody.indexOf("const missionResult = await loadMission");
  const missionBlock = openBody.slice(missionBlockStart, openBody.indexOf("feedPinnedRef.current = true;", missionBlockStart));
  assert.match(missionBlock, /if \(result\._aborted \|\| !isCurrentOpen\(\)\) return;/);
  // setMeta 必须位于最终守卫之后，不能由迟到的 A 覆盖 B。
  const setMetaIndex = openBody.indexOf("if (current.model) {");
  const finalGuardIndex = openBody.indexOf("if (result._aborted || !isCurrentOpen()) return;", missionBlockStart);
  assert.ok(finalGuardIndex !== -1 && finalGuardIndex < setMetaIndex, "setMeta 位于最终 generation 守卫之后");
});

test("loadMission 使用 mission coordinator，旧请求不能提交可见状态", async () => {
  const { readFile } = await import("node:fs/promises");
  const code = await readFile(new URL("../src/main.jsx", import.meta.url), "utf-8");
  const missionStart = code.indexOf("const loadMission = async (mission = MISSION, options = {}) => {");
  const missionBody = code.slice(missionStart, code.indexOf("useLayoutEffect", missionStart));
  assert.match(missionBody, /missionCoordinatorRef\.current\.begin\(identityKey\)/);
  assert.match(missionBody, /const signal = options\.signal \|\|/);
  assert.match(missionBody, /missionCoordinatorRef\.current\.isCurrent\(request\)/);
  assert.match(missionBody, /!options\.isCurrent \|\| options\.isCurrent\(\)/);
  assert.match(missionBody, /if \(result\._aborted \|\| !isCurrent\(\)\) return null;/);
  // 只有当前请求可以 setMissionContext / setMissionLoading(false)。
  const guardIndex = missionBody.indexOf("if (result._aborted || !isCurrent()) return null;");
  const afterGuard = missionBody.slice(guardIndex);
  assert.match(afterGuard, /setMissionContext\(result\.task\)/);
  assert.match(afterGuard, /setMissionLoading\(false\)/);
});

test("后台 scheduleIdle 受当前 open generation 限制", async () => {
  const { readFile } = await import("node:fs/promises");
  const code = await readFile(new URL("../src/main.jsx", import.meta.url), "utf-8");
  const openStart = code.indexOf("const openTask = async (task) => {");
  const openBody = code.slice(openStart, code.indexOf("const loadFiles = async", openStart));
  const idleStart = openBody.indexOf("scheduleIdle(async () => {");
  const idleBody = openBody.slice(idleStart, openBody.indexOf("});", idleStart));
  assert.match(idleBody, /if \(!isCurrentOpen\(\)\) return;/);
  // 每个关键 await 之后都重新校验，A 的迟到后台结果不能更新 B 的文件/panel/preview。
  const guardCount = (idleBody.match(/if \(!isCurrentOpen\(\)\) return;/g) || []).length;
  const awaitCount = (idleBody.match(/await loadOlderTaskEvents|await loadFiles/g) || []).length;
  assert.ok(guardCount >= awaitCount, `generation 守卫(${guardCount})不能少于关键 await 数(${awaitCount})`);
  assert.match(idleBody, /if \(isCurrentOpen\(\) && activeTaskIdRef\.current === taskId\)/);
  assert.match(idleBody, /if \(historyHasMore && isCurrentOpen\(\)\)/);
});
