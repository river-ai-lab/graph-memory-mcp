import { $, log, copyText } from "./dom.js";
import { state } from "./state.js";
import {
  loadPersistedFields,
  bindPersistence,
  persistField,
  resetPersistedForms,
  setTool,
} from "./persist.js";
import {
  cy,
  clearGraph,
  runLayout,
  rotateGraph,
  exportPng,
  exportJson,
  toggleLock,
  centerViewOnNode,
  applyViewFilters,
  applyLabelVisibility,
  updateStats,
  setBusy,
} from "./graph.js";
import { runSelectedTool } from "./tools.js";
import { loadBrief, focusNode, loadHistory } from "./detail.js";
import { loadNeighbors } from "./neighbors.js";

export function bindPanelControls() {
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
      if (e?.name === "AbortError") return;
      $("tool-summary").textContent = e.message;
      $("tool-summary").classList.add("muted");
      log(`tool error: ${e.message}`);
      setBusy(false);
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

  $("tool-call-section").addEventListener("input", (e) => {
    const el = e.target;
    if (el?.classList?.contains("has-error")) {
      el.classList.remove("has-error");
      el.closest(".field")?.querySelector(".field-error")?.remove();
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
      persistField("trace-from");
      persistField("trace-to");
      onRunToolClick();
    }
  });

  $("btn-clear").addEventListener("click", () => clearGraph());

  $("btn-reset-forms").addEventListener("click", () => {
    if (!confirm("Reset saved scope and tool form values?")) return;
    resetPersistedForms();
  });

  $("btn-copy-id").addEventListener("click", () => {
    copyText($("detail-id").textContent, "node id copied");
  });

  $("btn-copy-raw").addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    copyText($("tool-raw").textContent, "raw JSON copied");
  });

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
  $("btn-json").addEventListener("click", exportJson);

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
}

export async function checkHealth() {
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
