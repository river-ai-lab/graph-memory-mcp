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
  assert.equal(logic.previewZoom("always", 0.2), logic.DENSE_ZOOM);
  assert.equal(logic.previewZoom("always", 0.8), 0.8);
  assert.equal(logic.previewZoom("hover", 0.2), 0.2);
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

test("brief stats name outdated facts and singular entity", () => {
  assert.equal(
    logic.briefStatLine({
      total_facts: 4,
      total_entities: 1,
      total_relations: 5,
      active_facts: 3,
      outdated_facts: 1,
      archived_facts: 0,
    }),
    "4 facts · 1 entity · 5 relations · 3 active · 1 outdated",
  );
  assert.equal(logic.mapStats(1, 1), "1 item · 1 link");
  assert.equal(logic.mapStats(2, 3), "2 items · 3 links");
  assert.equal(
    logic.validityLabel({ metadata: { valid_from: "2026-08-01", valid_until: "2026-10-01" } }),
    "Valid from 2026-08-01 until 2026-10-01",
  );
  assert.equal(
    logic.validityLabel({ metadata: { valid_from: "2026-10-01" } }),
    "Valid from 2026-10-01 until still open",
  );
  assert.equal(logic.validityLabel({ metadata: {} }), "");
  assert.equal(logic.linkPhrase(false, "FOLLOWS_FROM"), "Links to · FOLLOWS_FROM");
  assert.equal(logic.linkPhrase(true, "CONTRADICTS"), "Linked from · CONTRADICTS");
});

test("detail line and history show validity and timestamps", () => {
  const node = {
    created_at: Date.UTC(2026, 9, 25, 21, 7, 0),
    updated_at: Date.UTC(2026, 9, 25, 21, 8, 0),
    metadata: { valid_from: "2026-08-01", valid_until: "2026-10-01" },
  };
  const line = logic.detailWhen(node);
  assert.match(line, /Valid 2026-08-01 → 2026-10-01/);
  assert.match(line, /Created /);
  assert.match(line, /Updated /);
  assert.match(line, /2026/);
  const history = logic.formatHistory([
    {
      version_timestamp: Date.UTC(2026, 9, 1, 12, 0, 0),
      status: "active",
      text: "Beta ships October 1.",
      metadata: { valid_from: "2026-08-01" },
    },
  ]);
  assert.match(history, /active/);
  assert.match(history, /from 2026-08-01/);
  assert.match(history, /Beta ships October 1\./);
  assert.equal(logic.formatHistory([]), "");
});

test("contradictions collapse to one edge and a path does not invent the reverse", () => {
  let store = { edges: {}, pathKeys: [] };
  store = logic.placeEdge(store, {
    from_id: "b",
    to_id: "a",
    relation_type: "CONTRADICTS",
  });
  store = logic.placeEdge(store, {
    from_id: "a",
    to_id: "b",
    relation_type: "CONTRADICTS",
  });
  assert.deepEqual(Object.keys(store.edges), ["a|CONTRADICTS|b"]);
  store = logic.placeEdge(store, {
    from_id: "a",
    to_id: "c",
    relation_type: "RELATED_TO",
  });
  store = logic.placeEdge(
    store,
    { from_id: "c", to_id: "a", relation_type: "RELATED_TO" },
    { path: true },
  );
  assert.deepEqual(Object.keys(store.edges), ["a|CONTRADICTS|b", "a|RELATED_TO|c"]);
  assert.deepEqual(store.pathKeys, ["a|RELATED_TO|c"]);
  store = logic.placeEdge(
    store,
    { from_id: "c", to_id: "d", relation_type: "FOLLOWS_FROM" },
    { path: true },
  );
  assert.ok(store.edges["c|FOLLOWS_FROM|d"]);
  assert.ok(store.pathKeys.includes("c|FOLLOWS_FROM|d"));
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

test("edgesFromTrace links consecutive path nodes", () => {
  assert.deepEqual(
    logic.edgesFromTrace(
      [{ node_id: "a" }, { node_id: "b" }, {}],
      [{ relation_type: "FOLLOWS_FROM" }, { relation_type: "" }],
    ),
    [{ from_id: "a", to_id: "b", relation_type: "FOLLOWS_FROM" }],
  );
  assert.deepEqual(logic.edgesFromTrace(null, null), []);
});
