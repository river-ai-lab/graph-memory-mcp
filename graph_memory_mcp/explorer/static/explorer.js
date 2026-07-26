/* Graph Memory Explorer — multi-layout viz + Cytoscape controls */

const KNOWN_EDGE_TYPES = new Set([
  "RELATED_TO",
  "MENTIONS",
  "SUMMARIZES",
  "FOLLOWS_FROM",
  "CONTRADICTS",
  "EXTRACTED_FROM",
]);

const state = {
  ownerId: localStorage.getItem("gm_owner_id") || "default",
  anchorId: null,
  nodes: new Map(),
  edges: new Map(),
  /** @type {Map<string, { offset: number, pageSize: number, hasMore: boolean, loaded: number, batchIds: string[] }>} */
  neighborState: new Map(),
  selectedId: null,
  hoverId: null,
  pathEdgeKeys: new Set(),
  nodesLocked: false,
  spacePan: false,
  layoutName: localStorage.getItem("gm_layout") || "cose",
  lastToolResponse: null,
  /** @type {{ active: boolean, cx: number, cy: number, lastAngle: number } | null} */
  rotateDrag: null,
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

function edgeClass(relationType) {
  const t = relationType || "RELATED";
  if (t === "CONTRADICTS") return "edge-contradicts";
  if (t === "SUMMARIZES") return "edge-summarizes";
  if (!KNOWN_EDGE_TYPES.has(t)) return "edge-triplet";
  return "edge-default";
}

function parseTags(raw) {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

function scopeMetadataFilter() {
  const project = $("scope-project").value.trim();
  const tags = parseTags($("scope-tags").value.trim());
  const mf = {};
  if (project) mf.project = project;
  if (tags.length) mf.tags = tags;
  return Object.keys(mf).length ? mf : null;
}

function searchFilters() {
  const extra = {};
  const status = $("search-status").value;
  if (status) {
    extra.status = status;
    if (status !== "active") extra.include_outdated = true;
  }
  const fact = $("type-fact").checked;
  const entity = $("type-entity").checked;
  if (fact && !entity) extra.node_types = ["Fact"];
  else if (entity && !fact) extra.node_types = ["Entity"];
  const mf = scopeMetadataFilter();
  if (mf) extra.metadata_filter = mf;
  return extra;
}

const TOOL_HINTS = {
  recall_context:
    "Semantic search + expand around seeds. Closest to “ask the memory a question”.",
  get_trace:
    "Shortest path between two node uids. Highlighted as gold path edges.",
  get_context:
    "Subgraph around one node. offset>0 enables paginated neighbor loading.",
  search:
    "Return ranked hits only (no expansion). Scope project/tags apply as filters.",
  find_similar:
    "Embedding-near facts for a given fact_id. Then draws edges among them.",
};

const PERSIST_FIELDS = [
  { id: "owner-id", key: "gm_owner_id", type: "text", fallback: "default" },
  { id: "scope-project", key: "gm_scope_project", type: "text" },
  { id: "scope-tags", key: "gm_scope_tags", type: "text" },
  { id: "llm-tool", key: "gm_llm_tool", type: "text", fallback: "recall_context" },
  { id: "tool-replace", key: "gm_tool_replace", type: "checkbox", fallback: true },
  { id: "recall-query", key: "gm_recall_query", type: "text" },
  { id: "recall-limit", key: "gm_recall_limit", type: "text", fallback: "8" },
  { id: "recall-depth", key: "gm_recall_depth", type: "text", fallback: "1" },
  { id: "recall-max-nodes", key: "gm_recall_max_nodes", type: "text", fallback: "30" },
  { id: "recall-threshold", key: "gm_recall_threshold", type: "text" },
  { id: "recall-paths", key: "gm_recall_paths", type: "checkbox", fallback: false },
  { id: "recall-outdated", key: "gm_recall_outdated", type: "checkbox", fallback: false },
  { id: "trace-from", key: "gm_trace_from", type: "text" },
  { id: "trace-to", key: "gm_trace_to", type: "text" },
  { id: "trace-depth", key: "gm_trace_depth", type: "text", fallback: "5" },
  { id: "trace-undirected", key: "gm_trace_undirected", type: "checkbox", fallback: false },
  { id: "ctx-node-id", key: "gm_ctx_node_id", type: "text" },
  { id: "ctx-depth", key: "gm_ctx_depth", type: "text", fallback: "1" },
  { id: "ctx-max-nodes", key: "gm_ctx_max_nodes", type: "text", fallback: "20" },
  { id: "ctx-offset", key: "gm_ctx_offset", type: "text", fallback: "0" },
  { id: "ctx-outdated", key: "gm_ctx_outdated", type: "checkbox", fallback: false },
  { id: "search-query", key: "gm_search_query", type: "text" },
  { id: "search-limit", key: "gm_search_limit", type: "text", fallback: "10" },
  { id: "search-status", key: "gm_search_status", type: "text" },
  { id: "type-fact", key: "gm_type_fact", type: "checkbox", fallback: true },
  { id: "type-entity", key: "gm_type_entity", type: "checkbox", fallback: true },
  { id: "similar-fact-id", key: "gm_similar_fact_id", type: "text" },
  { id: "similar-limit", key: "gm_similar_limit", type: "text", fallback: "5" },
  { id: "similar-threshold", key: "gm_similar_threshold", type: "text", fallback: "0.55" },
  { id: "neighbor-page-size", key: "gm_neighbor_page", type: "text", fallback: "10" },
  { id: "layout-mode", key: "gm_layout", type: "text", fallback: "cose" },
];

function loadPersistedFields() {
  for (const f of PERSIST_FIELDS) {
    const el = $(f.id);
    if (!el) continue;
    const raw = localStorage.getItem(f.key);
    if (f.type === "checkbox") {
      if (raw === null) el.checked = !!f.fallback;
      else el.checked = raw === "1";
    } else if (raw !== null) {
      el.value = raw;
    } else if (f.fallback != null) {
      el.value = String(f.fallback);
    }
  }
  state.ownerId = $("owner-id").value.trim() || "default";
  state.layoutName = $("layout-mode").value || "cose";
}

function persistField(id) {
  const f = PERSIST_FIELDS.find((x) => x.id === id);
  const el = $(id);
  if (!f || !el) return;
  if (f.type === "checkbox") localStorage.setItem(f.key, el.checked ? "1" : "0");
  else localStorage.setItem(f.key, el.value);
}

function bindPersistence() {
  for (const f of PERSIST_FIELDS) {
    const el = $(f.id);
    if (!el) continue;
    const ev = f.type === "checkbox" || el.tagName === "SELECT" ? "change" : "input";
    el.addEventListener(ev, () => persistField(f.id));
    el.addEventListener("change", () => persistField(f.id));
  }
}

function setTool(tool) {
  $("llm-tool").value = tool;
  for (const el of document.querySelectorAll(".tool-params")) {
    el.hidden = el.id !== `params-${tool}`;
  }
  const hint = $("tool-hint");
  if (hint) hint.textContent = TOOL_HINTS[tool] || "";
  persistField("llm-tool");
}

function showToolResult(tool, args, data) {
  state.lastToolResponse = { tool, args, data };
  const nodes = data.nodes?.length || 0;
  const edges = data.edges?.length || 0;
  const seeds = data.seeds?.length || 0;
  const paths = data.paths?.length || 0;
  const parts = [`${tool}`, `${nodes} nodes`, `${edges} edges`];
  if (seeds) parts.push(`${seeds} seeds`);
  if (paths) parts.push(`${paths} paths`);
  if (data.message) parts.push(data.message);
  if (data.has_more != null) parts.push(data.has_more ? "has_more" : "end");
  $("tool-summary").textContent = parts.join(" · ");
  $("tool-summary").classList.remove("muted");
  $("tool-raw").textContent = JSON.stringify({ tool, arguments: args, response: data }, null, 2);
}

async function beginToolRun() {
  if ($("tool-replace").checked) clearGraph({ quiet: true });
}

function buildToolCall(tool) {
  switch (tool) {
    case "recall_context": {
      const query = $("recall-query").value.trim();
      if (!query) throw new Error("recall_context needs query");
      const args = ownerArgs({
        query,
        limit: Number($("recall-limit").value) || 8,
        depth: Number($("recall-depth").value) || 0,
        max_nodes: Number($("recall-max-nodes").value) || 30,
        include_paths: $("recall-paths").checked,
        include_outdated: $("recall-outdated").checked,
      });
      const thr = $("recall-threshold").value;
      if (thr !== "") args.similarity_threshold = Number(thr);
      const mf = scopeMetadataFilter();
      if (mf) args.metadata_filter = mf;
      return args;
    }
    case "get_trace": {
      const from_id = $("trace-from").value.trim();
      const to_id = $("trace-to").value.trim();
      if (!from_id || !to_id) throw new Error("get_trace needs from_id and to_id");
      return ownerArgs({
        from_id,
        to_id,
        max_depth: Number($("trace-depth").value) || 5,
        directed: !$("trace-undirected").checked,
      });
    }
    case "get_context": {
      const node_id = $("ctx-node-id").value.trim();
      if (!node_id) throw new Error("get_context needs node_id");
      return ownerArgs({
        node_id,
        depth: Number($("ctx-depth").value) || 0,
        max_nodes: Number($("ctx-max-nodes").value) || 20,
        offset: Number($("ctx-offset").value) || 0,
        include_outdated: $("ctx-outdated").checked,
      });
    }
    case "search": {
      const query = $("search-query").value.trim();
      if (!query) throw new Error("search needs query");
      return ownerArgs({
        query,
        limit: Number($("search-limit").value) || 10,
        ...searchFilters(),
      });
    }
    case "find_similar": {
      const fact_id =
        $("similar-fact-id").value.trim() ||
        state.selectedId ||
        state.anchorId ||
        "";
      if (!fact_id) throw new Error("find_similar needs fact_id");
      return ownerArgs({
        fact_id,
        limit: Number($("similar-limit").value) || 5,
        similarity_threshold: Number($("similar-threshold").value) || 0.55,
      });
    }
    default:
      throw new Error(`unknown tool: ${tool}`);
  }
}

async function runSelectedTool() {
  const tool = $("llm-tool").value;
  const args = buildToolCall(tool);
  await beginToolRun();
  clearPathHighlight();
  const data = await callTool(tool, args);

  if (tool === "get_trace") {
    const nodes = data.nodes || [];
    if (!nodes.length) {
      showToolResult(tool, args, data);
      log(data.message || "no path");
      return data;
    }
    mergeNodes(nodes, { fresh: true });
    mergeEdges(edgesFromTrace(nodes, data.relations || []), { path: true });
    syncGraph({ fullLayout: true, originNodeId: args.from_id });
    centerViewOnNode(args.from_id);
  } else if (tool === "find_similar") {
    const anchor = args.fact_id;
    const ids = new Set([
      anchor,
      ...(data.similar_facts || []).map((f) => f.node_id),
    ]);
    mergeNodes(data.similar_facts, { fresh: true });
    mergeNodes([{ node_id: anchor }], {});
    const ctx = await callTool(
      "get_context",
      ownerArgs({ node_id: anchor, depth: 2, max_nodes: 50 }),
    );
    mergeEdges(
      (ctx.edges || []).filter((e) => ids.has(e.from_id) && ids.has(e.to_id)),
    );
    syncGraph({ originNodeId: anchor, fullLayout: true });
  } else {
    mergeToolResult(data, { fresh: true }, { fullLayout: true });
    const seed =
      data.seeds?.[0]?.node_id ||
      data.results?.[0]?.node_id ||
      args.node_id ||
      null;
    if (seed) {
      state.anchorId = seed;
      if (tool === "get_context") {
        $("ctx-node-id").value = seed;
        persistField("ctx-node-id");
      }
      centerViewOnNode(seed);
    }
  }

  showToolResult(tool, args, data);
  persistField("tool-replace");
  log(`ran ${tool}`);
  return data;
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
      similarity: meta.similarity ?? n.similarity ?? n.score ?? prev.similarity,
      metadata: n.metadata ?? prev.metadata,
      degree: n.degree ?? prev.degree,
      _fresh: meta.fresh !== false,
    });
  }
}

function mergeEdges(edges, { path = false } = {}) {
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

function layoutOptions(name) {
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

function runLayout(name = state.layoutName) {
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

function graphCenterModel() {
  const nodes = cy.nodes(":visible");
  if (nodes.empty()) return viewportCenter();
  const bb = nodes.boundingBox();
  return { x: (bb.x1 + bb.x2) / 2, y: (bb.y1 + bb.y2) / 2 };
}

function rotateGraphAround(degrees, cx, cy0) {
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

function rotateGraph(degrees) {
  const c = graphCenterModel();
  rotateGraphAround(degrees, c.x, c.y);
  log(`rotate ${degrees > 0 ? "+" : ""}${degrees}°`);
}

function renderedToModel(renderedX, renderedY) {
  const pan = cy.pan();
  const zoom = cy.zoom();
  return {
    x: (renderedX - pan.x) / zoom,
    y: (renderedY - pan.y) / zoom,
  };
}

function angleFromCenter(modelX, modelY, cx, cy0) {
  return Math.atan2(modelY - cy0, modelX - cx);
}

function syncGraph({ fullLayout = false, originNodeId = null } = {}) {
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
  applyViewFilters();
  applyLabelVisibility();
  cy.nodes().forEach((n) => n.lock(state.nodesLocked));

  if (fullLayout && cy.nodes(":visible").length > 1) {
    runLayout(state.layoutName);
  }

  for (const n of state.nodes.values()) n._fresh = false;
}

function applyNodeColors() {
  cy.nodes().forEach((ele) => {
    const st = nodeStyle(ele.data("nodeType"), ele.data("status"));
    ele.style({ backgroundColor: st.background, shape: st.shape });
  });
}

function applyViewFilters() {
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

function applyLabelVisibility() {
  const nodeLabels = $("view-node-labels").checked;
  const edgeLabels = $("view-edge-labels").checked;
  cy.style()
    .selector("node")
    .style("label", nodeLabels ? "data(label)" : "")
    .selector("edge")
    .style("label", edgeLabels ? "data(label)" : "")
    .update();
}

function centerViewOnNode(nodeId) {
  const node = cy.getElementById(nodeId);
  if (node.empty()) return;
  cy.animate({ center: { eles: node }, duration: 200 });
}

function updateStats() {
  const vis = cy.nodes(":visible").length;
  $("stats-bar").textContent = `${state.nodes.size} nodes · ${state.edges.size} edges · ${vis} visible · ${state.layoutName}`;
}

let cy = cytoscape({
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
      selector: "node:selected",
      style: { "border-color": "#fbbf24", "border-width": 3 },
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

async function loadNodeDetail(nodeId) {
  const data = await callTool("get_node", ownerArgs({ node_id: nodeId }));
  mergeToolResult(data, {}, { originNodeId: nodeId });
  showDetail(nodeId, data.node);
}

function neighborInfo(nodeId) {
  return (
    state.neighborState.get(nodeId) || {
      offset: 0,
      pageSize: Number($("neighbor-page-size")?.value) || 10,
      hasMore: true,
      loaded: 0,
      batchIds: [],
    }
  );
}

function updateNeighborUi(nodeId) {
  if (!nodeId || state.selectedId !== nodeId) return;
  const info = neighborInfo(nodeId);
  const status = $("neighbor-status");
  const moreBtn = $("btn-neighbors-more");
  const loadBtn = $("btn-neighbors");
  const selMore = $("btn-sel-more");
  const selStatus = $("sel-action-status");

  if (info.loaded === 0 && !state.neighborState.has(nodeId)) {
    status.textContent = "Not loaded yet — fetch 1-hop neighbors.";
    loadBtn.textContent = "Load neighbors";
    moreBtn.hidden = true;
    selMore.hidden = true;
    selStatus.textContent = "";
  } else {
    status.textContent = info.hasMore
      ? `Loaded ${info.loaded} · next offset ${info.offset} · more available`
      : `Loaded ${info.loaded} · no more pages`;
    loadBtn.textContent = "Reload from start";
    moreBtn.hidden = !info.hasMore;
    selMore.hidden = !info.hasMore;
    selStatus.textContent = info.hasMore
      ? `${info.loaded} loaded · more`
      : `${info.loaded} loaded`;
  }

  const list = $("neighbor-list");
  const ids = info.batchIds || [];
  list.innerHTML = ids.length
    ? ids
        .map((id) => {
          const n = state.nodes.get(id);
          return `<li data-id="${id}" title="${id}">${preview(n?.text || id, 42)}</li>`;
        })
        .join("")
    : "<li class='muted'>none in last page</li>";

  updateSelAction();
}

function updateSelAction() {
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
  const meta = n.metadata;
  $("detail-meta").textContent =
    meta && Object.keys(meta).length ? JSON.stringify(meta, null, 2) : "(none)";

  const related = [];
  for (const e of state.edges.values()) {
    if (e.from_id === nodeId) related.push(`→ ${e.relation_type} → ${e.to_id}`);
    if (e.to_id === nodeId) related.push(`← ${e.relation_type} ← ${e.from_id}`);
  }
  $("detail-edges").innerHTML = related.length
    ? related.map((x) => `<li>${x}</li>`).join("")
    : "<li class='muted'>none in view</li>";

  updateNeighborUi(nodeId);
}

async function loadHistory() {
  const id = state.selectedId;
  if (!id) return;
  const data = await callTool(
    "get_node_change_history",
    ownerArgs({ node_id: id }),
  );
  const versions = data.versions || [];
  $("detail-history").innerHTML = versions.length
    ? versions
        .map(
          (v) =>
            `<li>${preview(v.text, 40)} <span class="muted">@${v.version_timestamp}</span></li>`,
        )
        .join("")
    : "<li class='muted'>no versions</li>";
  log(`history ${id}: ${versions.length}`);
}

async function focusNode(nodeId, { loadDetail = true } = {}) {
  state.anchorId = nodeId;
  $("ctx-node-id").value = nodeId;
  $("similar-fact-id").value = nodeId;
  persistField("ctx-node-id");
  persistField("similar-fact-id");
  if (loadDetail) await loadNodeDetail(nodeId);
  showDetail(nodeId);
  const ele = cy.getElementById(nodeId);
  if (ele.nonempty()) {
    cy.$(":selected").unselect();
    ele.select();
    centerViewOnNode(nodeId);
  }
  updateSelAction();
  log(`selected ${nodeId}`);
}

async function loadNeighbors(nodeId, { reset = false, pageSize } = {}) {
  const size =
    pageSize || Number($("neighbor-page-size").value) || 10;
  let info = neighborInfo(nodeId);
  if (reset || !state.neighborState.has(nodeId)) {
    info = {
      offset: 0,
      pageSize: size,
      hasMore: true,
      loaded: 0,
      batchIds: [],
    };
  } else {
    info = { ...info, pageSize: size };
  }

  const args = ownerArgs({
    node_id: nodeId,
    depth: 1,
    max_nodes: info.pageSize,
    include_outdated: $("ctx-outdated")?.checked || false,
  });
  if (info.offset > 0) args.offset = info.offset;

  const data = await callTool("get_context", args);
  const before = new Set(state.nodes.keys());
  mergeToolResult(data, { fresh: true }, { originNodeId: nodeId });

  const returnedNodes = (data.nodes || []).filter((n) => n.node_id !== nodeId);
  const batchIds = returnedNodes.map((n) => n.node_id);
  const newCount = batchIds.filter((id) => !before.has(id)).length;
  const returned = data.nodes?.length || 0;

  // offset=0 uses BFS (no has_more); treat full page as "maybe more"
  let hasMore;
  if (info.offset > 0) {
    hasMore = data.has_more === true;
  } else {
    hasMore = returned >= info.pageSize;
  }

  const nextOffset = info.offset + info.pageSize;
  info = {
    offset: hasMore ? nextOffset : info.offset + returned,
    pageSize: info.pageSize,
    hasMore,
    loaded: info.loaded + returnedNodes.length,
    batchIds,
  };
  state.neighborState.set(nodeId, info);
  updateNeighborUi(nodeId);
  log(
    `neighbors ${nodeId} offset=${args.offset || 0} +${returnedNodes.length}` +
      (newCount ? ` (${newCount} new)` : ""),
  );
  return data;
}

function renderOverview(data) {
  const stats = data.stats || {};
  const parts = [];
  if (stats.total_facts != null) parts.push(`${stats.total_facts} facts`);
  if (stats.total_entities != null) parts.push(`${stats.total_entities} entities`);
  if (stats.total_relations != null) parts.push(`${stats.total_relations} rels`);
  if (stats.active_facts != null) parts.push(`${stats.active_facts} active`);
  $("overview-stats").textContent = parts.length ? parts.join(" · ") : "no stats";

  const blocks = [];
  const top = data.top_facts || [];
  if (top.length) {
    blocks.push(`<div class="ov-block"><h3>Top facts</h3><ul class="ov-list">
      ${top
        .map(
          (f) =>
            `<li data-id="${f.node_id}" title="${f.node_id}">${preview(f.text, 56)}${f.degree != null ? ` <span class="muted">·${f.degree}</span>` : ""}</li>`,
        )
        .join("")}
    </ul></div>`);
  }

  const contra = data.contradictions || [];
  if (contra.length) {
    blocks.push(`<div class="ov-block"><h3>Contradicts</h3><ul class="ov-list">
      ${contra
        .map(
          (c) =>
            `<li class="contradict" data-from="${c.from_id}" data-to="${c.to_id}">
              <span data-id="${c.from_id}">${preview(c.from_text, 28)}</span>
              <span class="sep">⚡</span>
              <span data-id="${c.to_id}">${preview(c.to_text, 28)}</span>
            </li>`,
        )
        .join("")}
    </ul></div>`);
  }

  const stale = data.stale_facts || [];
  if (stale.length) {
    blocks.push(`<div class="ov-block"><h3>Stale</h3><ul class="ov-list">
      ${stale
        .map(
          (f) =>
            `<li data-id="${f.node_id}" title="${f.node_id}">${preview(f.text, 56)}</li>`,
        )
        .join("")}
    </ul></div>`);
  }

  $("overview").innerHTML = blocks.length
    ? blocks.join("")
    : `<p class="muted">empty owner</p>`;
}

async function loadBrief() {
  const data = await callTool("get_brief", ownerArgs({ limit: 10 }));
  renderOverview(data);
  const seedNodes = [...(data.top_facts || []), ...(data.stale_facts || [])];
  for (const c of data.contradictions || []) {
    seedNodes.push(
      { node_id: c.from_id, text: c.from_text },
      { node_id: c.to_id, text: c.to_text },
    );
  }
  mergeNodes(seedNodes, { fresh: true });
  mergeEdges(
    (data.contradictions || []).map((c) => ({
      from_id: c.from_id,
      to_id: c.to_id,
      relation_type: "CONTRADICTS",
    })),
  );
  syncGraph({ fullLayout: cy.nodes().length === 0 && seedNodes.length > 1 });
  updateStats();
  log(
    `brief: top=${data.top_facts?.length || 0} contra=${data.contradictions?.length || 0} stale=${data.stale_facts?.length || 0}`,
  );
}

function clearGraph({ quiet = false } = {}) {
  cy.elements().remove();
  state.nodes.clear();
  state.edges.clear();
  state.neighborState.clear();
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

function exportPng() {
  const png = cy.png({ full: true, scale: 2, bg: "#111820" });
  const a = document.createElement("a");
  a.href = png;
  a.download = `graph-memory-${Date.now()}.png`;
  a.click();
  log("exported PNG");
}

function toggleLock() {
  state.nodesLocked = !state.nodesLocked;
  cy.nodes().forEach((n) => n.lock(state.nodesLocked));
  const btn = $("btn-lock");
  btn.textContent = state.nodesLocked ? "🔒" : "🔓";
  btn.classList.toggle("active-lock", state.nodesLocked);
  log(state.nodesLocked ? "nodes locked" : "nodes unlocked");
}

const hoverPlus = $("hover-plus");
let hidePlusTimer = null;

function positionHoverPlus(node) {
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
  cy.$(":selected").unselect();
  evt.target.select();
  showDetail(id);
  updateSelAction();
  loadNodeDetail(id).catch((e) => log(`detail error: ${e.message}`));
});

cy.on("tap", (evt) => {
  if (evt.target === cy) {
    $("sel-action").hidden = true;
  }
});

cy.on("dbltap", "node", (evt) => {
  const id = evt.target.id();
  loadNeighbors(id, { reset: !state.neighborState.has(id) }).catch((err) =>
    log(`expand: ${err.message}`),
  );
});

cy.on("mouseover", "node", (evt) => {
  showHoverPlus(evt.target);
});

cy.on("mouseout", "node", () => {
  scheduleHideHoverPlus();
});

cy.on("pan zoom", () => {
  refreshHoverPlusPosition();
  updateSelAction();
});

cy.on("drag", "node", (evt) => {
  if (state.hoverId === evt.target.id()) positionHoverPlus(evt.target);
  if (state.selectedId === evt.target.id()) updateSelAction();
});

cy.on("position", "node", (evt) => {
  if (state.hoverId === evt.target.id()) positionHoverPlus(evt.target);
  if (state.selectedId === evt.target.id()) updateSelAction();
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
  const reset = !state.neighborState.has(id);
  loadNeighbors(id, { reset }).catch((err) => log(`neighbors: ${err.message}`));
});

function isTypingTarget(el) {
  if (!el || el === document.body) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

// Space+drag pan · Alt+drag rotate · [ ] rotate · f fit · r re-layout
window.addEventListener("keydown", (e) => {
  if (isTypingTarget(e.target)) return;
  if (e.code === "Space") {
    e.preventDefault();
    state.spacePan = true;
    cy.userPanningEnabled(true);
    cy.boxSelectionEnabled(false);
    cy.container().classList.add("space-pan");
  }
  if (e.key === "f" && !e.metaKey && !e.ctrlKey) {
    cy.fit(undefined, 40);
  }
  if (e.key === "r" && !e.metaKey && !e.ctrlKey) {
    runLayout(state.layoutName);
  }
  if (e.key === "[" && !e.metaKey && !e.ctrlKey) {
    rotateGraph(-15);
  }
  if (e.key === "]" && !e.metaKey && !e.ctrlKey) {
    rotateGraph(15);
  }
});

window.addEventListener("keyup", (e) => {
  if (e.code === "Space") {
    state.spacePan = false;
    cy.boxSelectionEnabled(true);
    cy.container().classList.remove("space-pan");
  }
});

cy.on("mousedown", (evt) => {
  if (!evt.originalEvent?.altKey) return;
  if (evt.target !== cy) return; // only on background
  const c = graphCenterModel();
  const m = renderedToModel(evt.renderedPosition.x, evt.renderedPosition.y);
  state.rotateDrag = {
    active: true,
    cx: c.x,
    cy: c.y,
    lastAngle: angleFromCenter(m.x, m.y, c.x, c.y),
  };
  cy.userPanningEnabled(false);
  cy.userZoomingEnabled(false);
  cy.container().classList.add("rotating");
});

cy.on("mousemove", (evt) => {
  const rd = state.rotateDrag;
  if (!rd?.active) return;
  const m = renderedToModel(evt.renderedPosition.x, evt.renderedPosition.y);
  const ang = angleFromCenter(m.x, m.y, rd.cx, rd.cy);
  let delta = ang - rd.lastAngle;
  // unwrap jumps across ±π
  if (delta > Math.PI) delta -= 2 * Math.PI;
  if (delta < -Math.PI) delta += 2 * Math.PI;
  rd.lastAngle = ang;
  rotateGraphAround((delta * 180) / Math.PI, rd.cx, rd.cy);
});

function endRotateDrag() {
  if (!state.rotateDrag?.active) return;
  state.rotateDrag = null;
  cy.userPanningEnabled(true);
  cy.userZoomingEnabled(true);
  cy.container().classList.remove("rotating");
  log("rotated (alt+drag)");
}

cy.on("mouseup", endRotateDrag);
window.addEventListener("mouseup", endRotateDrag);

loadPersistedFields();
bindPersistence();
setTool($("llm-tool").value || "recall_context");

$("owner-id").addEventListener("change", () => {
  state.ownerId = $("owner-id").value.trim() || "default";
  persistField("owner-id");
  loadBrief().catch((e) => log(`brief: ${e.message}`));
});

$("btn-brief").addEventListener("click", () => {
  loadBrief().catch((e) => log(`brief: ${e.message}`));
});

$("llm-tool").addEventListener("change", () => {
  setTool($("llm-tool").value);
});

function onRunToolClick() {
  runSelectedTool().catch((e) => {
    $("tool-summary").textContent = e.message;
    $("tool-summary").classList.add("muted");
    log(`tool error: ${e.message}`);
  });
}

$("btn-run-tool").addEventListener("click", onRunToolClick);

$("tool-call-section").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (e.target.tagName === "TEXTAREA" && !e.metaKey && !e.ctrlKey) return;
  if (e.target.tagName === "TEXTAREA" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    onRunToolClick();
    return;
  }
  if (e.target.tagName === "INPUT") {
    e.preventDefault();
    onRunToolClick();
  }
});

$("overview").addEventListener("click", (e) => {
  const idEl = e.target.closest("[data-id]");
  if (idEl?.dataset.id) {
    focusNode(idEl.dataset.id).catch((err) => log(err.message));
    return;
  }
  const pair = e.target.closest("[data-from][data-to]");
  if (pair) {
    setTool("get_trace");
    $("trace-from").value = pair.dataset.from;
    $("trace-to").value = pair.dataset.to;
    runSelectedTool().catch((err) => log(`trace: ${err.message}`));
  }
});

$("btn-clear").addEventListener("click", () => clearGraph());

$("btn-set-anchor").addEventListener("click", () => {
  if (!state.selectedId) return;
  setTool("get_context");
  $("ctx-node-id").value = state.selectedId;
  persistField("ctx-node-id");
  log(`filled get_context node_id=${state.selectedId}`);
});

$("btn-neighbors").addEventListener("click", () => {
  if (!state.selectedId) return;
  loadNeighbors(state.selectedId, { reset: true }).catch((e) => log(e.message));
});

$("btn-neighbors-more").addEventListener("click", () => {
  if (!state.selectedId) return;
  loadNeighbors(state.selectedId, { reset: false }).catch((e) => log(e.message));
});

$("btn-sel-neighbors").addEventListener("click", (e) => {
  e.stopPropagation();
  if (!state.selectedId) return;
  loadNeighbors(state.selectedId, { reset: true }).catch((err) => log(err.message));
});

$("btn-sel-more").addEventListener("click", (e) => {
  e.stopPropagation();
  if (!state.selectedId) return;
  loadNeighbors(state.selectedId, { reset: false }).catch((err) => log(err.message));
});

$("neighbor-list").addEventListener("click", (e) => {
  const idEl = e.target.closest("[data-id]");
  if (idEl?.dataset.id) {
    focusNode(idEl.dataset.id).catch((err) => log(err.message));
  }
});

$("btn-history").addEventListener("click", () => {
  loadHistory().catch((e) => log(`history: ${e.message}`));
});

$("btn-trace-from").addEventListener("click", () => {
  if (!state.selectedId) return;
  setTool("get_trace");
  $("trace-from").value = state.selectedId;
  persistField("trace-from");
});

$("btn-trace-to").addEventListener("click", () => {
  if (!state.selectedId) return;
  setTool("get_trace");
  $("trace-to").value = state.selectedId;
  persistField("trace-to");
});

$("btn-layout").addEventListener("click", () => {
  runLayout($("layout-mode").value);
});

$("layout-mode").addEventListener("change", () => {
  runLayout($("layout-mode").value);
});

$("btn-rotate-cw").addEventListener("click", () => rotateGraph(15));
$("btn-rotate-ccw").addEventListener("click", () => rotateGraph(-15));
$("btn-fit").addEventListener("click", () => cy.fit(undefined, 40));
$("btn-center-sel").addEventListener("click", () => {
  const sel = cy.$(":selected");
  if (sel.nonempty()) cy.animate({ center: { eles: sel }, duration: 200 });
  else if (state.selectedId) centerViewOnNode(state.selectedId);
  else cy.fit(undefined, 40);
});
$("btn-lock").addEventListener("click", toggleLock);
$("btn-png").addEventListener("click", exportPng);

[
  "view-fact",
  "view-entity",
  "view-active",
  "view-outdated",
  "view-archived",
].forEach((id) => {
  $(id).addEventListener("change", () => {
    applyViewFilters();
    updateStats();
  });
});

$("view-node-labels").addEventListener("change", applyLabelVisibility);
$("view-edge-labels").addEventListener("change", applyLabelVisibility);

async function checkHealth() {
  const badge = $("status-badge");
  try {
    const res = await fetch("/health");
    const data = await res.json();
    if (data.ready) {
      badge.textContent = "FalkorDB connected";
      badge.className = "badge badge-ok";
      loadBrief().catch((e) => log(`brief: ${e.message}`));
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
log(
  "ready — LLM tool call (recall_context / get_trace) · click node → 1-hop neighbors",
);
