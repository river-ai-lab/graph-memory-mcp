import { $, log } from "./dom.js";
import { state } from "./state.js";
import { callTool, ownerArgs, preview } from "./api.js";
import { persistField } from "./persist.js";
import {
  cy,
  mergeNodes,
  mergeEdges,
  mergeToolResult,
  syncGraph,
  centerViewOnNode,
  updateStats,
  updateSelAction,
} from "./graph.js";
import { updateNeighborUi } from "./neighbors.js";

export function showDetail(nodeId, nodeOverride) {
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

export async function loadHistory() {
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

export async function focusNode(nodeId, { loadDetail = true } = {}) {
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

export async function loadNodeDetail(nodeId) {
  const data = await callTool("get_node", ownerArgs({ node_id: nodeId }));
  mergeToolResult(data, {}, { originNodeId: nodeId });
  showDetail(nodeId, data.node);
}

export function renderOverview(data) {
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

export async function loadBrief() {
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
