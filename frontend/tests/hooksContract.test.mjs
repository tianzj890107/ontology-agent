import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../src/main.jsx", import.meta.url), "utf8");

const EXPECTED_HOOKS = ["useEffect", "useLayoutEffect", "useMemo", "useRef", "useState", "useCallback"];

function importedReactHooks(src) {
  const match = src.match(/import\s+React\s*,\s*\{([^}]*)\}\s*from\s*["']react["']/);
  assert.ok(match, "main.jsx 必须包含 React hooks 导入语句");
  return match[1].split(",").map((name) => name.trim()).filter(Boolean);
}

function usedReactHooks(src) {
  const used = new Set();
  // Property-style calls like message.useMessage() are excluded via lookbehind.
  for (const match of src.matchAll(/(?<!\.)\buse[A-Z][A-Za-z0-9]*\s*\(/g)) {
    used.add(match[0].replace(/\s*\($/, ""));
  }
  return used;
}

test("main.jsx 中使用的每个 React hook 都已从 react 导入", () => {
  const imported = new Set(importedReactHooks(source));
  const used = usedReactHooks(source);
  const missing = [...used].filter((hook) => !imported.has(hook));
  assert.deepEqual(missing, [], `已使用但未从 react 导入的 hooks: ${missing.join(", ")}`);
});

test("useCallback 已导入并被 OntologyTreePreview 使用", () => {
  const imported = importedReactHooks(source);
  assert.ok(imported.includes("useCallback"), "useCallback 必须从 react 导入");
  assert.match(source, /const ensureRadialReady = useCallback\(async \(\) =>/, "OntologyTreePreview 必须使用 useCallback");
});

test("预期 hooks 全部导入", () => {
  const imported = importedReactHooks(source);
  for (const hook of EXPECTED_HOOKS) {
    assert.ok(imported.includes(hook), `${hook} 必须导入`);
  }
});

test("不使用 React.useXxx 混用风格", () => {
  assert.doesNotMatch(source, /React\.use[A-Z][A-Za-z0-9]*\s*\(/);
});

test("47313 与 47314 两处 Modal 都用外层 ErrorBoundary 包裹 OntologyTreePreview", () => {
  const wrapped = [...source.matchAll(
    /<OntologyPreviewErrorBoundary\b[^>]*resetKey=\{ontologyPreviewResetKey\(preview\.ontologyGraph\)\}[^>]*><OntologyTreePreview data=\{preview\.ontologyGraph\} \/><\/OntologyPreviewErrorBoundary>/g,
  )];
  assert.equal(wrapped.length, 2, "必须正好有两处外层 ErrorBoundary 包裹 OntologyTreePreview（47313 + 47314）");
});

test("内部 Sigma ErrorBoundary 仍位于 React.Suspense 内且 OntologySigmaPreview 保持懒加载", () => {
  assert.match(source, /const OntologySigmaPreview = React\.lazy\(\(\) => import\("\.\/OntologySigmaPreview\.jsx"\)\)/);
  assert.match(source, /React\.Suspense[\s\S]*?OntologyPreviewErrorBoundary[\s\S]*?OntologySigmaPreview/);
});
