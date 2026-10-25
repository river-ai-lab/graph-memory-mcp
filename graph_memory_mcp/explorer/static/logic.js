/* Testable Explorer helpers. No DOM. Used by explorer.js and logic.test.cjs. */
(function (root) {
  const PREVIEW_KEY = "gm_node_preview";
  const PREVIEW_ALWAYS = "always";
  const PREVIEW_HOVER = "hover";
  const ALWAYS_CHARS = 36;
  const HOVER_CHARS = 62;
  const DENSE_ZOOM = 0.5;

  function preview(text, n) {
    if (n == null) n = 48;
    if (!text) return "(empty)";
    const s = String(text).replace(/\s+/g, " ").trim();
    return s.length <= n ? s : `${s.slice(0, n)}…`;
  }

  function parseTime(value) {
    if (value == null || value === "") return null;
    if (value instanceof Date) {
      return Number.isFinite(value.getTime()) ? value : null;
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      return new Date(value < 1e12 ? value * 1000 : value);
    }
    const raw = String(value).trim();
    if (/^\d+$/.test(raw)) {
      const n = Number(raw);
      return new Date(n < 1e12 ? n * 1000 : n);
    }
    const date = new Date(raw);
    return Number.isFinite(date.getTime()) ? date : null;
  }

  function formatTime(value, includeSeconds) {
    const date = parseTime(value);
    if (!date) return value ? String(value) : "—";
    return new Intl.DateTimeFormat("en-GB", {
      dateStyle: "medium",
      timeStyle: includeSeconds ? "medium" : "short",
      hour12: false,
    }).format(date);
  }

  function normalizePreviewMode(value) {
    return value === PREVIEW_ALWAYS ? PREVIEW_ALWAYS : PREVIEW_HOVER;
  }

  function readPreviewMode(store) {
    try {
      return normalizePreviewMode((store || {}).getItem(PREVIEW_KEY));
    } catch {
      return PREVIEW_HOVER;
    }
  }

  function writePreviewMode(store, value) {
    const mode = normalizePreviewMode(value);
    try {
      (store || {}).setItem(PREVIEW_KEY, mode);
    } catch {
      /* ignore quota / private mode */
    }
    return mode;
  }

  function previewChars(mode) {
    return normalizePreviewMode(mode) === PREVIEW_ALWAYS ? ALWAYS_CHARS : HOVER_CHARS;
  }

  function shouldShowAlwaysLabels(mode, zoom) {
    return (
      normalizePreviewMode(mode) === PREVIEW_ALWAYS &&
      !(typeof zoom === "number" && zoom < DENSE_ZOOM)
    );
  }

  function contradictionEdges(pairs) {
    const edges = [];
    for (const pair of pairs || []) {
      const fromId = pair && (pair.from_id || pair.fromId);
      const toId = pair && (pair.to_id || pair.toId);
      if (!fromId || !toId) continue;
      edges.push({
        from_id: String(fromId),
        to_id: String(toId),
        relation_type: pair.relation_type || "CONTRADICTS",
      });
    }
    return edges;
  }

  function toolArguments(hideOwner, extra) {
    const args = { ...(extra || {}) };
    if (hideOwner) delete args.owner_id;
    return args;
  }

  function searchFilterArgs(status) {
    const extra = {};
    if (status) {
      extra.status = status;
      if (status !== "active") extra.include_outdated = true;
    } else {
      extra.include_outdated = true;
    }
    return extra;
  }

  function resultMeta(node) {
    const n = node || {};
    const bits = [n.node_type || "Fact", n.status || "active"];
    if (n.similarity != null && n.similarity !== "") {
      bits.push(`similarity ${Number(n.similarity).toFixed(3)}`);
    }
    const meta = n.metadata || {};
    if (meta.valid_from) bits.push(`from ${meta.valid_from}`);
    if (meta.valid_until) bits.push(`until ${meta.valid_until}`);
    return bits.join(" · ");
  }

  function provenanceRows(node) {
    const n = node || {};
    const meta = n.metadata || {};
    const rows = [
      ["Source", n.source && n.source.ref],
      ["Created", n.created_at],
      ["Updated", n.updated_at],
      ["Author", (n.created_by || (meta && meta.created_by))],
      ["Updated by", n.updated_by || (meta && meta.updated_by)],
      ["Project", meta.project],
      ["Tags", Array.isArray(meta.tags) ? meta.tags.join(", ") : meta.tags],
      ["Entity type", n.type || meta.type],
      ["Valid from", meta.valid_from],
      ["Valid until", meta.valid_until],
      ["TTL days", n.ttl_days],
      ["Expires", n.expires_at],
    ];
    return rows.filter(([, value]) => value != null && value !== "");
  }

  const api = {
    PREVIEW_KEY,
    PREVIEW_ALWAYS,
    PREVIEW_HOVER,
    ALWAYS_CHARS,
    HOVER_CHARS,
    DENSE_ZOOM,
    preview,
    parseTime,
    formatTime,
    normalizePreviewMode,
    readPreviewMode,
    writePreviewMode,
    previewChars,
    shouldShowAlwaysLabels,
    contradictionEdges,
    toolArguments,
    searchFilterArgs,
    resultMeta,
    provenanceRows,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ExplorerLogic = api;
})(typeof globalThis === "undefined" ? this : globalThis);
