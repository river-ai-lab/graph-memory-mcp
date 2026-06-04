/* Graph Memory Explorer — client-side graph merge + Cytoscape */

const state = {
  ownerId: localStorage.getItem("gm_owner_id") || "default",
  anchorId: null,
  depth: 1,
  nodes: new Map(),
  edges: new Map(),
  neighborOffset: new Map(),
  selectedId: null,
  hoverId: null,
};

const $ = (id) => document.getElementById(id);

function log(msg) {
  const el = $("log");
  const line = `[${new Date().toLocaleTimeString()}] ${msg}`;
  el.textContent = `${line}\n${el.textContent}`.slice(0, 4000);
}

async function callTool(tool, arguments_) {
  const res = await fetch("/api/tool", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool, arguments: arguments_ }),
  });
  const data = await res.json();
  if (!res.ok || data.success === false) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

function ownerArgs(extra = {}) {
  return { owner_id: $("owner-id").value.trim() || "default", ...extra };
}

function preview(text, n = 48) {
  if (!text) return "(empty)";
  const s = String(text).replace(/\s+/g, " ").trim();
  return s.length <= n ? s : `${s.slice(0, n)}…`;
}

function nodeStyle(nodeType, status) {
  const base =
    nodeType === "Entity"
      ? { background: "#7c3aed", shape: "diamond" }
      : { background: "#16a34a", shape: "ellipse" };
  if (status === "outdated") base.background = "#64748b";
  if (status === "archived") base.background = "#475569";
  return base;
}

function mergeNodes(nodes, meta = {}) {
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
      similarity: meta.similarity ?? n.similarity ?? prev.similarity,
      metadata: n.metadata ?? prev.metadata,
      _fresh: meta.fresh !== false,
    });
  }
}

function mergeEdges(edges) {
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
  }
}

function mergeToolResult(data, meta = {}, syncOpts = {}) {
  mergeNodes(data.nodes, meta);
  mergeNodes(data.similar_facts, { ...meta, fresh: true });
  mergeNodes(data.results, meta);
  mergeNodes(data.facts, meta);
  mergeNodes(data.entities, meta);
  if (data.node) mergeNodes([data.node], meta);
  mergeEdges(data.edges);
  syncGraph(syncOpts);
  updateStats();
}

function nodeElementDef(n) {
  return {
    group: "nodes",
    data: {
      id: n.node_id,
      label: preview(n.text, 36),
      nodeType: n.node_type,
      status: n.status,
      fullText: n.text || "",
      similarity: n.similarity,
    },
    classes: n._fresh ? "fresh" : "",
  };
}

function edgeElementDef(e) {
  const id = `${e.from_id}-${e.relation_type}-${e.to_id}`;
  return {
    group: "edges",
    data: {
      id,
      source: e.from_id,
      target: e.to_id,
      label: e.relation_type,
    },
  };
}

function viewportCenter() {
  const pan = cy.pan();
  const zoom = cy.zoom();
  return {
    x: (cy.width() / 2 - pan.x) / zoom,
    y: (cy.height() / 2 - pan.y) / zoom,
  };
}

function placeNearNode(originId, index) {
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

function syncGraph({ fullLayout = false, originNodeId = null } = {}) {
  const addedNodes = [];
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
      addedNodes.push(ele);
    } else {
      ele.data("label", preview(n.text, 36));
      ele.data("nodeType", n.node_type);
      ele.data("status", n.status);
      ele.data("fullText", n.text || "");
      if (n._fresh) ele.addClass("fresh");
      else ele.removeClass("fresh");
    }
  }

  for (const e of state.edges.values()) {
    const def = edgeElementDef(e);
    if (cy.getElementById(def.data.id).empty()) {
      cy.add(def);
    }
  }

  applyNodeColors();

  if (fullLayout && cy.nodes().length > 1) {
    cy.layout({
      name: "cose",
      animate: true,
      padding: 40,
      animationDuration: 250,
      fit: true,
    }).run();
  }

  for (const n of state.nodes.values()) n._fresh = false;
}

function centerViewOnNode(nodeId) {
  const node = cy.getElementById(nodeId);
  if (node.empty()) return;
  cy.animate({ center: { eles: node }, duration: 200 });
}

let cy = cytoscape({
  container: $("cy"),
  elements: [],
  style: [
    {
      selector: "node",
      style: {
        label: "data(label)",
        "font-size": 9,
        color: "#e2e8f0",
        "text-valign": "bottom",
        "text-margin-y": 4,
        width: 28,
        height: 28,
        "border-width": 2,
        "border-color": "#334155",
      },
    },
    {
      selector: "node.fresh",
      style: { "border-color": "#3b82f6", "border-width": 3 },
    },
    {
      selector: "node:selected",
      style: { "border-color": "#fbbf24", "border-width": 3 },
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
      },
    },
  ],
  layout: { name: "preset", animate: false },
});

function applyNodeColors() {
  cy.nodes().forEach((ele) => {
    const st = nodeStyle(ele.data("nodeType"), ele.data("status"));
    ele.style({ backgroundColor: st.background, shape: st.shape });
  });
}

function updateStats() {
  $("stats-bar").textContent = `${state.nodes.size} nodes · ${state.edges.size} edges`;
}

async function loadNodeDetail(nodeId) {
  const data = await callTool("get_node", ownerArgs({ node_id: nodeId }));
  mergeToolResult(data, {}, { originNodeId: nodeId });
  showDetail(nodeId, data.node);
}

function showDetail(nodeId, nodeOverride) {
  const n = nodeOverride || state.nodes.get(nodeId);
  if (!n) return;
  state.selectedId = nodeId;
  $("detail-empty").hidden = true;
  $("detail").hidden = false;
  $("detail-id").textContent = nodeId;
  $("detail-type").textContent = n.node_type || "—";
  $("detail-status").textContent = n.status || "active";
  $("detail-sim").textContent =
    n.similarity != null ? Number(n.similarity).toFixed(3) : "—";
  $("detail-text").textContent = n.text || "(no text)";

  const related = [];
  for (const e of state.edges.values()) {
    if (e.from_id === nodeId) related.push(`→ ${e.relation_type} → ${e.to_id}`);
    if (e.to_id === nodeId) related.push(`← ${e.relation_type} ← ${e.from_id}`);
  }
  $("detail-edges").innerHTML = related.length
    ? related.map((x) => `<li>${x}</li>`).join("")
    : "<li class='muted'>none in view</li>";
}

async function loadAnchor(nodeId) {
  state.anchorId = nodeId;
  $("node-id").value = nodeId;
  log(`anchor ${nodeId}`);
  const isEmpty = cy.nodes().length === 0;
  await loadNodeDetail(nodeId);
  await loadContext(nodeId, { resetOffset: true, originNodeId: nodeId });
  if (isEmpty) centerViewOnNode(nodeId);
}

async function loadContext(nodeId, opts = {}) {
  const depth = opts.depth ?? (Number($("depth").value) || 1);
  const maxNodes = Number($("max-nodes").value) || 10;
  const args = ownerArgs({
    node_id: nodeId,
    depth,
    max_nodes: maxNodes,
  });

  if (opts.resetOffset) {
    state.neighborOffset.set(nodeId, 0);
  }

  const data = await callTool("get_context", args);
  mergeToolResult(data, { fresh: true }, {
    fullLayout: opts.fullLayout === true,
    originNodeId: opts.originNodeId || nodeId,
  });
  log(`context ${nodeId} depth=${depth} nodes=${data.nodes?.length || 0}`);
  return data;
}

async function loadNeighbors(nodeId, pageSize = 10) {
  let off = state.neighborOffset.get(nodeId) ?? 0;
  const args = ownerArgs({
    node_id: nodeId,
    depth: 1,
    max_nodes: pageSize,
  });
  if (off > 0) args.offset = off;

  const data = await callTool("get_context", args);
  mergeToolResult(data, { fresh: true }, { originNodeId: nodeId });
  const returned = data.nodes?.length || 0;
  if (off > 0) {
    state.neighborOffset.set(
      nodeId,
      data.has_more ? off + pageSize : off + returned,
    );
  } else {
    state.neighborOffset.set(nodeId, pageSize);
  }
  log(`neighbors ${nodeId} offset=${off} +${returned}`);
  return data;
}

async function findSimilar() {
  const anchor = state.anchorId || $("node-id").value.trim();
  if (!anchor) {
    log("set anchor first");
    return;
  }
  const limit = Number($("similar-limit").value) || 5;
  const threshold = Number($("similar-threshold").value) || 0.55;
  const sim = await callTool(
    "find_similar",
    ownerArgs({
      fact_id: anchor,
      limit,
      similarity_threshold: threshold,
    }),
  );
  const ids = new Set([anchor, ...(sim.similar_facts || []).map((f) => f.node_id)]);
  mergeNodes(sim.similar_facts, { fresh: true });
  mergeNodes([{ node_id: anchor }], {});

  const ctx = await callTool(
    "get_context",
    ownerArgs({ node_id: anchor, depth: 2, max_nodes: 50 }),
  );
  const filteredEdges = (ctx.edges || []).filter(
    (e) => ids.has(e.from_id) && ids.has(e.to_id),
  );
  mergeEdges(filteredEdges);
  syncGraph({ originNodeId: anchor });
  log(`similar ${sim.similar_facts?.length || 0} facts + edges among them`);
}

async function textSearch() {
  const query = $("search-query").value.trim();
  if (!query) return;
  const limit = Number($("search-limit").value) || 10;
  const data = await callTool("search", ownerArgs({ query, limit }));
  mergeToolResult(data, { fresh: true }, { originNodeId: state.anchorId || null });
  log(`search "${query}" → ${data.results?.length || 0}`);
}

function clearGraph() {
  cy.elements().remove();
  state.nodes.clear();
  state.edges.clear();
  state.neighborOffset.clear();
  state.selectedId = null;
  updateStats();
  $("detail").hidden = true;
  $("detail-empty").hidden = false;
  log("graph cleared");
}

const hoverPlus = $("hover-plus");
let hidePlusTimer = null;

function positionHoverPlus(node) {
  // Body only — ignore label width/height so + stays on the node shape
  const bb = node.renderedBoundingBox({
    includeLabels: false,
    includeOverlays: false,
  });
  hoverPlus.style.left = `${bb.x2}px`;
  hoverPlus.style.top = `${bb.y1}px`;
}

function refreshHoverPlusPosition() {
  if (!state.hoverId || !hoverPlus.classList.contains("visible")) return;
  const node = cy.getElementById(state.hoverId);
  if (node.nonempty()) positionHoverPlus(node);
}

function showHoverPlus(node) {
  clearTimeout(hidePlusTimer);
  state.hoverId = node.id();
  positionHoverPlus(node);
  hoverPlus.classList.add("visible");
}

function scheduleHideHoverPlus() {
  clearTimeout(hidePlusTimer);
  hidePlusTimer = setTimeout(() => {
    hoverPlus.classList.remove("visible");
    state.hoverId = null;
  }, 250);
}

cy.on("tap", "node", (evt) => {
  const id = evt.target.id();
  showDetail(id);
  cy.$(":selected").unselect();
  evt.target.select();
  loadNodeDetail(id).catch((e) => log(`detail error: ${e.message}`));
});

cy.on("mouseover", "node", (evt) => {
  showHoverPlus(evt.target);
});

cy.on("mouseout", "node", () => {
  scheduleHideHoverPlus();
});

cy.on("pan zoom", refreshHoverPlusPosition);

cy.on("drag", "node", (evt) => {
  if (state.hoverId === evt.target.id()) positionHoverPlus(evt.target);
});

cy.on("position", "node", (evt) => {
  if (state.hoverId === evt.target.id()) positionHoverPlus(evt.target);
});

hoverPlus.addEventListener("mouseenter", () => {
  clearTimeout(hidePlusTimer);
});

hoverPlus.addEventListener("mouseleave", () => {
  scheduleHideHoverPlus();
});

hoverPlus.addEventListener("click", (e) => {
  e.stopPropagation();
  const id = state.hoverId;
  if (!id) return;
  loadNeighbors(id, 10).catch((err) => log(`neighbors: ${err.message}`));
});

$("owner-id").value = state.ownerId;
$("owner-id").addEventListener("change", () => {
  state.ownerId = $("owner-id").value.trim() || "default";
  localStorage.setItem("gm_owner_id", state.ownerId);
});

$("btn-load-node").addEventListener("click", () => {
  const id = $("node-id").value.trim();
  if (!id) return;
  loadAnchor(id).catch((e) => log(`load: ${e.message}`));
});

$("btn-search").addEventListener("click", () => {
  textSearch().catch((e) => log(`search: ${e.message}`));
});

$("btn-similar").addEventListener("click", () => {
  findSimilar().catch((e) => log(`similar: ${e.message}`));
});

$("btn-context").addEventListener("click", () => {
  const id = state.anchorId || $("node-id").value.trim();
  if (!id) return;
  loadContext(id, { originNodeId: id }).catch((e) => log(`context: ${e.message}`));
});

$("btn-hop").addEventListener("click", () => {
  const d = Number($("depth").value) || 1;
  $("depth").value = String(Math.min(3, d + 1));
  const id = state.anchorId || $("node-id").value.trim();
  if (!id) return;
  loadContext(id, { depth: Number($("depth").value), originNodeId: id }).catch((e) =>
    log(`hop: ${e.message}`),
  );
});

$("btn-clear").addEventListener("click", clearGraph);

$("btn-set-anchor").addEventListener("click", () => {
  if (state.selectedId) loadAnchor(state.selectedId).catch((e) => log(e.message));
});

$("btn-neighbors").addEventListener("click", () => {
  if (!state.selectedId) return;
  loadNeighbors(state.selectedId, 10).catch((e) => log(e.message));
});

async function checkHealth() {
  const badge = $("status-badge");
  try {
    const res = await fetch("/health");
    const data = await res.json();
    if (data.ready) {
      badge.textContent = "FalkorDB connected";
      badge.className = "badge badge-ok";
    } else {
      badge.textContent = "FalkorDB offline";
      badge.className = "badge badge-err";
    }
  } catch {
    badge.textContent = "server error";
    badge.className = "badge badge-err";
  }
}

checkHealth();
updateStats();
log("ready — enter owner_id and anchor node ID, then Load");
