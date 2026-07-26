import { $, log, sleep } from "./dom.js";
import { KNOWN_EDGE_TYPES } from "./state.js";

export function scopeIncludeOutdated() {
  return !!$("scope-outdated")?.checked;
}

export async function callTool(tool, arguments_, { signal, retries = 3 } = {}) {
  let lastErr = null;
  for (let attempt = 0; attempt <= retries; attempt++) {
    if (signal?.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }
    let res;
    try {
      res = await fetch("/api/tool", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool, arguments: arguments_ }),
        signal,
      });
    } catch (err) {
      if (err?.name === "AbortError") throw err;
      lastErr = err;
      if (attempt < retries) {
        await sleep(400 * 2 ** attempt);
        continue;
      }
      throw err;
    }

    if (res.status === 503 && attempt < retries) {
      log(`MCP not ready (503) — retry ${attempt + 1}/${retries}…`);
      await sleep(500 * 2 ** attempt);
      continue;
    }

    let data;
    try {
      data = await res.json();
    } catch {
      throw new Error(`HTTP ${res.status}: invalid JSON`);
    }
    if (!res.ok || data.success === false) {
      const msg = data.error || `HTTP ${res.status}`;
      if (res.status === 503 && attempt < retries) {
        log(`MCP not ready — retry ${attempt + 1}/${retries}…`);
        await sleep(500 * 2 ** attempt);
        continue;
      }
      throw new Error(msg);
    }
    return data;
  }
  throw lastErr || new Error("request failed");
}

export function ownerArgs(extra = {}) {
  return { owner_id: $("owner-id").value.trim() || "default", ...extra };
}

export function preview(text, n = 48) {
  if (!text) return "(empty)";
  const s = String(text).replace(/\s+/g, " ").trim();
  return s.length <= n ? s : `${s.slice(0, n)}…`;
}

export function nodeStyle(nodeType, status) {
  const base =
    nodeType === "Entity"
      ? { background: "#7c3aed", shape: "diamond" }
      : { background: "#16a34a", shape: "ellipse" };
  if (status === "outdated") base.background = "#64748b";
  if (status === "archived") base.background = "#475569";
  return base;
}

export function edgeClass(relationType) {
  const t = relationType || "RELATED";
  if (t === "CONTRADICTS") return "edge-contradicts";
  if (t === "SUMMARIZES") return "edge-summarizes";
  if (!KNOWN_EDGE_TYPES.has(t)) return "edge-triplet";
  return "edge-default";
}

export function parseTags(raw) {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export function scopeMetadataFilter() {
  const project = $("scope-project").value.trim();
  const tags = parseTags($("scope-tags").value.trim());
  const mf = {};
  if (project) mf.project = project;
  if (tags.length) mf.tags = tags;
  return Object.keys(mf).length ? mf : null;
}

export function searchFilters() {
  const extra = {};
  const status = $("search-status").value;
  if (status) {
    extra.status = status;
    if (status !== "active") extra.include_outdated = true;
  } else if (scopeIncludeOutdated()) {
    extra.include_outdated = true;
  }
  const fact = $("type-fact").checked;
  const entity = $("type-entity").checked;
  if (fact && !entity) extra.node_types = ["Fact"];
  else if (entity && !fact) extra.node_types = ["Entity"];
  const mf = scopeMetadataFilter();
  if (mf) extra.metadata_filter = mf;
  return extra;
}
