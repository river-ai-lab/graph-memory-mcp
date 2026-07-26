import { $, log } from "./dom.js";
import { state } from "./state.js";

export const TOOL_HINTS = {
  recall_context:
    "Semantic search + expand around seeds. Closest to “ask the memory a question”.",
  get_trace:
    "Shortest path between two node uids. Highlighted as gold path edges.",
  get_context:
    "Subgraph around one node. Neighbor UI uses a local buffer from one BFS fetch.",
  search:
    "Return ranked hits only (no expansion). Scope project/tags apply as filters.",
  find_similar:
    "Embedding-near facts for a given fact_id. Then draws edges among them.",
  search_triplets:
    "Find Entity–relation–Entity triplets. Drawn as amber edges between entities.",
  get_stats:
    "Owner-level counts only. Does not change the canvas (replace ignored).",
};

export const PERSIST_FIELDS = [
  { id: "owner-id", key: "gm_owner_id", type: "text", fallback: "default" },
  { id: "scope-project", key: "gm_scope_project", type: "text" },
  { id: "scope-tags", key: "gm_scope_tags", type: "text" },
  { id: "scope-outdated", key: "gm_scope_outdated", type: "checkbox", fallback: false },
  { id: "llm-tool", key: "gm_llm_tool", type: "text", fallback: "recall_context" },
  { id: "tool-replace", key: "gm_tool_replace", type: "checkbox", fallback: true },
  { id: "recall-query", key: "gm_recall_query", type: "text" },
  { id: "recall-limit", key: "gm_recall_limit", type: "text", fallback: "8" },
  { id: "recall-depth", key: "gm_recall_depth", type: "text", fallback: "1" },
  { id: "recall-max-nodes", key: "gm_recall_max_nodes", type: "text", fallback: "30" },
  { id: "recall-threshold", key: "gm_recall_threshold", type: "text" },
  { id: "recall-paths", key: "gm_recall_paths", type: "checkbox", fallback: false },
  { id: "trace-from", key: "gm_trace_from", type: "text" },
  { id: "trace-to", key: "gm_trace_to", type: "text" },
  { id: "trace-depth", key: "gm_trace_depth", type: "text", fallback: "5" },
  { id: "trace-undirected", key: "gm_trace_undirected", type: "checkbox", fallback: false },
  { id: "ctx-node-id", key: "gm_ctx_node_id", type: "text" },
  { id: "ctx-depth", key: "gm_ctx_depth", type: "text", fallback: "1" },
  { id: "ctx-max-nodes", key: "gm_ctx_max_nodes", type: "text", fallback: "20" },
  { id: "ctx-offset", key: "gm_ctx_offset", type: "text", fallback: "0" },
  { id: "search-query", key: "gm_search_query", type: "text" },
  { id: "search-limit", key: "gm_search_limit", type: "text", fallback: "10" },
  { id: "search-status", key: "gm_search_status", type: "text" },
  { id: "type-fact", key: "gm_type_fact", type: "checkbox", fallback: true },
  { id: "type-entity", key: "gm_type_entity", type: "checkbox", fallback: true },
  { id: "similar-fact-id", key: "gm_similar_fact_id", type: "text" },
  { id: "similar-limit", key: "gm_similar_limit", type: "text", fallback: "5" },
  { id: "similar-threshold", key: "gm_similar_threshold", type: "text", fallback: "0.55" },
  { id: "trip-subject", key: "gm_trip_subject", type: "text" },
  { id: "trip-predicate", key: "gm_trip_predicate", type: "text" },
  { id: "trip-object", key: "gm_trip_object", type: "text" },
  { id: "trip-limit", key: "gm_trip_limit", type: "text", fallback: "10" },
  { id: "neighbor-page-size", key: "gm_neighbor_page", type: "text", fallback: "10" },
  { id: "layout-mode", key: "gm_layout", type: "text", fallback: "cose" },
];

export function loadPersistedFields() {
  // migrate old per-tool outdated flags into shared scope once
  if (localStorage.getItem("gm_scope_outdated") === null) {
    if (
      localStorage.getItem("gm_recall_outdated") === "1" ||
      localStorage.getItem("gm_ctx_outdated") === "1"
    ) {
      localStorage.setItem("gm_scope_outdated", "1");
    }
  }
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

export function resetPersistedForms() {
  for (const f of PERSIST_FIELDS) localStorage.removeItem(f.key);
  localStorage.removeItem("gm_recall_outdated");
  localStorage.removeItem("gm_ctx_outdated");
  for (const f of PERSIST_FIELDS) {
    const el = $(f.id);
    if (!el) continue;
    if (f.type === "checkbox") el.checked = !!f.fallback;
    else el.value = f.fallback != null ? String(f.fallback) : "";
  }
  state.ownerId = "default";
  state.layoutName = "cose";
  clearFieldErrors();
  setTool("recall_context");
  $("tool-summary").textContent = "Forms reset to defaults (browser storage cleared).";
  $("tool-summary").classList.add("muted");
  $("tool-raw").textContent = "";
  log("forms reset");
}

export function clearFieldErrors() {
  document.querySelectorAll(".field-error").forEach((el) => el.remove());
  document.querySelectorAll(".has-error").forEach((el) => el.classList.remove("has-error"));
}

export function setFieldError(inputId, message) {
  const el = $(inputId);
  if (!el) return;
  el.classList.add("has-error");
  const host = el.closest(".field") || el.parentElement;
  if (!host) return;
  const existing = host.querySelector(".field-error");
  if (existing) {
    existing.textContent = message;
    return;
  }
  const err = document.createElement("span");
  err.className = "field-error";
  err.textContent = message;
  host.appendChild(err);
}

export function validateTool(tool) {
  clearFieldErrors();
  let ok = true;
  const need = (id, msg) => {
    const v = $(id)?.value?.trim?.() ?? "";
    if (!v) {
      setFieldError(id, msg);
      ok = false;
    }
  };
  if (tool === "recall_context") need("recall-query", "Required — the question / query text.");
  if (tool === "get_trace") {
    need("trace-from", "Required — start node uid.");
    need("trace-to", "Required — end node uid.");
  }
  if (tool === "get_context") need("ctx-node-id", "Required — center node uid.");
  if (tool === "search") need("search-query", "Required — search text.");
  if (tool === "find_similar") {
    const fact =
      $("similar-fact-id").value.trim() || state.selectedId || state.anchorId || "";
    if (!fact) {
      setFieldError("similar-fact-id", "Required — fact uid, or select a node first.");
      ok = false;
    }
  }
  if (tool === "search_triplets") {
    const any =
      $("trip-subject").value.trim() ||
      $("trip-predicate").value.trim() ||
      $("trip-object").value.trim();
    if (!any) {
      setFieldError("trip-subject", "Provide at least subject, predicate, or object.");
      ok = false;
    }
  }
  return ok;
}

export function persistField(id) {
  const f = PERSIST_FIELDS.find((x) => x.id === id);
  const el = $(id);
  if (!f || !el) return;
  if (f.type === "checkbox") localStorage.setItem(f.key, el.checked ? "1" : "0");
  else localStorage.setItem(f.key, el.value);
}

export function bindPersistence() {
  for (const f of PERSIST_FIELDS) {
    const el = $(f.id);
    if (!el) continue;
    const ev = f.type === "checkbox" || el.tagName === "SELECT" ? "change" : "input";
    el.addEventListener(ev, () => persistField(f.id));
    el.addEventListener("change", () => persistField(f.id));
  }
}

export function setTool(tool) {
  $("llm-tool").value = tool;
  for (const el of document.querySelectorAll(".tool-params")) {
    el.hidden = el.id !== `params-${tool}`;
  }
  const hint = $("tool-hint");
  if (hint) hint.textContent = TOOL_HINTS[tool] || "";
  persistField("llm-tool");
}

