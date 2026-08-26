import React, { useEffect, useRef, useState } from "react";
import Sigma from "sigma";
import { buildGraphologyGraph } from "./ontologyGraphModel.js";
import { layoutOntologyForceAtlas } from "./ontologyForceLayout.js";

const ATTRIBUTE_LABEL_RATIO = 0.58;

export default function OntologySigmaPreview({ data, appliedLayers }) {
  const containerRef = useRef(null);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [layoutRunning, setLayoutRunning] = useState(true);

  useEffect(() => {
    let disposed = false;
    let renderer = null;
    let observer = null;
    let layoutTimer = null;
    let doubleClickHandler = null;
    setLayoutRunning(true);
    layoutTimer = window.setTimeout(() => {
      if (disposed || !containerRef.current) return;
      const graph = buildGraphologyGraph(data, appliedLayers);
      layoutOntologyForceAtlas(graph);
      if (disposed || !containerRef.current) return;

      let hoveredNode = null;
      let selectedNode = null;
      let selectedNeighbors = new Set();
      let cameraRatio = 1;
      renderer = new Sigma(graph, containerRef.current, {
        allowInvalidContainer: false,
        defaultNodeColor: "#64748b",
        defaultEdgeColor: "#cbd5e1",
        labelColor: { color: "#334155" },
        labelFont: '"PingFang SC", -apple-system, sans-serif',
        labelSize: 12,
        labelWeight: "500",
        labelRenderedSizeThreshold: 5,
        renderEdgeLabels: false,
        hideEdgesOnMove: graph.order > 700,
        stagePadding: 24,
        zIndex: true,
        minCameraRatio: 0.08,
        maxCameraRatio: 8,
        nodeReducer: (node, attributes) => {
          const highlighted = node === hoveredNode || node === selectedNode || selectedNeighbors.has(node);
          const dimmed = selectedNode && !highlighted;
          const alwaysLabel = ["businessObject", "logicalEntity", "metric", "businessRule"].includes(attributes.nodeType);
          const attributeLabel = attributes.nodeType === "businessAttribute" && (highlighted || cameraRatio < ATTRIBUTE_LABEL_RATIO);
          return {
            ...attributes,
            label: alwaysLabel || attributeLabel ? attributes.label : "",
            color: dimmed ? "#cbd5e1" : attributes.color,
            size: attributes.size * (node === hoveredNode || node === selectedNode ? 1.28 : 1),
            zIndex: highlighted ? 2 : 1,
            forceLabel: Boolean(highlighted || attributes.nodeType === "businessObject"),
          };
        },
        edgeReducer: (edge, attributes) => {
          const [source, target] = graph.extremities(edge);
          const highlighted = selectedNode && (source === selectedNode || target === selectedNode);
          return {
            ...attributes,
            color: selectedNode ? (highlighted ? "#475569" : "#e2e8f0") : attributes.color,
            size: attributes.size * (highlighted ? 1.7 : 1),
            zIndex: highlighted ? 2 : 0,
          };
        },
      });

      const refresh = () => renderer?.refresh();
      renderer.on("enterNode", ({ node }) => { hoveredNode = node; refresh(); });
      renderer.on("leaveNode", () => { hoveredNode = null; refresh(); });
      renderer.on("clickNode", ({ node, event }) => {
        event.preventSigmaDefault?.();
        selectedNode = node;
        selectedNeighbors = new Set(graph.neighbors(node));
        refresh();
      });
      renderer.on("clickStage", () => {
        selectedNode = null;
        selectedNeighbors = new Set();
        refresh();
      });
      const camera = renderer.getCamera();
      camera.on("updated", (state) => {
        const nextRatio = Number(state.ratio) || 1;
        if ((cameraRatio < ATTRIBUTE_LABEL_RATIO) !== (nextRatio < ATTRIBUTE_LABEL_RATIO)) {
          cameraRatio = nextRatio;
          refresh();
        } else cameraRatio = nextRatio;
      });
      camera.animatedReset({ duration: 300 });

      doubleClickHandler = (event) => {
        event.preventDefault();
        event.stopPropagation();
      };
      containerRef.current.addEventListener("dblclick", doubleClickHandler, { capture: true });
      observer = new ResizeObserver(() => renderer?.resize());
      observer.observe(containerRef.current);
      setLayoutRunning(false);
    }, 0);

    return () => {
      disposed = true;
      if (layoutTimer !== null) window.clearTimeout(layoutTimer);
      observer?.disconnect();
      if (containerRef.current && doubleClickHandler) containerRef.current.removeEventListener("dblclick", doubleClickHandler, { capture: true });
      renderer?.kill();
    };
  }, [data, appliedLayers, layoutVersion]);

  return <div className="ontology-sigma-shell">
    <div className="ontology-sigma-actions"><span>ForceAtlas2 Beta</span><button type="button" disabled={layoutRunning} onClick={() => setLayoutVersion((value) => value + 1)}>{layoutRunning ? "布局中…" : "重新布局"}</button></div>
    <div className="ontology-sigma-preview" ref={containerRef} aria-label="Sigma ForceAtlas2 本体网络图" />
  </div>;
}
