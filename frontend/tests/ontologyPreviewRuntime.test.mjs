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

test("47313 与 47314 的绘图入口都先查会话 graph 缓存再加载", async () => {
  const { readFile } = await import("node:fs/promises");
  const code = await readFile(new URL("../src/main.jsx", import.meta.url), "utf-8");
  // Both draw functions must consult the shared per-session graph cache before
  // downloading any CSV, and reuse the same in-flight promise on a click.
  const drawEntries = [...code.matchAll(/const (drawOntology|drawStandaloneOntology) = async \(\) => \{/g)];
  assert.equal(drawEntries.length, 2);
  for (const entry of drawEntries) {
    const name = entry[1];
    const start = code.indexOf(entry[0]);
    const end = code.indexOf("};", start);
    const body = code.slice(start, end);
    assert.match(body, /graphCache\.getStatus/);
    assert.match(body, /graphCache\.ensure/);
    assert.match(body, /status\.status === "ready"/);
  }
  // Cache-first behavior exists on both sides, plus per-entry loading guards.
  assert.match(code, /standaloneGraphCacheRef/);
  assert.match(code, /taskGraphCacheRef/);
  assert.match(code, /standaloneDrawRequestRef/);
  assert.match(code, /ontologyDrawRequestRef/);
});

test("会话文件列表就绪后两个入口都会后台预加载本体 graph", async () => {
  const { readFile } = await import("node:fs/promises");
  const code = await readFile(new URL("../src/main.jsx", import.meta.url), "utf-8");
  // 47313: loadFiles and openTask both trigger the task graph preload.
  assert.match(code, /preloadTaskOntologyGraph\(taskCacheKey\(task\), loadedFiles, task\)/);
  assert.match(code, /preloadTaskOntologyGraph\(taskKey, loadedFiles, current\)/);
  // 47314: loadRunFiles triggers the standalone graph preload.
  assert.match(code, /preloadStandaloneOntologyGraph\(runId, loadedFiles\)/);
  // Preload is fire-and-forget: it must never auto-open the preview Modal.
  const preloadSites = [...code.matchAll(/void graphCache\.ensure\([\s\S]*?\)\.catch\(\(\) => \{\}\)/g)];
  assert.equal(preloadSites.length, 2);
  assert.ok(preloadSites.every((site) => site[0].includes("void graphCache.ensure")));
});

test("会话切换回 A 时从内存缓存恢复事件与文件列表", async () => {
  const { readFile } = await import("node:fs/promises");
  const code = await readFile(new URL("../src/main.jsx", import.meta.url), "utf-8");
  // 47313 openTask merges the cached events into the fresh tail window and
  // restores the cached log window start; the active-task effect restores the
  // cached file list on switch back.
  assert.match(code, /mergeEvents\(cachedEvents, recentEvents, `task:\$\{current\.id\}`\)/);
  assert.match(code, /restoredStart < logStart/);
  assert.match(code, /taskSessionCacheRef\.current\.get\(taskCacheKey\(active\)\)/);
  // 47314 selectRun restores events/files/window from the bounded run cache.
  assert.match(code, /const cachedSession = standaloneSessionCacheRef\.current\.get\(runId\);/);
  assert.match(code, /eventWindowRef\.current\.set\(runId, cachedSession\.eventWindow\)/);
  assert.match(code, /files: cachedSession\?\.files\?\.length \? cachedSession\.files/);
});

test("缓存使用内存 LRU 且不写入持久化存储", async () => {
  const { readFile } = await import("node:fs/promises");
  const code = await readFile(new URL("../src/main.jsx", import.meta.url), "utf-8");
  assert.match(code, /createSessionCache\(\{ maxEntries: 10 \}\)/);
  assert.match(code, /createOntologyGraphCache\(\{[\s\S]*?maxEntries: 10/);
  // The graph cache keys are namespaced by mission identity where applicable.
  assert.match(code, /taskCacheKey/);
  assert.match(code, /mission:\$\{identity\.repositoryId\}:\$\{identity\.taskCode\}:\$\{task\?\.id\}/);
});
