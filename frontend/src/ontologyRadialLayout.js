const TAU = Math.PI * 2;

export const ONTOLOGY_LAYER_DEFINITIONS = [
  { key: "businessObject", label: "业务对象", baseRadius: 88 },
  { key: "logicalEntity", label: "逻辑实体", baseRadius: 188 },
  { key: "businessAttribute", label: "业务属性", baseRadius: 300 },
  { key: "metric", label: "指标", baseRadius: 412 },
  { key: "businessRule", label: "业务规则", baseRadius: 524 },
];

export const nodeWidth = (node) => Array.isArray(node?.symbolSize) ? Number(node.symbolSize[0]) || 92 : Number(node?.symbolSize) || 92;
export const nodeHeight = (node) => Array.isArray(node?.symbolSize) ? Number(node.symbolSize[1]) || 38 : Number(node?.symbolSize) || 38;

export function computeTrackCapacity(radius, angularSpan = TAU, width = 92, minGap = 18) {
  return Math.max(1, Math.floor(Math.max(1, radius) * Math.max(0.01, angularSpan) / Math.max(1, width + minGap)));
}

export function computeTrackCount(count, radius, angularSpan = TAU, width = 92, minGap = 18) {
  return Math.max(1, Math.ceil(Math.max(0, count) / computeTrackCapacity(radius, angularSpan, width, minGap)));
}

export function computeRingRadius(previousRadius, previousHeight, currentHeight, minGap = 18) {
  return previousRadius + previousHeight / 2 + currentHeight / 2 + minGap;
}

export function computeNodeAngle(start, end, index, count) {
  return start + (end - start) * ((index + 0.5) / Math.max(1, count));
}

export function polarToCartesian(centerX, centerY, radius, angle) {
  return { x: centerX + radius * Math.cos(angle), y: centerY + radius * Math.sin(angle) };
}

export function computeSectorAngles(groups, gap = 0.035, startAngle = -Math.PI / 2) {
  if (!groups.length) return [];
  const safeGap = Math.min(gap, TAU / groups.length / 3);
  const usable = TAU - safeGap * groups.length;
  const weighted = groups.map((group) => ({ ...group, weight: Math.max(1, Number(group.weight) || Math.sqrt(Math.max(1, group.count || 1))) }));
  const totalWeight = weighted.reduce((sum, group) => sum + group.weight, 0);
  let cursor = startAngle;
  return weighted.map((group) => {
    const span = usable * group.weight / totalWeight;
    const sector = { ...group, start: cursor, end: cursor + span, span };
    cursor += span + safeGap;
    return sector;
  });
}

function boxesOverlap(a, b, minGap = 0) {
  return Math.abs(a.x - b.x) < (nodeWidth(a) + nodeWidth(b)) / 2 + minGap
    && Math.abs(a.y - b.y) < (nodeHeight(a) + nodeHeight(b)) / 2 + minGap;
}

export function hasNodeOverlap(nodes, minGap = 0) {
  for (let left = 0; left < nodes.length; left += 1) {
    for (let right = left + 1; right < nodes.length; right += 1) {
      if (boxesOverlap(nodes[left], nodes[right], minGap)) return true;
    }
  }
  return false;
}

function placeSectorTrack(batches, radius, trackIndex) {
  return batches.flatMap(({ sector, nodes }) => nodes.map((node, index) => {
    const angle = computeNodeAngle(sector.start, sector.end, index, nodes.length);
    const point = polarToCartesian(0, 0, radius, angle);
    return { ...node, ...point, angle, trackIndex };
  }));
}

function fitSectorTrackWithoutOverlap(batches, initialRadius, alreadyPlaced, minGap, trackIndex) {
  const maxHeight = Math.max(...batches.flatMap((batch) => batch.nodes).map(nodeHeight), 38);
  let radius = Math.max(1, initialRadius);
  for (let attempt = 0; attempt < 400; attempt += 1) {
    const nodes = placeSectorTrack(batches, radius, trackIndex);
    if (!hasNodeOverlap(nodes, minGap) && !nodes.some((node) => alreadyPlaced.some((placed) => boxesOverlap(node, placed, minGap)))) {
      return { radius, nodes };
    }
    radius += Math.max(8, maxHeight / 3);
  }
  return { radius, nodes: placeSectorTrack(batches, radius, trackIndex) };
}

export function layoutOntologyRadial(graph, options = {}) {
  const selected = new Set(options.selectedLayers || ONTOLOGY_LAYER_DEFINITIONS.map((layer) => layer.key));
  const minGap = options.minGap ?? 18;
  const padding = options.padding ?? 28;
  const hoverScale = options.hoverScale ?? 1.12;
  const sourceNodes = (graph?.nodes || []).filter((node) => selected.has(node.layer));
  if (!sourceNodes.length) return null;
  const visibleIds = new Set(sourceNodes.map((node) => node.id));
  const links = (graph?.links || []).filter((link) => visibleIds.has(link.source) && visibleIds.has(link.target));

  const sectorCounts = new Map();
  sourceNodes.forEach((node) => {
    const sectorId = node.sectorId || `ontology:${node.layer}`;
    sectorCounts.set(sectorId, (sectorCounts.get(sectorId) || 0) + 1);
  });
  const sectorOrder = [];
  sourceNodes.filter((node) => node.layer === "businessObject").forEach((node) => {
    const id = node.sectorId || node.id;
    if (!sectorOrder.includes(id)) sectorOrder.push(id);
  });
  sourceNodes.forEach((node) => {
    const id = node.sectorId || `ontology:${node.layer}`;
    if (!sectorOrder.includes(id)) sectorOrder.push(id);
  });
  const sectors = computeSectorAngles(sectorOrder.map((id) => ({ id, count: sectorCounts.get(id) || 1, weight: Math.sqrt(sectorCounts.get(id) || 1) })));
  const sectorMap = new Map(sectors.map((sector) => [sector.id, sector]));

  const placed = [];
  const tracks = [];
  let previousRadius = 0;
  let previousHeight = 0;
  for (const definition of ONTOLOGY_LAYER_DEFINITIONS) {
    if (!selected.has(definition.key)) continue;
    const layerNodes = sourceNodes.filter((node) => node.layer === definition.key);
    if (!layerNodes.length) continue;
    const remaining = new Map(sectorOrder.map((id) => [id, layerNodes.filter((node) => (node.sectorId || `ontology:${node.layer}`) === id)]));
    let radius = Math.max(definition.baseRadius, computeRingRadius(previousRadius, previousHeight, Math.max(...layerNodes.map(nodeHeight)), minGap));
    let trackIndex = 0;
    while ([...remaining.values()].some((nodes) => nodes.length)) {
      const batches = [];
      let capacity = 0;
      for (const sectorId of sectorOrder) {
        const queue = remaining.get(sectorId);
        if (!queue?.length) continue;
        const sector = sectorMap.get(sectorId);
        const width = Math.max(...queue.map(nodeWidth));
        const sectorCapacity = computeTrackCapacity(radius, sector.span, width, minGap);
        const nodes = queue.splice(0, sectorCapacity);
        capacity += sectorCapacity;
        batches.push({ sector, nodes });
      }
      const fitted = fitSectorTrackWithoutOverlap(batches, radius, placed, minGap, trackIndex);
      fitted.nodes.forEach((node) => placed.push(node));
      tracks.push({ layer: definition.key, trackIndex, radius: fitted.radius, capacity, count: fitted.nodes.length });
      previousRadius = fitted.radius;
      previousHeight = Math.max(...fitted.nodes.map(nodeHeight));
      radius = computeRingRadius(previousRadius, previousHeight, previousHeight, minGap);
      trackIndex += 1;
    }
  }

  const minX = Math.min(...placed.map((node) => node.x - nodeWidth(node) * hoverScale / 2));
  const maxX = Math.max(...placed.map((node) => node.x + nodeWidth(node) * hoverScale / 2));
  const minY = Math.min(...placed.map((node) => node.y - nodeHeight(node) * hoverScale / 2));
  const maxY = Math.max(...placed.map((node) => node.y + nodeHeight(node) * hoverScale / 2));
  const naturalWidth = maxX - minX + padding * 2;
  const naturalHeight = maxY - minY + padding * 2;
  const nodes = placed.map((node) => ({ ...node, x: node.x - minX + padding, y: node.y - minY + padding }));
  const boundaryAnchors = [
    { id: "ontology:boundary:start", x: 0, y: 0, layoutAnchor: true, symbolSize: 0 },
    { id: "ontology:boundary:end", x: naturalWidth, y: naturalHeight, layoutAnchor: true, symbolSize: 0 },
  ];
  return { nodes, links, tracks, sectors, boundaryAnchors, naturalWidth, naturalHeight };
}

export function computeFitScale(naturalWidth, naturalHeight, viewportWidth, viewportHeight, padding = 20) {
  const width = Math.max(1, viewportWidth - padding * 2);
  const height = Math.max(1, viewportHeight - padding * 2);
  return Math.min(width / Math.max(1, naturalWidth), height / Math.max(1, naturalHeight));
}

export function scaledTypography(baseSize, fitScale, roamZoom, maxZoom = 1.8) {
  return baseSize * fitScale * Math.min(Math.max(0.1, roamZoom), maxZoom);
}
