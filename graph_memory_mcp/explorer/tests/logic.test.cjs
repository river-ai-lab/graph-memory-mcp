const { test } = require("node:test");
const assert = require("node:assert/strict");
const logic = require("../static/logic.js");

test("formatTime accepts unix ms numbers and numeric strings", () => {
  const ms = Date.UTC(2026, 9, 1, 12, 0, 0);
  const fromNumber = logic.formatTime(ms);
  const fromString = logic.formatTime(String(ms));
  assert.notEqual(fromNumber, "—");
  assert.equal(fromNumber, fromString);
  assert.match(fromNumber, /2026/);
  assert.equal(logic.formatTime(null), "—");
  assert.equal(logic.formatTime(""), "—");
});

test("preview truncates without breaking empty text", () => {
  assert.equal(logic.preview(""), "(empty)");
  assert.equal(logic.preview("short"), "short");
  assert.equal(logic.preview("x".repeat(50), 10), `${"x".repeat(10)}…`);
});

test("preview mode persists and defaults to hover", () => {
  const store = {
    data: {},
    getItem(key) {
      return this.data[key] ?? null;
    },
    setItem(key, value) {
      this.data[key] = value;
    },
  };
  assert.equal(logic.readPreviewMode(store), "hover");
  assert.equal(logic.writePreviewMode(store, "always"), "always");
  assert.equal(store.data[logic.PREVIEW_KEY], "always");
  assert.equal(logic.readPreviewMode(store), "always");
  assert.equal(logic.normalizePreviewMode("nope"), "hover");
  assert.equal(logic.previewChars("always"), logic.ALWAYS_CHARS);
  assert.equal(logic.previewChars("hover"), logic.HOVER_CHARS);
});

test("always-mode labels hide on a dense zoomed-out map", () => {
  assert.equal(logic.shouldShowAlwaysLabels("always", 1), true);
  assert.equal(logic.shouldShowAlwaysLabels("always", 0.4), false);
  assert.equal(logic.shouldShowAlwaysLabels("hover", 1), false);
});

test("contradiction_pairs become CONTRADICTS edges", () => {
  assert.deepEqual(
    logic.contradictionEdges([
      { from_id: "a", to_id: "b" },
      { from_id: "", to_id: "c" },
      { fromId: "d", toId: "e", relation_type: "CONTRADICTS" },
    ]),
    [
      { from_id: "a", to_id: "b", relation_type: "CONTRADICTS" },
      { from_id: "d", to_id: "e", relation_type: "CONTRADICTS" },
    ],
  );
});

test("auth mode strips owner_id from tool arguments", () => {
  assert.deepEqual(logic.toolArguments(true, { owner_id: "demo", query: "q" }), {
    query: "q",
  });
  assert.deepEqual(logic.toolArguments(false, { owner_id: "demo", query: "q" }), {
    owner_id: "demo",
    query: "q",
  });
});

test("any status includes outdated; active does not", () => {
  assert.deepEqual(logic.searchFilterArgs(""), { include_outdated: true });
  assert.deepEqual(logic.searchFilterArgs("active"), { status: "active" });
  assert.deepEqual(logic.searchFilterArgs("outdated"), {
    status: "outdated",
    include_outdated: true,
  });
});

test("search result meta and provenance include status, validity, timestamps", () => {
  const node = {
    node_type: "Fact",
    status: "outdated",
    similarity: 0.8123,
    created_at: 1700000000000,
    updated_at: 1700001000000,
    created_by: "alice",
    type: "Project",
    ttl_days: 7,
    metadata: {
      valid_from: "2026-08-01",
      valid_until: "2026-10-01",
      project: "release",
      tags: ["beta"],
    },
    source: { ref: "seed" },
  };
  assert.equal(
    logic.resultMeta(node),
    "Fact · outdated · similarity 0.812 · from 2026-08-01 · until 2026-10-01",
  );
  const labels = Object.fromEntries(logic.provenanceRows(node));
  assert.equal(labels.Source, "seed");
  assert.equal(labels.Created, 1700000000000);
  assert.equal(labels.Updated, 1700001000000);
  assert.equal(labels.Author, "alice");
  assert.equal(labels["Valid from"], "2026-08-01");
  assert.equal(labels["Valid until"], "2026-10-01");
  assert.equal(labels["TTL days"], 7);
  assert.equal(labels["Entity type"], "Project");
});
