import { $, log } from "./dom.js";
import { state } from "./state.js";
import { callTool, ownerArgs, preview, nodeStyle, edgeClass } from "./api.js";

/** @type {cytoscape.Core} */
export let cy;

export function setBusy(busy, label = "Calling tool…") {
  state.busy = busy;
  const btn = $("btn-run-tool");
  if (btn) {
    btn.disabled = busy;
    btn.classList.toggle("is-busy", busy);
  }
  const banner = $("busy-banner");
  if (banner) {
    banner.hidden = !busy;
    banner.textContent = label;
  }
}

export function markSeeds(seedList) {
  state.seedIds.clear();
  for (const s of seedList || []) {
    const id = s?.node_id || s;
    if (id) state.seedIds.add(String(id));
  }
}

export function applySeedClasses() {
  cy.nodes().forEach((ele) => {
    if (state.seedIds.has(ele.id())) ele.addClass("seed");
    else ele.removeClass("seed");
  });
}

export function mergeTriplets(triplets) {
  const nodes = [];
  const edges = [];
  for (const t of triplets || []) {
    if (t.subject_id) {
      nodes.push({
        node_id: t.subject_id,
        node_type: "Entity",
        text: t.subject || t.subject_id,
      });
    }
    if (t.object_id) {
      nodes.push({
        node_id: t.object_id,
        node_type: "Entity",
        text: t.object || t.object_id,
      });
    }
    if (t.subject_id && t.object_id) {
      edges.push({
        from_id: t.subject_id,
        to_id: t.object_id,
        relation_type: t.predicate || "RELATED",
      });
    }
  }
  mergeNodes(nodes, { fresh: true });
  mergeEdges(edges);
}

export function mergeNodes(nodes, meta = {}) {
  for (const n of nodes || []) {
    const id = n.node_id;
    if (!id) continue;
    const prev = state.nodes.get(id) || {};
    state.nodes.set(id, {
      ...prev,
      node_id: id,
      node_type: n.node_type || prev.node_type || "Fact",
      text: n.text ?? prev.text,
      status: n.status ?? prev.status,
      similarity: meta.similarity ?? n.similarity ?? n.score ?? prev.similarity,
      metadata: n.metadata ?? prev.metadata,
      degree: n.degree ?? prev.degree,
      _fresh: meta.fresh !== false,
    });
  }
}

export function mergeEdges(edges, { path = false } = {}) {
  for (const e of edges || []) {
    const from = e.from_id;
    const to = e.to_id;
    if (!from || !to) continue;
    const key = `${from}|${e.relation_type || "?"}|${to}`;
    state.edges.set(key, {
      from_id: from,
      to_id: to,
      relation_type: e.relation_type || "RELATED",
    });
    if (path) state.pathEdgeKeys.add(key);
  }
}

export function edgesFromTrace(nodes, relations) {
  const edges = [];
  for (let i = 0; i < (relations || []).length; i++) {
    const a = nodes[i];
    const b = nodes[i + 1];
    if (!a?.node_id || !b?.node_id) continue;
    edges.push({
      from_id: a.node_id,
      to_id: b.node_id,
      relation_type: relations[i].relation_type || "RELATED",
    });
  }
  return edges;
}

export function clearPathHighlight() {
  state.pathEdgeKeys.clear();
}

export function mergeToolResult(data, meta = {}, syncOpts = {}) {
  mergeNodes(data.nodes, meta);
  mergeNodes(data.similar_facts, { ...meta, fresh: true });
  mergeNodes(data.results, meta);
  mergeNodes(data.facts, meta);
  mergeNodes(data.entities, meta);
  mergeNodes(data.seeds, meta);
  if (data.node) mergeNodes([data.node], meta);
  mergeEdges(data.edges);
  for (const p of data.paths || []) {
    mergeNodes(p.nodes, { fresh: true });
    mergeEdges(edgesFromTrace(p.nodes || [], p.relations || []), { path: true });
  }
  syncGraph(syncOpts);
  updateStats();
}

export function nodeElementDef(n) {
  return {
    group: "nodes",
    data: {
      id: n.node_id,
      label: preview(n.text, 36),
      nodeType: n.node_type,
      status: n.status || "active",
      fullText: n.text || "",
      similarity: n.similarity,
      degree: n.degree || 0,
    },
    classes: n._fresh ? "fresh" : "",
  };
}

export function edgeElementDef(e, key) {
  const id = `${e.from_id}-${e.relation_type}-${e.to_id}`;
  const classes = [edgeClass(e.relation_type)];
  if (state.pathEdgeKeys.has(key || `${e.from_id}|${e.relation_type}|${e.to_id}`)) {
    classes.push("edge-path");
  }
  return {
    group: "edges",
    data: {
      id,
      source: e.from_id,
      target: e.to_id,
      label: e.relation_type,
    },
    classes: classes.join(" "),
  };
}

export function viewportCenter() {
  const pan = cy.pan();
  const zoom = cy.zoom();
  return {
    x: (cy.width() / 2 - pan.x) / zoom,
    y: (cy.height() / 2 - pan.y) / zoom,
  };
}

export function placeNearNode(originId, index) {
  const origin = cy.getElementById(originId);
  if (origin.empty()) return undefined;
  const pos = origin.position();
  const angle = ((index * 53) % 360) * (Math.PI / 180);
  const ring = Math.floor(index / 7);
  const radius = 72 + ring * 48;
  return {
    x: pos.x + radius * Math.cos(angle),
    y: pos.y + radius * Math.sin(angle),
  };
}

export function layoutOptions(name) {
  const common = {
    animate: true,
    animationDuration: 280,
    fit: true,
    padding: 48,
  };
  const root = state.anchorId || state.selectedId;
  switch (name) {
    case "circle":
      return { name: "circle", ...common };
    case "concentric":
      return {
        name: "concentric",
        ...common,
        concentric: (n) => {
          if (root && n.id() === root) return 1000;
          return n.degree();
        },
        levelWidth: () => 2,
        minNodeSpacing: 28,
      };
    case "breadthfirst":
      return {
        name: "breadthfirst",
        ...common,
        directed: true,
        roots: root ? `#${CSS.escape(root)}` : undefined,
        spacingFactor: 1.15,
      };
    case "grid":
      return { name: "grid", ...common, condense: true };
    case "cose-bilkent-fallback":
      return {
        name: "cose",
        ...common,
        nodeRepulsion: 8000,
        idealEdgeLength: 90,
        gravity: 0.2,
        numIter: 900,
      };
    case "cose":
    default:
      return {
        name: "cose",
        ...common,
        nodeRepulsion: 4500,
        idealEdgeLength: 70,
        gravity: 0.25,
        numIter: 600,
      };
  }
}

export function runLayout(name = state.layoutName) {
  state.layoutName = name;
  localStorage.setItem("gm_layout", name);
  $("layout-mode").value = name;
  if (cy.nodes().length < 2) {
    cy.fit(undefined, 40);
    return;
  }
  cy.layout(layoutOptions(name)).run();
  log(`layout: ${name}`);
}

export function graphCenterModel() {
  const nodes = cy.nodes(":visible");
  if (nodes.empty()) return viewportCenter();
  const bb = nodes.boundingBox();
  return { x: (bb.x1 + bb.x2) / 2, y: (bb.y1 + bb.y2) / 2 };
}

export function rotateGraphAround(degrees, cx, cy0) {
  const nodes = cy.nodes(":visible");
  if (nodes.empty()) return;
  const rad = (degrees * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  nodes.positions((ele) => {
    const p = ele.position();
    const dx = p.x - cx;
    const dy = p.y - cy0;
    return {
      x: cx + dx * cos - dy * sin,
      y: cy0 + dx * sin + dy * cos,
    };
  });
}

export function rotateGraph(degrees) {
  const c = graphCenterModel();
  rotateGraphAround(degrees, c.x, c.y);
  log(`rotate ${degrees > 0 ? "+" : ""}${degrees}°`);
}

export function renderedToModel(renderedX, renderedY) {
  const pan = cy.pan();
  const zoom = cy.zoom();
  return {
    x: (renderedX - pan.x) / zoom,
    y: (renderedY - pan.y) / zoom,
  };
}

export function angleFromCenter(modelX, modelY, cx, cy0) {
  return Math.atan2(modelY - cy0, modelX - cx);
}

export function syncGraph({ fullLayout = false, originNodeId = null } = {}) {
  let newIndex = 0;

  for (const n of state.nodes.values()) {
    const id = n.node_id;
    let ele = cy.getElementById(id);
    if (ele.empty()) {
      const def = nodeElementDef(n);
      if (cy.nodes().length === 0) {
        def.position = viewportCenter();
      } else if (originNodeId && id !== originNodeId) {
        def.position = placeNearNode(originNodeId, newIndex++);
      }
      ele = cy.add(def);
    } else {
      ele.data("label", preview(n.text, 36));
      ele.data("nodeType", n.node_type);
      ele.data("status", n.status || "active");
      ele.data("fullText", n.text || "");
      ele.data("degree", n.degree || ele.degree());
      if (n._fresh) ele.addClass("fresh");
      else ele.removeClass("fresh");
    }
    if (state.seedIds.has(id)) ele.addClass("seed");
    else ele.removeClass("seed");
  }

  for (const [key, e] of state.edges) {
    const def = edgeElementDef(e, key);
    let ele = cy.getElementById(def.data.id);
    if (ele.empty()) {
      if (cy.getElementById(e.from_id).nonempty() && cy.getElementById(e.to_id).nonempty()) {
        cy.add(def);
      }
    } else {
      ele.removeClass(
        "edge-contradicts edge-summarizes edge-triplet edge-default edge-path",
      );
      ele.addClass(def.classes);
    }
  }

  applyNodeColors();
  applySeedClasses();
  applyViewFilters();
  applyLabelVisibility();
  cy.nodes().forEach((n) => n.lock(state.nodesLocked));

  if (fullLayout && cy.nodes(":visible").length > 1) {
    runLayout(state.layoutName);
  }

  for (const n of state.nodes.values()) n._fresh = false;
}

export function applyNodeColors() {
  cy.nodes().forEach((ele) => {
    const st = nodeStyle(ele.data("nodeType"), ele.data("status"));
    ele.style({ backgroundColor: st.background, shape: st.shape });
  });
}

export function applyViewFilters() {
  const showFact = $("view-fact").checked;
  const showEntity = $("view-entity").checked;
  const showActive = $("view-active").checked;
  const showOutdated = $("view-outdated").checked;
  const showArchived = $("view-archived").checked;

  cy.batch(() => {
    cy.nodes().forEach((ele) => {
      const type = ele.data("nodeType") || "Fact";
      const status = ele.data("status") || "active";
      const typeOk =
        (type === "Fact" && showFact) || (type === "Entity" && showEntity);
      const statusOk =
        (status === "active" && showActive) ||
        (status === "outdated" && showOutdated) ||
        (status === "archived" && showArchived) ||
        (!["active", "outdated", "archived"].includes(status) && showActive);
      if (typeOk && statusOk) ele.removeClass("filtered-out");
      else ele.addClass("filtered-out");
    });
    cy.edges().forEach((ele) => {
      const src = ele.source();
      const tgt = ele.target();
      if (src.hasClass("filtered-out") || tgt.hasClass("filtered-out")) {
        ele.addClass("filtered-out");
      } else {
        ele.removeClass("filtered-out");
      }
    });
  });
}

export function applyLabelVisibility() {
  const nodeLabels = $("view-node-labels").checked;
  const edgeLabels = $("view-edge-labels").checked;
  cy.style()
    .selector("node")
    .style("label", nodeLabels ? "data(label)" : "")
    .selector("edge")
    .style("label", edgeLabels ? "data(label)" : "")
    .update();
}

export function centerViewOnNode(nodeId) {
  const node = cy.getElementById(nodeId);
  if (node.empty()) return;
  cy.animate({ center: { eles: node }, duration: 200 });
}

export function updateStats() {
  const vis = cy.nodes(":visible").length;
  $("stats-bar").textContent = `${state.nodes.size} nodes · ${state.edges.size} edges · ${vis} visible · ${state.layoutName}`;
}

export function clearGraph({ quiet = false } = {}) {
  cy.elements().remove();
  state.nodes.clear();
  state.edges.clear();
  state.neighborState.clear();
  state.seedIds.clear();
  state.pathEdgeKeys.clear();
  state.selectedId = null;
  updateStats();
  $("detail").hidden = true;
  $("detail-empty").hidden = false;
  $("detail-history").innerHTML = "";
  $("neighbor-list").innerHTML = "";
  $("neighbor-status").textContent = "Not loaded yet.";
  $("btn-neighbors-more").hidden = true;
  $("sel-action").hidden = true;
  if (!quiet) log("graph cleared");
}

export function exportPng() {
  const png = cy.png({ full: true, scale: 2, bg: "#111820" });
  const a = document.createElement("a");
  a.href = png;
  a.download = `graph-memory-${Date.now()}.png`;
  a.click();
  log("exported PNG");
}

export function exportJson() {
  const payload = {
    exported_at: new Date().toISOString(),
    owner_id: $("owner-id").value.trim() || "default",
    layout: state.layoutName,
    seed_ids: [...state.seedIds],
    nodes: [...state.nodes.values()].map((n) => ({
      node_id: n.node_id,
      node_type: n.node_type,
      text: n.text,
      status: n.status,
      similarity: n.similarity,
      metadata: n.metadata,
      seed: state.seedIds.has(n.node_id),
    })),
    edges: [...state.edges.values()],
    last_tool: state.lastToolResponse
      ? { tool: state.lastToolResponse.tool, arguments: state.lastToolResponse.args }
      : null,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `graph-memory-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
  log(`exported JSON (${payload.nodes.length} nodes, ${payload.edges.length} edges)`);
}

export function toggleLock() {
  state.nodesLocked = !state.nodesLocked;
  cy.nodes().forEach((n) => n.lock(state.nodesLocked));
  const btn = $("btn-lock");
  btn.textContent = state.nodesLocked ? "🔒" : "🔓";
  btn.classList.toggle("active-lock", state.nodesLocked);
  log(state.nodesLocked ? "nodes locked" : "nodes unlocked");
}


export function initCy() {
cy = cytoscape({
  container: $("cy"),
  elements: [],
  wheelSensitivity: 0.25,
  minZoom: 0.15,
  maxZoom: 3.5,
  style: [
    {
      selector: "node",
      style: {
        label: "data(label)",
        "font-size": 9,
        color: "#e2e8f0",
        "text-valign": "bottom",
        "text-margin-y": 4,
        "text-wrap": "ellipsis",
        "text-max-width": 90,
        width: 28,
        height: 28,
        "border-width": 2,
        "border-color": "#334155",
        "transition-property": "border-color, border-width, opacity",
        "transition-duration": "120ms",
      },
    },
    {
      selector: "node.fresh",
      style: { "border-color": "#3b82f6", "border-width": 3 },
    },
    {
      selector: "node.seed",
      style: {
        "border-color": "#f472b6",
        "border-width": 4,
        width: 34,
        height: 34,
        "background-blacken": -0.05,
      },
    },
    {
      selector: "node:selected",
      style: { "border-color": "#fbbf24", "border-width": 3 },
    },
    {
      selector: "node.seed:selected",
      style: { "border-color": "#fbbf24", "border-width": 4 },
    },
    {
      selector: "node.filtered-out",
      style: { display: "none" },
    },
    {
      selector: "edge",
      style: {
        width: 1.5,
        "line-color": "#475569",
        "target-arrow-shape": "triangle",
        "target-arrow-color": "#475569",
        "curve-style": "bezier",
        label: "data(label)",
        "font-size": 8,
        color: "#94a3b8",
        "text-rotation": "autorotate",
        opacity: 0.95,
      },
    },
    {
      selector: "edge.edge-contradicts",
      style: {
        width: 2.5,
        "line-color": "#ef4444",
        "target-arrow-color": "#ef4444",
        color: "#fca5a5",
      },
    },
    {
      selector: "edge.edge-summarizes",
      style: {
        width: 2,
        "line-color": "#22d3ee",
        "target-arrow-color": "#22d3ee",
        color: "#a5f3fc",
      },
    },
    {
      selector: "edge.edge-triplet",
      style: {
        width: 2,
        "line-color": "#f59e0b",
        "target-arrow-color": "#f59e0b",
        color: "#fcd34d",
      },
    },
    {
      selector: "edge.edge-path",
      style: {
        width: 3.5,
        "line-color": "#fbbf24",
        "target-arrow-color": "#fbbf24",
        "line-style": "solid",
      },
    },
    {
      selector: "edge.filtered-out",
      style: { display: "none" },
    },
  ],
  layout: { name: "preset", animate: false },
});
  return cy;
}


export function updateSelAction() {
  const bar = $("sel-action");
  if (!state.selectedId) {
    bar.hidden = true;
    return;
  }
  const node = cy.getElementById(state.selectedId);
  if (node.empty()) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;
  const bb = node.renderedBoundingBox({
    includeLabels: false,
    includeOverlays: false,
  });
  bar.style.left = `${(bb.x1 + bb.x2) / 2}px`;
  bar.style.top = `${bb.y2 + 8}px`;
}
