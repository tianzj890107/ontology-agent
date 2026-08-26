import forceAtlas2 from "graphology-layout-forceatlas2";

export const FORCE_ATLAS_CONFIG = Object.freeze({
  scalingRatio: 4.5,
  gravity: 0.25,
  strongGravityMode: false,
  barnesHutOptimize: true,
  barnesHutTheta: 0.65,
  slowDown: 4,
  edgeWeightInfluence: 1,
  linLogMode: true,
  outboundAttractionDistribution: false,
  adjustSizes: false,
});

const TAU = Math.PI * 2;

function hashUnit(value) {
  let hash = 2166136261;
  for (const char of String(value || "")) {
    hash ^= char.codePointAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 100000) / 100000;
}

export function semanticSeed(graph) {
  const businessObjects = graph.filterNodes((node, attributes) => attributes.nodeType === "businessObject");
  const clusterRadius = Math.max(8, Math.sqrt(Math.max(1, businessObjects.length)) * 7);
  const centers = new Map();
  businessObjects.forEach((node, index) => {
    const angle = TAU * index / Math.max(1, businessObjects.length) - Math.PI / 2;
    centers.set(node, { x: Math.cos(angle) * clusterRadius, y: Math.sin(angle) * clusterRadius });
  });
  graph.forEachNode((node, attributes) => {
    const parent = attributes.parentId && graph.hasNode(attributes.parentId) ? attributes.parentId : null;
    const parentCenter = parent ? centers.get(parent) || {
      x: Number(graph.getNodeAttribute(parent, "x")) || 0,
      y: Number(graph.getNodeAttribute(parent, "y")) || 0,
    } : null;
    const ownCenter = centers.get(node);
    const layerDistance = { businessObject: 0, logicalEntity: 3.5, businessAttribute: 5.5, metric: 4.5, businessRule: 8 }[attributes.nodeType] || 6;
    const angle = hashUnit(node) * TAU;
    const center = ownCenter || parentCenter || { x: 0, y: 0 };
    const disconnectedOffset = graph.degree(node) === 0 ? clusterRadius + 8 : layerDistance;
    graph.mergeNodeAttributes(node, {
      x: center.x + Math.cos(angle) * disconnectedOffset,
      y: center.y + Math.sin(angle) * disconnectedOffset,
    });
  });
}

function reduceOverlap(graph, iterations = 18) {
  const nodes = graph.nodes().filter((node) => graph.degree(node) > 0);
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    let moved = false;
    for (let left = 0; left < nodes.length; left += 1) {
      const a = nodes[left];
      const ax = graph.getNodeAttribute(a, "x");
      const ay = graph.getNodeAttribute(a, "y");
      for (let right = left + 1; right < nodes.length; right += 1) {
        const b = nodes[right];
        const bx = graph.getNodeAttribute(b, "x");
        const by = graph.getNodeAttribute(b, "y");
        let dx = bx - ax;
        let dy = by - ay;
        let distance = Math.hypot(dx, dy);
        const minimum = (graph.getNodeAttribute(a, "size") + graph.getNodeAttribute(b, "size")) * 0.13 + 0.8;
        if (distance >= minimum) continue;
        if (distance < 0.0001) {
          const angle = hashUnit(`${a}:${b}`) * TAU;
          dx = Math.cos(angle);
          dy = Math.sin(angle);
          distance = 1;
        }
        const push = (minimum - distance) * 0.34;
        const ux = dx / distance;
        const uy = dy / distance;
        graph.setNodeAttribute(a, "x", graph.getNodeAttribute(a, "x") - ux * push);
        graph.setNodeAttribute(a, "y", graph.getNodeAttribute(a, "y") - uy * push);
        graph.setNodeAttribute(b, "x", graph.getNodeAttribute(b, "x") + ux * push);
        graph.setNodeAttribute(b, "y", graph.getNodeAttribute(b, "y") + uy * push);
        moved = true;
      }
    }
    if (!moved) break;
  }
}

function packIsolatedNodes(graph) {
  const connected = graph.filterNodes((node) => graph.degree(node) > 0);
  const isolated = graph.filterNodes((node) => graph.degree(node) === 0);
  if (!isolated.length) return;
  const xs = connected.map((node) => graph.getNodeAttribute(node, "x"));
  const ys = connected.map((node) => graph.getNodeAttribute(node, "y"));
  const minX = xs.length ? Math.min(...xs) : -5;
  const maxX = xs.length ? Math.max(...xs) : 5;
  const maxY = ys.length ? Math.max(...ys) : 5;
  const columns = Math.max(1, Math.ceil(Math.sqrt(isolated.length)));
  const spacing = 4.5;
  const startX = (minX + maxX) / 2 - (Math.min(columns, isolated.length) - 1) * spacing / 2;
  isolated.forEach((node, index) => {
    graph.setNodeAttribute(node, "x", startX + (index % columns) * spacing);
    graph.setNodeAttribute(node, "y", maxY + 7 + Math.floor(index / columns) * spacing);
  });
}

function normalizeCoordinates(graph, stretchAxes = false, targetAspect = 1) {
  if (!graph.order) return;
  const xs = graph.mapNodes((node, attributes) => Number(attributes.x) || 0);
  const ys = graph.mapNodes((node, attributes) => Number(attributes.y) || 0);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(1, maxX - minX);
  const spanY = Math.max(1, maxY - minY);
  const span = Math.max(spanX, spanY);
  graph.updateEachNodeAttributes((node, attributes) => ({
    ...attributes,
    x: ((Number(attributes.x) || 0) - (minX + maxX) / 2) / (stretchAxes ? spanX : span) * 100 * (stretchAxes ? targetAspect : 1),
    y: ((Number(attributes.y) || 0) - (minY + maxY) / 2) / (stretchAxes ? spanY : span) * 100,
  }));
}

export function forceAtlasIterations(nodeCount) {
  if (nodeCount <= 80) return 180;
  if (nodeCount <= 1200) return 160;
  return 100;
}

export function layoutOntologyForceAtlas(graph, options = {}) {
  if (!graph?.order) return graph;
  semanticSeed(graph);
  if (graph.size) {
    forceAtlas2.assign(graph, {
      iterations: options.iterations || forceAtlasIterations(graph.order),
      settings: { ...FORCE_ATLAS_CONFIG, ...(options.settings || {}) },
      getEdgeWeight: "weight",
    });
  }
  reduceOverlap(graph, options.overlapIterations ?? (graph.order > 500 ? 8 : 18));
  packIsolatedNodes(graph);
  // Sparse filtered graphs otherwise keep the full graph's narrow cluster
  // silhouette and waste one canvas dimension. Stretch their two coordinate
  // axes independently after ForceAtlas2, preserving topology while making
  // the remaining nodes use the available stage in both directions.
  normalizeCoordinates(graph, graph.order <= 40, Math.max(1, Math.min(3.2, Number(options.targetAspect) || 1)));
  return graph;
}

export function graphBounds(graph) {
  const xs = graph.mapNodes((node, attributes) => Number(attributes.x));
  const ys = graph.mapNodes((node, attributes) => Number(attributes.y));
  return {
    minX: Math.min(...xs), maxX: Math.max(...xs),
    minY: Math.min(...ys), maxY: Math.max(...ys),
    width: Math.max(...xs) - Math.min(...xs),
    height: Math.max(...ys) - Math.min(...ys),
  };
}
