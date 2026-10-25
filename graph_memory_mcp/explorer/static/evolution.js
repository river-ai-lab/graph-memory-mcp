/* Timestamp activity and real GraphDiff comparisons of explicit observations. */
const evolutionState = { captures: [], current: null, busy: false };

async function evolutionRequest(action, body) {
  const generation = state.generation;
  const res = await fetch(`/api/evolution/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ owner_id: state.ownerId, ...body }),
    signal: AbortSignal.timeout(120000),
  });
  const result = await res.json();
  if (generation !== state.generation) throw new Error("Map changed; capture again.");
  if (!res.ok || result.success === false) throw new Error(result.error || `HTTP ${res.status}`);
  return result;
}

async function evolutionAction(task) {
  if (evolutionState.busy) return;
  evolutionState.busy = true;
  updateEvolutionControls();
  $("evolution-status").textContent = "Working…";
  $("evolution-status").classList.remove("error-message");
  try { await task(); }
  catch (error) { $("evolution-status").textContent = error.message; $("evolution-status").classList.add("error-message"); }
  finally {
    evolutionState.busy = false;
    updateEvolutionControls();
  }
}

function captureLabel(capture) {
  const time = formatTime(capture.timestamp, true);
  return `${time} · ${capture.nodes.length} nodes · ${capture.coverage}`;
}

function renderCaptureSelectors() {
  const available = evolutionState.captures.filter(c => c.owner_id === state.ownerId);
  for (const id of ["capture-before", "capture-after"]) {
    const selected = $(id).value;
    $(id).replaceChildren();
    if (!available.length) {
      const placeholder = document.createElement("option");
      placeholder.value = ""; placeholder.textContent = "Capture or import first";
      $(id).appendChild(placeholder);
    }
    for (const capture of available) {
      const option = document.createElement("option");
      option.value = capture.timestamp;
      option.textContent = captureLabel(capture);
      $(id).appendChild(option);
    }
    if (available.some(c => c.timestamp === selected)) $(id).value = selected;
  }
  if (available.length > 0) $("capture-after").value = available.at(-1).timestamp;
  updateEvolutionControls();
}

function updateEvolutionControls() {
  const available = evolutionState.captures.filter(c => c.owner_id === state.ownerId);
  const before = available.find(c => c.timestamp === $("capture-before").value);
  const after = available.find(c => c.timestamp === $("capture-after").value);
  const validPair = before && after && new Date(before.timestamp) < new Date(after.timestamp)
    && before.scope === after.scope && before.coverage === after.coverage;
  const hasCurrent = evolutionState.current?.owner_id === state.ownerId;
  $("btn-capture-map").disabled = evolutionState.busy || !state.nodes.size;
  $("btn-period").disabled = evolutionState.busy || !hasCurrent;
  $("btn-compare-captures").disabled = evolutionState.busy || !validPair;
  $("btn-export-capture").disabled = evolutionState.busy || !hasCurrent;
  for (const id of ["capture-before", "capture-after", "evolution-period", "import-captures", "period-start", "period-end"]) $(id).disabled = evolutionState.busy;
  for (const id of ["btn-capture-map", "btn-period", "btn-compare-captures"]) $(id).setAttribute("aria-busy", String(evolutionState.busy));
  $("evolution-compare-hint").textContent = available.length < 2
    ? "Capture or import two observations to compare them."
    : validPair ? "Matching owner and view. Reads are excluded from the diff." : "Choose an earlier Before snapshot of the same view and coverage.";
}

function addCapture(capture) {
  if (evolutionState.captures.some(c => c.owner_id === capture.owner_id && c.timestamp === capture.timestamp)) {
    throw new Error("A capture with this owner and timestamp is already loaded.");
  }
  evolutionState.captures.push(capture);
  evolutionState.current = capture;
  renderCaptureSelectors();
  updateEvolutionControls();
  $("evolution-scope").textContent = `${capture.owner_id} · ${capture.coverage === "partial" ? "Partial map" : "Full capture"} · ${capture.nodes.length} nodes · ${capture.edges.length} edges · ${formatTime(capture.timestamp)}`;
}

function mapSignature() {
  return JSON.stringify([...state.nodes.keys()].sort()) + JSON.stringify([...state.edges.keys()].sort());
}

async function captureCurrentMap() {
  const signature = mapSignature();
  if (!state.nodes.size) throw new Error("Load a model, brief or search results before capturing.");
  const result = await evolutionRequest("capture", {
    node_ids: [...state.nodes.keys()], edges: [...state.edges.values()],
  });
  if (signature !== mapSignature()) throw new Error("Map changed during capture; try again.");
  addCapture(result.capture);
  $("evolution-status").textContent = "Snapshot captured from the loaded map. Dates and full node contents were read from MCP.";
  await showPeriod();
}

function statsHtml(items) {
  return items.map(([number, label]) => `<div class="evolution-stat"><strong>${Number(number)}</strong>${escapeHtml(label)}</div>`).join("");
}

function activityList(title, nodes, dateField) {
  if (!nodes.length) return "";
  return `<h3>${escapeHtml(title)}</h3><ul class="ov-list">${nodes.map(n => `<li tabindex="0" role="button" data-node-id="${escapeHtml(n.node_id)}">${escapeHtml(preview(n.text, 200))}<span class="result-meta">${escapeHtml(n.node_type)} · ${escapeHtml(formatTime(n[dateField]))}</span></li>`).join("")}</ul>`;
}

async function showPeriod() {
  const capture = evolutionState.current;
  if (!capture || capture.owner_id !== state.ownerId) throw new Error("Capture or import a map for this owner first.");
  const period = $("evolution-period").value;
  const end = period === "custom" ? new Date($("period-end").value) : new Date(capture.timestamp);
  const start = period === "custom" ? new Date($("period-start").value) : new Date(end.getTime() - Number(period) * 86400000);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) throw new Error("Select both custom dates.");
  const result = await evolutionRequest("activity", { capture, start: start.toISOString(), end: end.toISOString() });
  $("evolution-summary").innerHTML = statsHtml([
    [result.created_nodes.length, "Nodes created in this map"],
    [result.updated_nodes.length, "Nodes with later updates"],
    [result.created_edges.length, "Relations created in this map"],
  ]);
  $("evolution-results").innerHTML = activityList("Created in this period", result.created_nodes, "created_at") + activityList("Updated timestamp in this period", result.updated_nodes, "updated_at");
  if (!result.created_nodes.length && !result.updated_nodes.length) $("evolution-results").textContent = "No dated node activity in this capture for the selected period.";
  $("evolution-status").textContent = `${formatTime(start)} → ${formatTime(end)}. Unknown dates: ${result.unknown_node_dates} nodes, ${result.unknown_edge_dates} relations. ${result.omitted_edges ? `${result.omitted_edges} edges omitted outside the captured map.` : ""}`;
}

async function compareCaptures() {
  const available = evolutionState.captures.filter(c => c.owner_id === state.ownerId);
  const before = available.find(c => c.timestamp === $("capture-before").value);
  const after = available.find(c => c.timestamp === $("capture-after").value);
  if (!before || !after || before.timestamp === after.timestamp) throw new Error("Capture or import two different snapshots, then select before and after.");
  const result = await evolutionRequest("compare", { before, after });
  const n = result.summary.nodes, e = result.summary.edges;
  const partial = result.coverage === "partial";
  $("evolution-summary").innerHTML = statsHtml([
    [n.added, partial ? "Nodes entered view" : "Nodes added"],
    [n.removed, partial ? "Nodes left view" : "Nodes removed"],
    [n.modified, "Nodes changed"],
    [e.added, partial ? "Edges entered view" : "Edges added"],
    [e.removed, partial ? "Edges left view" : "Edges removed"],
    [e.modified, "Edges changed"],
  ]);
  $("evolution-results").replaceChildren();
  for (const change of result.changes) {
    $("evolution-results").appendChild(changeCard(change, before, after));
  }
  if (!result.changes.length) $("evolution-results").textContent = "No content or structure changes between these observations. Read counters are ignored.";
  $("evolution-status").textContent = `${before.owner_id} · ${partial ? "Changes in the captured view" : "Changes in complete captures"}. ${result.limitations.join(" ")}`;
}

function changeCard(change, before, after) {
  const nodes = new Map([...before.nodes, ...after.nodes].map(n => [n.id, n]));
  const labels = { NodeAdded: before.coverage === "partial" ? "Node entered view" : "Node added", NodeRemoved: before.coverage === "partial" ? "Node left view" : "Node removed", NodePropertiesChanged: "Node updated", NodeLabelChanged: "Node type changed", EdgeAdded: before.coverage === "partial" ? "Connection entered view" : "Connection added", EdgeRemoved: before.coverage === "partial" ? "Connection left view" : "Connection removed", EdgePropertiesChanged: "Connection updated" };
  const nodeName = id => preview(nodes.get(id)?.properties?.text || id, 120);
  const edge = change.edge;
  const title = edge ? `${nodeName(edge.source)} → ${nodeName(edge.target)}` : change.node?.properties?.text || nodeName(change.node_id);
  const card = document.createElement("article"); card.className = "diff-card";
  const changes = change.property_changes || (change.type === "NodeLabelChanged" ? [{ name: "Node type", old: change.old_label, new: change.new_label }] : []);
  const value = (v, present) => present === false ? "Not present" : v === null ? "null" : v === undefined ? "Not available" : typeof v === "object" ? JSON.stringify(v) : String(v);
  card.innerHTML = `<span class="diff-kind">${escapeHtml(labels[change.type] || change.type)}</span><h4>${escapeHtml(preview(title, 200))}</h4>${edge ? `<p class="muted">${escapeHtml(edge.type)}</p>` : ""}${changes.length ? `<dl>${changes.map(c => `<dt>${escapeHtml(c.name.replaceAll("_", " "))}</dt><dd><del>${escapeHtml(value(c.old, c.old_present))}</del><ins>${escapeHtml(value(c.new, c.new_present))}</ins></dd>`).join("")}</dl>` : ""}<details><summary>Raw change</summary><pre class="diff-change"></pre></details>`;
  card.querySelector("pre").textContent = JSON.stringify(change, null, 2);
  return card;
}

$("btn-evolution").addEventListener("click", () => {
  syncOwner();
  if (evolutionState.current?.owner_id !== state.ownerId) evolutionState.current = null;
  renderCaptureSelectors();
  $("evolution-scope").textContent = evolutionState.current
    ? `${state.ownerId} · ${evolutionState.current.coverage} · ${evolutionState.current.nodes.length} nodes`
    : `${state.ownerId} · Loaded map: ${state.nodes.size} nodes. Capture it to inspect dates.`;
  $("evolution-summary").replaceChildren();
  $("evolution-results").replaceChildren();
  $("evolution-status").classList.remove("error-message");
  $("evolution-status").textContent = evolutionState.current ? "Choose a period or compare saved observations." : "Capture the loaded map or import a saved snapshot to begin.";
  $("btn-export-capture").disabled = !evolutionState.current;
  updateEvolutionControls();
  $("evolution-dialog").showModal();
});
for (const id of ["capture-before", "capture-after"]) $(id).addEventListener("change", updateEvolutionControls);
$("btn-close-evolution").addEventListener("click", () => $("evolution-dialog").close());
$("btn-capture-map").addEventListener("click", () => evolutionAction(captureCurrentMap));
$("btn-period").addEventListener("click", () => evolutionAction(showPeriod));
$("btn-compare-captures").addEventListener("click", () => evolutionAction(compareCaptures));
$("evolution-period").addEventListener("change", () => { $("custom-period").hidden = $("evolution-period").value !== "custom"; });
$("btn-export-capture").addEventListener("click", () => {
  const capture = evolutionState.current;
  if (!capture) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(capture, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url; link.download = `graph-memory-${capture.owner_id}-${capture.timestamp.replace(/[:.]/g, "-")}.json`;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$("import-captures").addEventListener("change", () => evolutionAction(async () => {
  for (const file of $("import-captures").files) {
    if (file.size > 4_000_000) throw new Error("Import snapshots smaller than 4 MB.");
    const capture = JSON.parse(await file.text());
    if (capture.owner_id !== state.ownerId) throw new Error("Snapshot owner does not match this workspace.");
    // Validate with the same adapter used for analysis before accepting the file.
    const end = new Date(capture.timestamp);
    await evolutionRequest("activity", { capture, start: new Date(end.getTime() - 86400000).toISOString(), end: end.toISOString() });
    addCapture(capture);
  }
  $("import-captures").value = "";
  $("evolution-status").textContent = "Snapshots imported. Select their periods or compare observations.";
}));
$("evolution-results").addEventListener("click", event => {
  const id = event.target.closest("[data-node-id]")?.dataset.nodeId;
  if (!id) return;
  $("evolution-dialog").close();
  loadAnchor(id).catch(error => notice(error.message, true));
});
$("evolution-results").addEventListener("keydown", event => {
  if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-node-id]")) { event.preventDefault(); event.target.click(); }
});

async function modelLens(kind) {
  if (state.ownerId !== "luminaria") return;
  clearGraph();
  for (const [id, key] of [["btn-wheat", "wheat"], ["btn-corn", "corn"], ["btn-both", "both"]]) $(id).setAttribute("aria-pressed", String(key === kind));
  const ids = kind === "wheat" ? ["f337518108a7400a87c1485fb36533be"] : kind === "corn" ? ["b58b3151e1c54092a9ac68bbdbf0734d"] : ["f337518108a7400a87c1485fb36533be", "b58b3151e1c54092a9ac68bbdbf0734d"];
  for (const id of ids) {
    const data = await callTool("get_context", contextArgs(id, { depth: 1, max_nodes: 12, exclude_relation_types: ["MENTIONS"] }));
    mergeToolResult(data, { fresh: true }, { fullLayout: true });
  }
  // Read the shared body bridge to show how corn reuses the wheat encoder.
  if (kind === "both") {
    const bridge = await callTool("get_context", contextArgs("33e8108ae2ae41c98f262236d2c04550", { depth: 1, max_nodes: 12, exclude_relation_types: ["MENTIONS"] }));
    mergeToolResult(bridge, { fresh: true }, { fullLayout: true });
  }
  state.anchorId = ids[0]; $("node-id").value = ids[0];
  state.selectedId = ids[0]; await loadNodeDetail(ids[0]);
}
for (const [id, kind] of [["btn-wheat", "wheat"], ["btn-corn", "corn"], ["btn-both", "both"]]) {
  $(id).addEventListener("click", () => modelLens(kind).catch(error => notice(error.message, true)));
}
$("btn-history").addEventListener("click", async () => {
  const id = state.selectedId;
  if (!id) return;
  try {
    const result = await callTool("get_node_change_history", ownerArgs({ node_id: id }));
    if (state.selectedId !== id) return;
    $("detail-history").hidden = false;
    $("detail-history").textContent = result.versions?.length
      ? JSON.stringify(result.versions, null, 2)
      : "No saved versions. Creation time alone cannot restore an earlier text or status.";
  } catch (error) { notice(error.message, true); }
});
