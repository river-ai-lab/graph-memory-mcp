/* Graph Memory Explorer — client-side graph merge + Cytoscape */

const KNOWN_EDGE_TYPES = new Set([
  "RELATED_TO",
  "MENTIONS",
  "SUMMARIZES",
  "FOLLOWS_FROM",
  "CONTRADICTS",
  "EXTRACTED_FROM",
]);

const L = window.ExplorerLogic;
const state = {
  ownerId: new URLSearchParams(location.search).get("owner") || localStorage.getItem("gm_owner_id") || "default",
  hideOwner: false,
  previewMode: L.readPreviewMode(localStorage),
  anchorId: null,
  depth: 1,
  nodes: new Map(),
  edges: new Map(),
  neighborOffset: new Map(),
  selectedId: null,
  hoverId: null,
  pathEdgeKeys: new Set(),
  generation: 0,
  pending: 0,
};

const $ = (id) => document.getElementById(id);

function log(msg) {
  if (msg.includes("old response discarded")) return;
  const el = $("log");
  const line = `[${new Date().toLocaleTimeString()}] ${msg}`;
  el.textContent = `${line}\n${el.textContent}`.slice(0, 4000);
  if (/error:|needs |first$|^no path|^set anchor/.test(msg)) notice(msg, true);
}

function notice(message, error = false) {
  $("notice").hidden = false;
  $("notice-text").textContent = message;
  $("notice").classList.toggle("error", error);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

async function callTool(tool, arguments_) {
  const generation = state.generation;
  state.pending++;
  notice(({ get_brief: "Loading project brief…", get_node: "Loading full node text…", get_context: "Loading connected context…", search: "Searching memory…", recall_context: "Recalling connected context…", get_trace: "Finding a path…", find_similar: "Finding similar facts…", get_node_change_history: "Loading version history…" })[tool] || "Loading memory…");
  try {
    const res = await fetch("/api/tool", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool, arguments: arguments_ }),
      signal: AbortSignal.timeout(60000),
    });
    const data = await res.json();
    if (generation !== state.generation) throw new Error("Workspace changed; old response discarded.");
    if (!res.ok || data.success === false) throw new Error(data.error || `HTTP ${res.status}`);
    if (state.pending === 1) $("notice").hidden = true;
    return data;
  } catch (error) {
    if (generation === state.generation) notice(error.message, true);
    throw error;
  } finally {
    state.pending--;
  }
}

function ownerArgs(extra = {}) {
  syncOwner();
  return L.toolArguments(state.hideOwner, { owner_id: state.ownerId, ...extra });
}

function contextArgs(nodeId, extra = {}) {
  return ownerArgs({
    node_id: nodeId,
    include_outdated: true,
    include_ttl: true,
    ...extra,
  });
}

function nodeText(n) {
  if (!n) return "";
  return n.text || n.snippet || "";
}

function preview(text, n = 48) {
  return L.preview(text, n);
}

function formatTime(value, includeSeconds = false) {
  return L.formatTime(value, includeSeconds);
}

function nodeLabel(n) {
  const text = nodeText(n);
  if (state.ownerId === "luminaria") {
    const titles = [
      [/^Spring wheat neural network$/, "Spring wheat NN"],
      [/^Corn neural network$/, "Corn NN"],
      [/^Spring wheat NN reads a county-day/, "Wheat · Weather inputs"],
      [/^Spring wheat NN encode_mode/, "Wheat · Weather encoder"],
      [/^Spring wheat NN LSTM_clock/, "Wheat · Growth clock"],
      [/^Spring wheat NN LSTM_yield/, "Wheat · Yield readout"],
      [/^Spring wheat NN county embedding/, "Wheat · Location & planting"],
      [/^Live spring-wheat NN code/, "Wheat · Code location"],
      [/^Corn NN uses the same/, "Corn · Shared encoder"],
      [/^Corn NN stage order/, "Corn · Growth stages"],
      [/^Corn NN clock yaml/, "Corn · Clock & yield"],
      [/^Luminaria memory for/, "Luminaria · Project brief"],
    ];
    for (const [pattern, label] of titles) if (pattern.test(text)) return label;
  }
  return preview(text, L.previewChars(state.previewMode));
}

function setInspectorOpen(open) {
  document.body.classList.toggle("inspector-hidden", !open);
  $("inspector-panel").hidden = !open;
  $("btn-inspector").setAttribute("aria-expanded", String(open));
  cy.resize();
}

function policyHint(text) {
  if (!text) return "";
  const t = String(text);
  const hints = [];
  if (
    /\b(launched|relaunched|OOMKilled|backoffLimit)\b/.test(t) &&
    /\b(\d+\s*CPU|\d+CPU|\d+Gi|RUN )\b/.test(t)
  ) {
    hints.push("run diary");
  }
  if ((t.match(/\d+\.\d+\/\d+\.\d+/g) || []).length >= 2) {
    hints.push("metric table");
  }
  if (t.length > 600) hints.push("long");
  if (/\.aws\/credentials|~\/\.kube/.test(t)) hints.push("machine path");
  return hints.join(" · ");
}

function nodeStyle(nodeType, status) {
  const base =
    nodeType === "Entity"
      ? { background: "#b5a0f2", shape: "diamond" }
      : { background: "#79e1cb", shape: "ellipse" };
  if (status === "outdated") base.background = "#64748b";
  if (status === "archived") base.background = "#475569";
  return base;
}

function edgeClass(relationType) {
  const t = relationType || "RELATED";
  if (t === "CONTRADICTS") return "edge-contradicts";
  if (t === "FOLLOWS_FROM") return "edge-follows";
  if (t === "SUMMARIZES") return "edge-summarizes";
  if (!KNOWN_EDGE_TYPES.has(t)) return "edge-triplet";
  return "edge-default";
}

function searchFilters() {
  const extra = {};
  const status = $("search-status").value;
  Object.assign(extra, L.searchFilterArgs(status));
  const fact = $("type-fact").checked;
  const entity = $("type-entity").checked;
  if (fact && !entity) extra.node_types = ["Fact"];
  else if (entity && !fact) extra.node_types = ["Entity"];
  if (!fact && !entity) throw new Error("Select Fact or Entity to search.");
  // both → omit (server default)

  const project = $("filter-project").value.trim();
  const tagsRaw = $("filter-tags").value.trim();
  const mf = {};
  if (project) mf.project = project;
  if (tagsRaw) {
    mf.tags = tagsRaw
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
  }
  if (Object.keys(mf).length) extra.metadata_filter = mf;
  return extra;
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
      snippet: n.snippet ?? prev.snippet,
      source: n.source ?? prev.source,
      created_at: n.created_at ?? prev.created_at,
      updated_at: n.updated_at ?? prev.updated_at,
      created_by: n.created_by ?? prev.created_by,
      updated_by: n.updated_by ?? prev.updated_by,
      ttl_days: n.ttl_days ?? prev.ttl_days,
      expires_at: n.expires_at ?? prev.expires_at,
      type: n.type ?? prev.type,
      status: n.status ?? prev.status,
      similarity: meta.similarity ?? n.similarity ?? n.score ?? prev.similarity,
      metadata: n.metadata ?? prev.metadata,
      _fresh: meta.fresh !== false,
    });
  }
}

function mergeEdges(edges, { path = false } = {}) {
  let store = {
    edges: Object.fromEntries(state.edges),
    pathKeys: [...state.pathEdgeKeys],
  };
  for (const edge of edges || []) store = L.placeEdge(store, edge, { path });
  state.edges = new Map(Object.entries(store.edges));
  state.pathEdgeKeys = new Set(store.pathKeys);
}

function edgesFromTrace(nodes, relations) {
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

function clearPathHighlight() {
  state.pathEdgeKeys.clear();
}

function mergeToolResult(data, meta = {}, syncOpts = {}) {
  mergeNodes(data.nodes, meta);
  mergeNodes(data.similar_facts, { ...meta, fresh: true });
  mergeNodes(data.results, meta);
  mergeNodes(data.facts, meta);
  mergeNodes(data.entities, meta);
  mergeNodes(data.seeds, meta);
  if (data.node) mergeNodes([data.node], meta);
  mergeEdges(data.edges);
  mergeEdges(L.contradictionEdges(data.contradiction_pairs));
  for (const p of data.paths || []) {
    mergeNodes(p.nodes, { fresh: true });
    mergeEdges(edgesFromTrace(p.nodes || [], p.relations || []), { path: true });
  }
  syncGraph(syncOpts);
  updateStats();
}

function nodeElementDef(n) {
  return {
    group: "nodes",
    data: {
      id: n.node_id,
      label: nodeLabel(n).replace(" · ", "\n"),
      nodeType: n.node_type,
      status: n.status,
      fullText: nodeText(n),
      similarity: n.similarity,
    },
    classes: n._fresh ? "fresh" : "",
  };
}

function edgeElementDef(e, key) {
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
  if (typeof pausePhysics === "function") pausePhysics();
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
      ele.data("label", nodeLabel(n).replace(" · ", "\n"));
      ele.data("nodeType", n.node_type);
      ele.data("status", n.status);
      ele.data("fullText", nodeText(n));
      if (n._fresh) ele.addClass("fresh");
      else ele.removeClass("fresh");
    }
  }

  for (const [key, e] of state.edges) {
    const def = edgeElementDef(e, key);
    if (cy.getElementById(e.from_id).empty() || cy.getElementById(e.to_id).empty()) continue;
    let ele = cy.getElementById(def.data.id);
    if (ele.empty()) {
      cy.add(def);
    } else {
      ele.removeClass("edge-contradicts edge-follows edge-summarizes edge-triplet edge-default edge-path");
      ele.addClass(def.classes);
    }
  }

  applyNodeColors();
  applyPreviewMode();

  const labelLayout = L.shouldShowAlwaysLabels(state.previewMode, cy.zoom());
  if ((fullLayout || (!originNodeId && addedNodes.length > 0)) && cy.nodes().length > 1) {
    const connected = cy.edges().length > 0;
    cy.layout({
      name: connected ? "concentric" : "grid",
      animate: false,
      padding: labelLayout ? 48 : 40,
      concentric: (node) => (node.data("nodeType") === "Entity" ? 2 : 1),
      levelWidth: () => 1,
      minNodeSpacing: labelLayout ? 18 : 32,
      nodeDimensionsIncludeLabels: Boolean(labelLayout),
      avoidOverlap: true,
      spacingFactor: labelLayout ? 1.15 : 1.05,
      fit: true,
    }).run();
    let level = cy.zoom();
    if (level > 1.2) level = 1.2;
    level = L.previewZoom(state.previewMode, level);
    if (level !== cy.zoom()) {
      cy.zoom({ level, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
    }
    applyPreviewMode();
  }

  for (const n of state.nodes.values()) n._fresh = false;
  if (state.selectedId && state.nodes.has(state.selectedId)) showDetail(state.selectedId);
  updateStats();
  if (typeof restartPhysics === "function") restartPhysics();
}

function centerViewOnNode(nodeId) {
  const node = cy.getElementById(nodeId);
  if (node.empty()) return;
  const bounds = node.renderedBoundingBox();
  if (bounds.x1 >= 24 && bounds.x2 <= cy.width() - 24 && bounds.y1 >= 80 && bounds.y2 <= cy.height() - 100) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) cy.center(node);
  else cy.animate({ center: { eles: node }, duration: 200 });
}

let cy = cytoscape({
  container: $("cy"),
  elements: [],
  wheelSensitivity: 0.05,
  minZoom: 0.05,
  maxZoom: 4,
  style: [
    {
      selector: "node",
      style: {
        label: "",
        "font-size": 11,
        "line-height": 1.25,
        color: "#d6e5f3",
        "text-valign": "bottom",
        "text-halign": "center",
        "text-margin-y": 6,
        "text-wrap": "ellipsis",
        "text-max-width": 168,
        "text-background-color": "#0b111b",
        "text-background-opacity": 0.92,
        "text-background-padding": "3px",
        "min-zoomed-font-size": 8,
        width: 34,
        height: 34,
        "border-width": 2,
        "border-color": "#334155",
      },
    },
    {
      selector: "node.fresh",
      style: { "border-color": "#bdeee0", "border-width": 3 },
    },
    {
      selector: "node:selected",
      style: { "border-color": "#e3edf6", "border-width": 3, "underlay-color": "#79e1cb", "underlay-opacity": 0.15, "underlay-padding": 7 },
    },
    {
      selector: "edge",
      style: {
        width: 1.5,
        "line-color": "#475569",
        "target-arrow-shape": "triangle",
        "target-arrow-color": "#475569",
        "curve-style": "bezier",
        label: $("edge-labels").checked ? "data(label)" : "",
        "font-size": 10,
        color: "#a2b9cd",
        "text-rotation": "autorotate",
        "text-background-color": "#0b111b",
        "text-background-opacity": 0.9,
        "text-background-padding": 2,
      },
    },
    {
      selector: "edge.edge-contradicts",
      style: {
        width: 2.5,
        "line-color": "#f38f9b",
        "target-arrow-color": "#f38f9b",
        color: "#fca5a5",
      },
    },
    {
      selector: "edge.edge-follows",
      style: {
        width: 2,
        "line-color": "#c4a574",
        "target-arrow-color": "#c4a574",
        "line-style": "dashed",
        color: "#e7d3a8",
      },
    },
    {
      selector: "edge.edge-summarizes",
      style: {
        width: 2,
        "line-color": "#85c7ed",
        "target-arrow-color": "#85c7ed",
        color: "#a5f3fc",
      },
    },
    {
      selector: "edge.edge-triplet",
      style: {
        width: 2,
        "line-color": "#d2ac70",
        "target-arrow-color": "#d2ac70",
        color: "#fcd34d",
      },
    },
    {
      selector: "edge.edge-path",
      style: {
        width: 4,
        "underlay-color": "#f0ce83",
        "underlay-opacity": 0.55,
        "underlay-padding": 5,
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
  $("graph-empty").hidden = state.nodes.size > 0;
  $("tour-section").hidden = state.ownerId !== "luminaria";
  $("map-title").textContent = state.ownerId === "luminaria" ? "Luminaria" : state.ownerId;
  $("stats-bar").textContent = L.mapStats(cy.nodes().length, cy.edges().length);
  $("map-caption").textContent = state.nodes.size
    ? "Select a node to read its full text."
    : "Search, load the brief, or enter a node ID.";
  for (const id of ["btn-fit", "btn-layout", "btn-zoom-in", "btn-zoom-out"]) $(id).disabled = !cy.nodes().length;
}

async function loadNodeDetail(nodeId) {
  setInspectorOpen(true);
  const data = await callTool("get_node", ownerArgs({ node_id: nodeId }));
  mergeToolResult(data, {}, { originNodeId: nodeId });
  if (!state.selectedId || state.selectedId === nodeId) showDetail(nodeId);
}

function showDetail(nodeId, nodeOverride) {
  const n = nodeOverride || state.nodes.get(nodeId);
  if (!n) return;
  if (state.selectedId !== nodeId) $("detail-history").hidden = true;
  state.selectedId = nodeId;
  const selectedNode = cy.getElementById(nodeId);
  if (selectedNode.nonempty() && !selectedNode.selected()) {
    cy.$(":selected").unselect(); selectedNode.select();
  }
  $("detail-empty").hidden = true;
  $("detail").hidden = false;
  $("detail-id").textContent = nodeId;
  $("detail-id").title = nodeId;
  $("btn-copy-id").textContent = "Copy ID";
  const typeName = n.node_type || "Fact";
  $("detail-type").textContent = typeName === "Entity" && n.type ? `Entity · ${n.type}` : typeName;
  $("detail-type").dataset.value = typeName;
  $("detail-status").textContent = n.status || "active";
  $("detail-status").dataset.value = n.status || "active";
  $("detail-sim").textContent =
    n.similarity != null ? `Similarity ${Number(n.similarity).toFixed(3)}` : "";
  $("detail-sim").hidden = n.similarity == null;
  const hint = policyHint(nodeText(n));
  $("detail-policy").hidden = !hint;
  $("detail-policy").textContent = hint ? `Review hints (heuristic): ${hint}` : "";
  $("detail-text").textContent = nodeText(n) || "(no text)";
  const when = L.detailWhen(n);
  $("detail-when").hidden = !when;
  $("detail-when").textContent = when;

  const related = [];
  for (const e of state.edges.values()) {
    if (e.from_id === nodeId) related.push({ id: e.to_id, kind: `Outgoing · ${e.relation_type}` });
    if (e.to_id === nodeId) related.push({ id: e.from_id, kind: `Incoming · ${e.relation_type}` });
  }
  $("detail-metadata").textContent = JSON.stringify({
    ...n.metadata, ...(n.source ? { source: n.source } : {}),
    ...(n.created_at ? { created_at: n.created_at } : {}),
    ...(n.updated_at ? { updated_at: n.updated_at } : {}),
    ...(n.ttl_days != null ? { ttl_days: n.ttl_days } : {}),
    ...(n.expires_at ? { expires_at: n.expires_at } : {}),
  }, null, 2);
  const timeKeys = new Set(["Created", "Updated", "Expires"]);
  const provenance = L.provenanceRows(n).map(([label, value]) => [
    label,
    timeKeys.has(label) ? formatTime(value) : value,
  ]);
  $("detail-provenance").innerHTML = provenance.length
    ? provenance.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")
    : "<dd>No source metadata available.</dd>";
  $("detail-edges").innerHTML = related.length
    ? related.map(r => `<li><button type="button" class="connection-button" data-node-id="${escapeHtml(r.id)}" title="${escapeHtml(r.id)}"><span class="connection-kind">${escapeHtml(r.kind)}</span>${escapeHtml(state.nodes.has(r.id) ? nodeLabel(state.nodes.get(r.id)) : `Node ${r.id.slice(0, 8)}`)}</button></li>`).join("")
    : "<li class='muted'>No connections in this map. Expand neighbors to explore.</li>";
  for (const el of document.querySelectorAll("#overview [data-id], #search-results [data-id]")) {
    el.classList.toggle("active", el.dataset.id === nodeId);
    el.setAttribute("aria-pressed", String(el.dataset.id === nodeId));
  }

}

async function loadAnchor(nodeId) {
  state.selectedId = nodeId;
  state.anchorId = nodeId;
  $("node-id").value = nodeId;
  log(`anchor ${nodeId}`);
  const isEmpty = cy.nodes().length === 0;
  await loadNodeDetail(nodeId);
  await loadContext(nodeId, { resetOffset: true, originNodeId: nodeId, fullLayout: isEmpty });
  if (isEmpty) centerViewOnNode(nodeId);
}

async function loadContext(nodeId, opts = {}) {
  const depth = opts.depth ?? Number($("depth").value);
  const maxNodes = Number($("max-nodes").value) || 10;
  const args = contextArgs(nodeId, {
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
  // Stable pages (page=true), not the priority walk. Skip a page that only
  // repeats nodes already on the map so one click still reveals new neighbors.
  let off = state.neighborOffset.get(nodeId) ?? 0;
  let data = null;
  let added = 0;
  for (let attempt = 0; attempt < 6; attempt++) {
    const before = state.nodes.size;
    data = await callTool(
      "get_context",
      contextArgs(nodeId, {
        depth: 1,
        max_nodes: pageSize,
        offset: off,
        page: true,
      }),
    );
    mergeToolResult(data, { fresh: true }, { originNodeId: nodeId });
    added = state.nodes.size - before;
    off += pageSize;
    state.neighborOffset.set(nodeId, off);
    if (added > 0 || !data.has_more) break;
  }
  log(`neighbors ${nodeId} offset=${off - pageSize} +${added}`);
  if (!added) notice("No further neighbors in this map.");
  return data;
}

async function findSimilar() {
  const anchor = state.anchorId || $("node-id").value.trim();
  if (!anchor) {
    log("set anchor first");
    return;
  }
  const limit = Number($("similar-limit").value) || 5;
  const threshold = Number($("similar-threshold").value);
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
    contextArgs(anchor, { depth: 2, max_nodes: 50 }),
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
  if (!query) { notice("Enter a question to search your memory.", true); return; }
  const limit = Number($("search-limit").value) || 10;
  const args = ownerArgs({ query, limit, ...searchFilters() });
  if ($("search-compact").checked) args.compact = true;
  const data = await callTool("search", args);
  mergeToolResult(data, { fresh: true }, { originNodeId: state.anchorId || null });
  renderResults(data.results || [], data);
  log(`search "${query}" → ${data.results?.length || 0}${budgetNote(data)}`);
}

async function recallContext() {
  const query = $("search-query").value.trim();
  if (!query) { notice("Enter a question to search your memory.", true); return; }
  const limit = Number($("search-limit").value) || 10;
  const depth = Number($("depth").value) || 1;
  const maxNodes = Number($("max-nodes").value) || 10;
  clearPathHighlight();
  const filters = searchFilters();
  const args = ownerArgs({
    query,
    limit,
    depth,
    max_nodes: maxNodes,
    include_paths: true,
  });
  if (filters.metadata_filter) args.metadata_filter = filters.metadata_filter;
  if (filters.include_outdated) args.include_outdated = true;
  if ($("search-compact").checked) args.compact = true;
  const data = await callTool("recall_context", args);
  mergeToolResult(data, { fresh: true }, { fullLayout: true });
  renderResults(data.seeds || [], data);
  const seed = data.seeds?.[0]?.node_id;
  if (seed) {
    state.anchorId = seed;
    $("node-id").value = seed;
    centerViewOnNode(seed);
  }
  log(
    `recall "${query}" → ${data.nodes?.length || 0} nodes, ${data.seeds?.length || 0} seeds${budgetNote(data)}`,
  );
}

function budgetNote(data) {
  const b = data && data.budget;
  if (!b) return "";
  const cap = b.tokens_max != null ? `/${b.tokens_max}` : "";
  const cut = b.truncated ? " truncated" : "";
  return ` · ${b.mode || "full"} ~${b.tokens_est}${cap}${cut}`;
}

function renderOverview(data) {
  const stats = data.stats || {};
  const line = L.briefStatLine(stats);
  $("overview-stats").textContent = line || "no stats";

  const blocks = [];
  const about = data.about;
  if (about && (about.text || about.snippet)) {
    const aboutText = about.text || about.snippet;
    blocks.push(
      `<div class="ov-block"><h3>About</h3><ul class="ov-list"><li data-id="${escapeHtml(about.node_id)}">${escapeHtml(preview(aboutText, 140))}</li></ul></div>`,
    );
  }

  const top = data.top_facts || [];
  const rankedByDegree = top.some((f) => f.degree != null);
  if (top.length) {
    blocks.push(`<div class="ov-block"><h3>${rankedByDegree ? "Most linked" : "Recent"}</h3><ul class="ov-list">
      ${top
        .map((f) => {
          const text = nodeText(f);
          const noise = policyHint(text);
          return `<li data-id="${escapeHtml(f.node_id)}" title="${escapeHtml(f.node_id)}">${escapeHtml(preview(text, 90))}${f.degree != null ? ` <span class="muted">·${escapeHtml(f.degree)}</span>` : ""}${noise ? ` <span class="chip-noise">${noise}</span>` : ""}</li>`;
        })
        .join("")}
    </ul></div>`);
  }

  const contra = data.contradictions || [];
  if (contra.length) {
    blocks.push(`<div class="ov-block"><h3>Contradicts</h3><ul class="ov-list">
      ${contra
        .map(
          (c) =>
            `<li class="contradict" data-from="${escapeHtml(c.from_id)}" data-to="${escapeHtml(c.to_id)}">
              <span data-id="${escapeHtml(c.from_id)}">${escapeHtml(preview(c.from_text, 28))}</span>
              <span class="sep">⚡</span>
              <span data-id="${escapeHtml(c.to_id)}">${escapeHtml(preview(c.to_text, 28))}</span>
            </li>`,
        )
        .join("")}
    </ul></div>`);
  }

  const stale = data.stale_facts || [];
  if (stale.length) {
    blocks.push(`<details class="ov-block"><summary>Not recently accessed</summary><ul class="ov-list">
      ${stale
        .map(
          (f) =>
            `<li data-id="${escapeHtml(f.node_id)}" title="${escapeHtml(f.node_id)}">${escapeHtml(preview(f.text, 90))}</li>`,
        )
        .join("")}
    </ul></details>`);
  }

  $("overview").innerHTML = blocks.length
    ? blocks.join("")
    : `<p class="muted">empty owner</p>`;
}

async function loadBrief({ open = true, seedGraph = true } = {}) {
  const data = await callTool("get_brief", ownerArgs({ limit: 10, include_stale: true }));
  renderOverview(data);
  $("overview-section").open = open;
  if (!seedGraph) { updateStats(); log("project brief loaded"); return; }
  // seed graph with top + contradict endpoints for click targets
  if (state.hideOwner && data.owner_id) {
    state.ownerId = data.owner_id;
    $("owner-id").value = data.owner_id;
    localStorage.setItem("gm_owner_id", data.owner_id);
  }
  const asFact = (node) => ({ node_type: "Fact", status: "active", ...node });
  const seedNodes = [
    ...(data.about ? [asFact(data.about)] : []),
    ...(data.top_facts || []).map(asFact),
  ];
  for (const c of data.contradictions || []) {
    seedNodes.push(
      asFact({ node_id: c.from_id, text: c.from_text }),
      asFact({ node_id: c.to_id, text: c.to_text }),
    );
  }
  mergeNodes(seedNodes, { fresh: true });
  const contraEdges = (data.contradictions || []).map((c) => ({
    from_id: c.from_id,
    to_id: c.to_id,
    relation_type: "CONTRADICTS",
  }));
  mergeEdges(contraEdges);
  syncGraph({ fullLayout: cy.nodes().length === 0 && seedNodes.length > 1 });
  updateStats();
  log(
    `brief: top=${data.top_facts?.length || 0} contra=${data.contradictions?.length || 0} stale=${data.stale_count || 0}`,
  );
}

async function runTrace() {
  const fromId = $("trace-from").value.trim();
  const toId = $("trace-to").value.trim();
  if (!fromId || !toId) {
    log("trace needs from_id and to_id");
    return;
  }
  const maxDepth = Number($("trace-depth").value) || 5;
  const directed = !$("trace-undirected").checked;
  clearPathHighlight();
  const data = await callTool(
    "get_trace",
    ownerArgs({
      from_id: fromId,
      to_id: toId,
      max_depth: maxDepth,
      directed,
    }),
  );
  const nodes = data.nodes || [];
  if (!nodes.length) {
    log(data.message || "no path");
    return;
  }
  mergeNodes(nodes, { fresh: true });
  mergeEdges(edgesFromTrace(nodes, data.relations || []), { path: true });
  syncGraph({ fullLayout: true, originNodeId: fromId });
  if (cy.nodes().length === nodes.length) {
    const order = new Map(nodes.map((node, index) => [node.node_id, index]));
    cy.layout({ name: "grid", rows: 1, padding: 80,
      nodeDimensionsIncludeLabels: true,
      sort: (a, b) => order.get(a.id()) - order.get(b.id()),
    }).run();
  }
  log(`trace ${fromId} → ${toId}: ${nodes.length} nodes`);
}

function clearGraph() {
  for (const el of document.querySelectorAll("#overview [data-id], #search-results [data-id]")) {
    el.classList.remove("active"); el.setAttribute("aria-pressed", "false");
  }
  for (const id of ["btn-wheat", "btn-corn", "btn-both"]) $(id).setAttribute("aria-pressed", "false");
  if (typeof pausePhysics === "function") pausePhysics();
  state.generation++;
  cy.elements().remove();
  state.nodes.clear();
  state.edges.clear();
  state.neighborOffset.clear();
  state.pathEdgeKeys.clear();
  state.selectedId = null;
  state.anchorId = null;
  state.hoverId = null;
  $("hover-plus").classList.remove("visible");
  hideNodePreviewTip();
  $("node-id").value = "";
  updateStats();
  $("detail").hidden = true;
  $("detail-history").hidden = true;
  $("detail-empty").hidden = false;
  log("graph cleared");
}

const hoverPlus = $("hover-plus");
const previewTip = $("node-preview-tip");
let hidePlusTimer = null;

function positionHoverPlus(node) {
  const bb = node.renderedBoundingBox({
    includeLabels: false,
    includeOverlays: false,
  });
  hoverPlus.style.left = `${bb.x2}px`;
  hoverPlus.style.top = `${bb.y1}px`;
}

function showNodePreviewTip(node) {
  if (!node || node.empty()) return;
  if (L.shouldShowAlwaysLabels(state.previewMode, cy.zoom())) {
    hideNodePreviewTip();
    return;
  }
  const n = state.nodes.get(node.id());
  previewTip.textContent = preview(nodeText(n), L.HOVER_CHARS);
  const bb = node.renderedBoundingBox({ includeLabels: false, includeOverlays: false });
  previewTip.hidden = false;
  previewTip.style.left = `${Math.max(8, Math.min(bb.x1, cy.width() - 228))}px`;
  previewTip.style.top = `${Math.min(bb.y2 + 8, cy.height() - 48)}px`;
}

function hideNodePreviewTip() {
  previewTip.hidden = true;
  previewTip.textContent = "";
}

function refreshHoverPlusPosition() {
  if (!state.hoverId) return;
  const node = cy.getElementById(state.hoverId);
  if (node.empty()) return;
  if (hoverPlus.classList.contains("visible")) positionHoverPlus(node);
  if (!previewTip.hidden) showNodePreviewTip(node);
}

function showHoverPlus(node) {
  clearTimeout(hidePlusTimer);
  state.hoverId = node.id();
  positionHoverPlus(node);
  hoverPlus.classList.add("visible");
  showNodePreviewTip(node);
}

function scheduleHideHoverPlus() {
  clearTimeout(hidePlusTimer);
  hidePlusTimer = setTimeout(() => {
    hoverPlus.classList.remove("visible");
    hideNodePreviewTip();
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
function syncOwner() {
  const owner = $("owner-id").value.trim() || "default";
  if (owner === state.ownerId) return false;

  if ($("evolution-dialog").open) $("evolution-dialog").close();
  state.generation++;
  clearGraph();
  $("overview").replaceChildren();
  $("overview-stats").textContent = "Loading workspace…";
  $("results-section").hidden = true;
  $("search-results").replaceChildren();
  $("trace-from").value = "";
  $("trace-to").value = "";
  $("filter-project").value = "";
  $("filter-tags").value = "";
  state.ownerId = $("owner-id").value.trim() || "default";
  $("owner-id").value = state.ownerId;
  localStorage.setItem("gm_owner_id", state.ownerId);
  updateStats();
  return true;
}
$("owner-id").addEventListener("change", () => {
  if (syncOwner()) loadBrief().catch(e => notice(e.message, true));
});
$("owner-id").addEventListener("blur", () => {
  if (syncOwner()) loadBrief().catch(e => notice(e.message, true));
});

$("btn-brief").addEventListener("click", () => {
  loadBrief().catch((e) => log(`brief error: ${e.message}`));
});

$("overview").addEventListener("click", (e) => {
  const pair = e.target.closest("[data-from][data-to]");
  const idEl = pair ? null : e.target.closest("[data-id]");
  if (idEl?.dataset.id) {
    loadAnchor(idEl.dataset.id).catch((err) => log(err.message));
    return;
  }
  if (pair) {
    $("trace-from").value = pair.dataset.from;
    $("trace-to").value = pair.dataset.to;
    runTrace().catch((err) => log(`trace: ${err.message}`));
  }
});

$("btn-load-node").addEventListener("click", () => {
  const id = $("node-id").value.trim();
  if (!id) return;
  loadAnchor(id).catch((e) => log(`load error: ${e.message}`));
});

$("btn-search").addEventListener("click", () => {
  textSearch().catch((e) => log(`search error: ${e.message}`));
});

$("btn-recall").addEventListener("click", () => {
  recallContext().catch((e) => log(`recall: ${e.message}`));
});

$("btn-trace").addEventListener("click", () => {
  runTrace().catch((e) => log(`trace error: ${e.message}`));
});

$("btn-similar").addEventListener("click", () => {
  findSimilar().catch((e) => log(`similar: ${e.message}`));
});

$("btn-context").addEventListener("click", () => {
  const id = state.anchorId || $("node-id").value.trim();
  if (!id) { notice("Select an anchor node first.", true); return; }
  loadContext(id, { originNodeId: id }).catch((e) => log(`context: ${e.message}`));
});

$("btn-hop").addEventListener("click", () => {
  const d = Number($("depth").value) || 1;
  $("depth").value = String(Math.min(3, d + 1));
  const id = state.anchorId || $("node-id").value.trim();
  if (!id) { notice("Select an anchor node first.", true); return; }
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

$("btn-trace-from").addEventListener("click", () => {
  if (state.selectedId) $("trace-from").value = state.selectedId;
});

$("btn-trace-to").addEventListener("click", () => {
  if (state.selectedId) $("trace-to").value = state.selectedId;
});

async function checkHealth() {
  const generation = state.generation;
  const badge = $("status-badge");
  try {
    const res = await fetch("/health");
    const data = await res.json();
    if (data.ready) {
      badge.textContent = "Memory connected";
      badge.className = "badge badge-ok";
      applyAuthMode(data);
      if (generation === state.generation) loadBrief({ open: window.innerWidth > 600, seedGraph: true }).catch((e) => log(`brief error: ${e.message}`));
    } else {
      applyAuthMode(data);
      badge.textContent = "Memory offline";
      notice(data.error || "MCP is unavailable. Check the port-forward and restart Explorer to reconnect.", true);
      badge.className = "badge badge-err";
    }
  } catch {
    badge.textContent = "Connection error";
    notice("Explorer cannot reach its backend. Check the local server.", true);
    badge.className = "badge badge-err";
  }
}

function applyAuthMode(data) {
  state.hideOwner = Boolean(data.hide_owner);
  document.body.classList.toggle("auth-owner", state.hideOwner);
  $("owner-id").disabled = state.hideOwner;
  $("owner-bound").hidden = !state.hideOwner;
}

function renderResults(nodes, data) {
  $("results-section").hidden = false;
  $("overview-section").open = false;
  $("result-summary").textContent = `${nodes.length} results${data.budget?.tokens_est != null ? ` · ≈${data.budget.tokens_est} tokens` : ""}. Open a result for full text.`;
  const pairs = data.contradiction_pairs || [];
  const pairBlock = pairs.length
    ? `<div class="ov-block"><h3>Contradicts</h3><ul class="ov-list">${pairs.map((c) => {
        const from = state.nodes.get(c.from_id);
        const to = state.nodes.get(c.to_id);
        return `<li class="contradict" data-from="${escapeHtml(c.from_id)}" data-to="${escapeHtml(c.to_id)}"><span data-id="${escapeHtml(c.from_id)}">${escapeHtml(preview(nodeText(from), 28))}</span><span class="sep">⚡</span><span data-id="${escapeHtml(c.to_id)}">${escapeHtml(preview(nodeText(to), 28))}</span></li>`;
      }).join("")}</ul></div>`
    : "";
  $("search-results").innerHTML = nodes.length
    ? `${pairBlock}<ul class="ov-list">${nodes.map(n => `<li data-id="${escapeHtml(n.node_id)}">${escapeHtml(preview(nodeText(n), 150))}<span class="result-meta">${escapeHtml(L.resultMeta(n))}</span></li>`).join("")}</ul>`
    : '<p class="muted">No matches. Try a broader question or adjust your filters.</p>';
  if (!nodes.length) notice("No matches. Try a broader question or adjust your filters.");
}

$("search-results").addEventListener("click", e => {
  const pair = e.target.closest("[data-from][data-to]");
  const id = pair ? null : e.target.closest("[data-id]")?.dataset.id;
  if (id) {
    loadAnchor(id).catch(error => notice(error.message, true));
    return;
  }
  if (pair) {
    $("trace-from").value = pair.dataset.from;
    $("trace-to").value = pair.dataset.to;
    runTrace().catch((err) => log(`trace: ${err.message}`));
  }
});
$("search-query").addEventListener("keydown", e => {
  if (e.key === "Enter") textSearch().catch(error => notice(error.message, true));
});
$("node-id").addEventListener("keydown", e => {
  if (e.key === "Enter") $("btn-load-node").click();
});
$("btn-fit").addEventListener("click", () => {
  cy.fit(undefined, 60);
  const floor = L.previewZoom(state.previewMode, cy.zoom());
  if (floor > cy.zoom()) {
    cy.zoom({ level: floor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }
});
$("btn-layout").addEventListener("click", () => syncGraph({ fullLayout: true }));
function zoomBy(factor) {
  cy.zoom({ level: Math.min(cy.maxZoom(), Math.max(cy.minZoom(), cy.zoom() * factor)), renderedPosition: { x: cy.width()/2, y: cy.height()/2 } });
}
$("btn-zoom-in").addEventListener("click", () => zoomBy(1.25));
$("btn-zoom-out").addEventListener("click", () => zoomBy(.8));
cy.on("zoom", () => {
  $("zoom-level").textContent = `${Math.round(cy.zoom()*100)}%`;
  applyPreviewMode();
});
$("edge-labels").addEventListener("change", () => {
  cy.style().selector("edge").style("label", $("edge-labels").checked ? "data(label)" : "").update();
});
let lastAlwaysLabels = null;
let applyingPreview = false;
function applyPreviewMode({ relayout = false } = {}) {
  if (applyingPreview) return;
  state.previewMode = L.normalizePreviewMode($("node-preview").value);
  L.writePreviewMode(localStorage, state.previewMode);
  const show = L.shouldShowAlwaysLabels(state.previewMode, cy.zoom());
  applyingPreview = true;
  try {
    cy.batch(() => {
      for (const n of state.nodes.values()) {
        const ele = cy.getElementById(n.node_id);
        if (ele.nonempty()) ele.data("label", nodeLabel(n).replace(" · ", "\n"));
      }
    });
    if (lastAlwaysLabels !== show) {
      lastAlwaysLabels = show;
      cy.style().selector("node").style("label", show ? "data(label)" : "").update();
    }
  } finally {
    applyingPreview = false;
  }
  if (!show && state.hoverId) showNodePreviewTip(cy.getElementById(state.hoverId));
  else if (show) hideNodePreviewTip();
  if (relayout && show && cy.nodes().length > 1) syncGraph({ fullLayout: true });
}
$("node-preview").value = state.previewMode;
$("node-preview").addEventListener("change", () => applyPreviewMode({ relayout: true }));
$("btn-present").addEventListener("click", () => {
  const active = document.body.classList.toggle("presenting");
  $("btn-present").setAttribute("aria-pressed", String(active));
  $("btn-present").textContent = active ? "Exit present" : "Present";
  cy.resize();
  cy.fit(undefined, 60);
});
$("btn-inspector").addEventListener("click", () => setInspectorOpen($("inspector-panel").hidden));
$("btn-dismiss-notice").addEventListener("click", () => { $("notice").hidden = true; });
$("btn-copy-id").addEventListener("click", async () => {
  if (!state.selectedId) return;
  try { await navigator.clipboard.writeText(state.selectedId); $("btn-copy-id").textContent = "Copied"; }
  catch { notice("Copy is unavailable. Select the node ID to copy it manually.", true); }
});
$("detail-edges").addEventListener("click", e => {
  const id = e.target.closest("[data-node-id]")?.dataset.nodeId;
  if (!id) return;
  showDetail(id);
  cy.$(":selected").unselect(); cy.getElementById(id).select();
  centerViewOnNode(id);
  loadNodeDetail(id).catch(error => notice(error.message, true));
});
for (const [id, field] of [["btn-trace-from", "trace-from"], ["btn-trace-to", "trace-to"]]) {
  $(id).addEventListener("click", () => {
    document.querySelector(".advanced").open = true;
    if (document.body.classList.contains("presenting")) $("btn-present").click();
    $(field).scrollIntoView({ block: "nearest" });
    $(field).focus();
  });
}
cy.on("mouseover", "edge", event => { event.target.style("label", event.target.data("label")); });
cy.on("mouseout", "edge", event => {
  if ($("edge-labels").checked) event.target.style("label", event.target.data("label"));
  else event.target.removeStyle("label");
});
new ResizeObserver(() => cy.resize()).observe($("cy"));
for (const el of document.querySelectorAll("input, select")) {
  if (!el.labels?.length) el.setAttribute("aria-label", el.placeholder || el.title || el.id.replaceAll("-", " "));
}
function activateListItem(e) {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches("li[data-id], li[data-from]")) {
    e.preventDefault(); e.target.click();
  }
}
for (const id of ["overview", "search-results"]) {
  $(id).addEventListener("keydown", activateListItem);
  new MutationObserver(() => {
    $(id).querySelectorAll("li[data-id], li[data-from]").forEach(el => { el.tabIndex = 0; el.setAttribute("role", "button"); });
  }).observe($(id), { childList: true, subtree: true });
}
checkHealth();
updateStats();
log("ready — Brief loads overview; Search / Recall / Trace explore");
