import { computeFitScale, layoutOntologyRadial, scaledTypography } from "./ontologyRadialLayout.js";

// Bump when the radial layout algorithm or its render conversion changes so
// stale cached layouts from an older build are never reused.
export const RADIAL_LAYOUT_VERSION = "v1";

export function normalizeViewport(width, height) {
  return {
    width: Math.max(320, Math.round(Number(width) || 0)),
    height: Math.max(520, Math.round(Number(height) || 0)),
  };
}

export function readViewport(element) {
  if (!element) return normalizeViewport(0, 0);
  return normalizeViewport(element.clientWidth || 0, element.clientHeight || 0);
}

// FNV-1a 32-bit fingerprint of the visible node/link set.  Any node, layer,
// size or link change produces a different fingerprint so cached radial
// layouts are invalidated when the underlying data changes.
export function ontologyDataFingerprint(graph) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const links = Array.isArray(graph?.links) ? graph.links : [];
  let hash = 2166136261;
  const feed = (value) => {
    const text = String(value ?? "");
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
  };
  feed(nodes.length);
  for (const node of nodes) {
    feed(node?.id || "");
    feed(node?.layer || "");
    feed(Array.isArray(node?.symbolSize) ? node.symbolSize.join("x") : node?.symbolSize || "");
  }
  feed(links.length);
  for (const link of links) {
    feed(link?.source || "");
    feed(link?.target || "");
  }
  return (hash >>> 0).toString(36);
}

export function radialCacheKey({ fingerprint, layerKey, width, height, version = RADIAL_LAYOUT_VERSION }) {
  const viewport = normalizeViewport(width, height);
  return `radial:${fingerprint}:${layerKey}:${viewport.width}x${viewport.height}:${version}`;
}

export function radialSeriesRenderData(layout, fitScale) {
  const renderNodes = layout.nodes.map((node) => ({
    ...node,
    symbolSize: Array.isArray(node.symbolSize)
      ? node.symbolSize.map((value) => Number(value) * fitScale)
      : node.symbolSize,
  }));
  return { data: [...renderNodes, ...layout.boundaryAnchors], links: layout.links };
}

export function prepareRadialLayout(graph, appliedLayers, viewport = {}) {
  const { width, height } = normalizeViewport(viewport.width, viewport.height);
  const layerKey = Array.isArray(appliedLayers) ? appliedLayers.join("|") : "";
  const layout = layoutOntologyRadial(graph, {
    selectedLayers: appliedLayers,
    viewportWidth: width,
    viewportHeight: height,
    horizontalGap: 10,
    verticalGap: 6,
    radialGap: 8,
    padding: 12,
    hoverScale: 1.12,
  });
  if (!layout) return null;
  const fitScale = computeFitScale(layout.naturalWidth, layout.naturalHeight, width, height);
  return {
    layout,
    fitScale,
    viewportWidth: width,
    viewportHeight: height,
    layerKey,
    renderData: radialSeriesRenderData(layout, fitScale),
  };
}

export function radialGraphOption(prepared) {
  const { fitScale, renderData } = prepared;
  const displayScale = fitScale;
  return {
    tooltip: { trigger: "item", formatter: ({ data: node }) => node?.layoutAnchor ? "" : node?.name || "" },
    series: [{
      id: "ontology-graph",
      type: "graph",
      layout: "none",
      data: renderData.data,
      links: renderData.links,
      top: 0,
      left: 0,
      bottom: 0,
      right: 0,
      roam: true,
      zoom: 1,
      scaleLimit: { min: 0.15, max: 12 },
      nodeScaleRatio: 1,
      label: {
        show: true,
        position: "inside",
        verticalAlign: "middle",
        align: "center",
        color: "#fff",
        fontSize: scaledTypography(13, displayScale, 1),
        overflow: "truncate",
        formatter: ({ data: node }) => node?.layoutAnchor ? "" : node?.name || "",
      },
      lineStyle: { color: "#94a3b8", width: Math.max(0.5, 1.2 * displayScale), opacity: 0.8, curveness: 0.08 },
      emphasis: { focus: "none", scale: 1.12 },
      blur: { itemStyle: { opacity: 1 }, lineStyle: { opacity: 0.8 }, label: { opacity: 1 } },
      selectedMode: false,
      animationDuration: 0,
      animationDurationUpdate: 0,
    }],
  };
}

// Bounded radial-layout cache.  Entries are evicted oldest-first so closing a
// preview or switching tasks never keeps unbounded graph data in memory.
export function createRadialLayoutCache(options = {}) {
  const maxEntries = Math.max(1, Number(options.maxEntries) || 8);
  const store = new Map();
  const inflight = new Map();
  return {
    get maxEntries() { return maxEntries; },
    has(key) { return store.has(key); },
    get(key) { return store.get(key)?.prepared || null; },
    set(key, prepared) {
      if (store.has(key)) store.delete(key);
      store.set(key, { key, prepared, updatedAt: Date.now() });
      while (store.size > maxEntries) store.delete(store.keys().next().value);
      return prepared;
    },
    delete(key) {
      store.delete(key);
      inflight.delete(key);
    },
    clear() {
      store.clear();
      inflight.clear();
    },
    size() { return store.size; },
    getInFlight(key) { return inflight.get(key) || null; },
    putInFlight(key, promise) { inflight.set(key, promise); },
    clearInFlight(key) { inflight.delete(key); },
    inflightSize() { return inflight.size; },
  };
}

export function layoutIsForViewport(prepared, viewport) {
  if (!prepared) return false;
  const expected = normalizeViewport(viewport.width, viewport.height);
  return prepared.viewportWidth === expected.width && prepared.viewportHeight === expected.height;
}
