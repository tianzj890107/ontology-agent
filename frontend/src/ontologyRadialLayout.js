const TAU = Math.PI * 2;

export const ONTOLOGY_LAYER_DEFINITIONS = [
  { key: "businessObject", nodeType: "businessObject", label: "业务对象", color: "#2563eb" },
  { key: "logicalEntity", nodeType: "entity", label: "逻辑实体", color: "#0f766e" },
  { key: "businessAttribute", nodeType: "attribute", label: "业务属性", color: "#64748b" },
  { key: "metric", nodeType: "metric", label: "指标", color: "#7c3aed" },
  { key: "businessRule", nodeType: "rule", label: "业务规则", color: "#c2410c" },
];

export function nodeWidth(node, fallback = 92) {
  const size = node?.symbolSize;
  return Array.isArray(size) && Number(size[0]) > 0 ? Number(size[0]) : fallback;
}

export function nodeHeight(node, fallback = 38) {
  const size = node?.symbolSize;
  return Array.isArray(size) && Number(size[1]) > 0 ? Number(size[1]) : fallback;
}

export function computeTrackCapacity(radius, spanAngle, maxNodeWidth, minGap) {
  const slot = Math.max(1, maxNodeWidth + minGap);
  return Math.max(1, Math.floor(Math.max(0, radius * spanAngle) / slot));
}

export function computeTrackCount(count, firstRadius, spanAngle, maxNodeWidth, minGap) {
  let remaining = Math.max(0, count);
  let radius = firstRadius;
  let tracks = 0;
  while (remaining > 0) {
    remaining -= computeTrackCapacity(radius, spanAngle, maxNodeWidth, minGap);
    tracks += 1;
    radius += Math.max(1, maxNodeWidth + minGap);
  }
  return tracks;
}

export function computeRingRadius(previousRadius, previousHeight, currentHeight, minGap) {
  return previousRadius + previousHeight / 2 + minGap + currentHeight / 2;
}

export function computeNodeAngle(startAngle, endAngle, index, total) {
  if (total <= 1) return (startAngle + endAngle) / 2;
  return startAngle + ((index + 0.5) / total) * (endAngle - startAngle);
}

export function polarToCartesian(centerX, centerY, radius, angle) {
  return { x: centerX + radius * Math.cos(angle), y: centerY + radius * Math.sin(angle) };
}

function boxesOverlap(first, second, minGap) {
  const horizontal = Math.abs(first.x - second.x) < (nodeWidth(first) + nodeWidth(second)) / 2 + minGap;
  const vertical = Math.abs(first.y - second.y) < (nodeHeight(first) + nodeHeight(second)) / 2 + minGap;
  return horizontal && vertical;
}

export function hasNodeOverlap(nodes, minGap = 0) {
  for (let first = 0; first < nodes.length; first += 1) {
    for (let second = first + 1; second < nodes.length; second += 1) {
      if (boxesOverlap(nodes[first], nodes[second], minGap)) return true;
    }
  }
  return false;
}

function relationOrder(nodes, links) {
  const order = new Map();
  nodes.forEach((node, index) => order.set(node.id, index));
  links.forEach((link) => {
    if (!order.has(link.source) || !order.has(link.target)) return;
    order.set(link.target, order.get(link.source) + (order.get(link.target) + 1) / (nodes.length + 1));
  });
  return order;
}

function placeRing(batch, radius, center, startAngle = -Math.PI / 2) {
  return batch.map((node, index) => {
    const angle = computeNodeAngle(startAngle, startAngle + TAU, index, batch.length);
    return { ...node, ...polarToCartesian(center, center, radius, angle), angle };
  });
}

function fitRingWithoutOverlap(batch, initialRadius, center, alreadyPlaced, minGap) {
  let radius = Math.max(1, initialRadius);
  let placed = placeRing(batch, radius, center);
  const step = Math.max(8, Math.min(...batch.map((node) => nodeHeight(node))) / 2);
  let guard = 0;
  while ((hasNodeOverlap(placed, minGap) || placed.some((node) => alreadyPlaced.some((other) => boxesOverlap(node, other, minGap)))) && guard < 2000) {
    radius += step;
    placed = placeRing(batch, radius, center);
    guard += 1;
  }
  return { radius, nodes: placed };
}

/** 配置化径向布局：每个语义层共享全局轨道，外轨道按实际半径获得更大容量。 */
export function layoutOntologyRadial(graph, options = {}) {
  const {
    selectedLayers = ONTOLOGY_LAYER_DEFINITIONS.map((layer) => layer.key),
    minGap = 18,
    layerGap = 28,
    padding = 32,
    hoverScale = 1.12,
  } = options;
  const selected = new Set(selectedLayers);
  const sourceNodes = (graph?.nodes || []).filter((node) => selected.has(node.layer));
  if (!sourceNodes.length) return null;
  const visibleIds = new Set(sourceNodes.map((node) => node.id));
  const links = (graph?.links || []).filter((link) => visibleIds.has(link.source) && visibleIds.has(link.target));
  const order = relationOrder(sourceNodes, links);
  const configuredLayers = ONTOLOGY_LAYER_DEFINITIONS.filter((layer) => selected.has(layer.key));
  const maxWidth = Math.max(...sourceNodes.map((node) => nodeWidth(node)));
  const estimatedRadius = Math.max(80, sourceNodes.length * (maxWidth + minGap) / TAU / Math.max(1, configuredLayers.length));
  const center = Math.max(estimatedRadius * 2, 600);
  const placed = [];
  const tracks = [];
  let previousRadius = 0;
  let previousHeight = 0;

  configuredLayers.forEach((definition) => {
    let remaining = sourceNodes
      .filter((node) => node.layer === definition.key)
      .sort((first, second) => (order.get(first.id) || 0) - (order.get(second.id) || 0));
    if (!remaining.length) return;
    const layerWidth = Math.max(...remaining.map((node) => nodeWidth(node)));
    const layerHeight = Math.max(...remaining.map((node) => nodeHeight(node)));
    let radius = computeRingRadius(previousRadius, previousHeight, layerHeight, previousRadius ? layerGap : minGap);
    let trackIndex = 0;
    while (remaining.length) {
      const capacity = computeTrackCapacity(radius, TAU, layerWidth, minGap);
      const batch = remaining.slice(0, capacity);
      remaining = remaining.slice(batch.length);
      const fitted = fitRingWithoutOverlap(batch, radius, center, placed, minGap);
      radius = fitted.radius;
      placed.push(...fitted.nodes.map((node) => ({ ...node, trackIndex })));
      tracks.push({ layer: definition.key, trackIndex, radius, capacity, count: batch.length });
      previousRadius = radius;
      previousHeight = layerHeight;
      radius = computeRingRadius(previousRadius, previousHeight, layerHeight, minGap);
      trackIndex += 1;
    }
  });

  const minX = Math.min(...placed.map((node) => node.x - nodeWidth(node) * hoverScale / 2));
  const maxX = Math.max(...placed.map((node) => node.x + nodeWidth(node) * hoverScale / 2));
  const minY = Math.min(...placed.map((node) => node.y - nodeHeight(node) * hoverScale / 2));
  const maxY = Math.max(...placed.map((node) => node.y + nodeHeight(node) * hoverScale / 2));
  const naturalWidth = maxX - minX + padding * 2;
  const naturalHeight = maxY - minY + padding * 2;
  const shiftX = padding - minX;
  const shiftY = padding - minY;
  const nodes = placed.map((node) => ({ ...node, x: node.x + shiftX, y: node.y + shiftY, children: undefined }));
  const boundaryAnchors = [
    { id: "ontology:bounds:top-left", layoutAnchor: true, name: "", x: 0, y: 0, symbolSize: 0, silent: true, itemStyle: { opacity: 0 }, label: { show: false } },
    { id: "ontology:bounds:bottom-right", layoutAnchor: true, name: "", x: naturalWidth, y: naturalHeight, symbolSize: 0, silent: true, itemStyle: { opacity: 0 }, label: { show: false } },
  ];
  return { nodes, links, boundaryAnchors, naturalWidth, naturalHeight, tracks };
}

export function computeFitScale(naturalWidth, naturalHeight, viewportWidth, viewportHeight, inset = 12) {
  return Math.min(
    Math.max(1, viewportWidth - inset * 2) / Math.max(1, naturalWidth),
    Math.max(1, viewportHeight - inset * 2) / Math.max(1, naturalHeight),
  );
}

export function scaledTypography(baseFontSize, fitScale, roamZoom, maxScale = 1.8) {
  return Math.max(1, baseFontSize * fitScale * Math.min(Math.max(0.05, roamZoom), maxScale));
}
