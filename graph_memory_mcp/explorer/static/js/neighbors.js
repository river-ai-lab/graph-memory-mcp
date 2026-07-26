import { $, log } from "./dom.js";
import { state } from "./state.js";
import { callTool, ownerArgs, preview, scopeIncludeOutdated } from "./api.js";
import { mergeNodes, mergeEdges, syncGraph, updateSelAction } from "./graph.js";

/** Neighbor paging: one BFS fetch into a buffer, then reveal pageSize slices.
 *  Avoids mixing offset=0 BFS with offset>0 SKIP/LIMIT (different API paths).
 */
export function emptyNeighborInfo(pageSize) {
  const ps = pageSize || 10;
  return {
    pageSize: ps,
    fetchCap: Math.min(100, Math.max(ps * 5, ps)),
    bufferIds: [],
    nodeById: new Map(),
    edges: [],
    revealed: 0,
    capped: false,
    loaded: false,
    batchIds: [],
  };
}

export function neighborInfo(nodeId) {
  return (
    state.neighborState.get(nodeId) ||
    emptyNeighborInfo(Number($("neighbor-page-size")?.value) || 10)
  );
}

export function neighborCanLoadMore(info) {
  return info.loaded && info.revealed < info.bufferIds.length;
}

export function updateNeighborUi(nodeId) {
  if (!nodeId || state.selectedId !== nodeId) return;
  const info = neighborInfo(nodeId);
  const status = $("neighbor-status");
  const moreBtn = $("btn-neighbors-more");
  const loadBtn = $("btn-neighbors");
  const selMore = $("btn-sel-more");
  const selStatus = $("sel-action-status");

  if (!info.loaded) {
    status.textContent = "Not loaded yet — fetch 1-hop neighbors into a buffer.";
    loadBtn.textContent = "Load neighbors";
    moreBtn.hidden = true;
    selMore.hidden = true;
    selStatus.textContent = "";
  } else {
    const total = info.bufferIds.length;
    const shown = info.revealed;
    const hasMore = shown < total;
    let moreText;
    if (hasMore) {
      moreText = `buffer ${shown}/${total} · next page local`;
    } else if (info.capped) {
      moreText = `buffer complete ${total} (fetch cap ${info.fetchCap} — graph may have more)`;
    } else {
      moreText = `all ${total} neighbors in buffer`;
    }
    status.textContent = moreText;
    loadBtn.textContent = "Reload from start";
    moreBtn.hidden = !hasMore;
    selMore.hidden = !hasMore;
    selStatus.textContent = hasMore
      ? `${shown}/${total}`
      : info.capped
        ? `${total} · capped`
        : `${total} · done`;
  }

  const list = $("neighbor-list");
  const ids = info.batchIds || [];
  list.innerHTML = ids.length
    ? ids
        .map((id) => {
          const n = state.nodes.get(id) || info.nodeById?.get(id);
          const seed = state.seedIds.has(id) ? " · seed" : "";
          return `<li data-id="${id}" title="${id}">${preview(n?.text || id, 42)}${seed}</li>`;
        })
        .join("")
    : "<li class='muted'>none in last page</li>";

  updateSelAction();
}

export function revealNeighborPage(nodeId) {
  const info = state.neighborState.get(nodeId);
  if (!info?.loaded) return;
  const start = info.revealed;
  const end = Math.min(start + info.pageSize, info.bufferIds.length);
  const batchIds = info.bufferIds.slice(start, end);
  const batchNodes = batchIds.map((id) => info.nodeById.get(id)).filter(Boolean);

  mergeNodes(batchNodes, { fresh: true });
  const visible = new Set([nodeId, ...info.bufferIds.slice(0, end)]);
  mergeEdges(
    (info.edges || []).filter(
      (e) => visible.has(e.from_id) && visible.has(e.to_id),
    ),
  );
  info.revealed = end;
  info.batchIds = batchIds;
  state.neighborState.set(nodeId, info);
  syncGraph({ originNodeId: nodeId });
  updateNeighborUi(nodeId);
  log(
    `neighbors ${nodeId}: revealed ${end}/${info.bufferIds.length}` +
      (info.capped ? ` · cap ${info.fetchCap}` : ""),
  );
}

export async function loadNeighbors(nodeId, { reset = false, pageSize } = {}) {
  const size = pageSize || Number($("neighbor-page-size").value) || 10;
  let info = state.neighborState.get(nodeId);

  if (!reset && info?.loaded) {
    info.pageSize = size;
    state.neighborState.set(nodeId, info);
    if (!neighborCanLoadMore(info)) {
      updateNeighborUi(nodeId);
      log(
        `neighbors ${nodeId}: buffer exhausted` +
          (info.capped ? ` (fetch cap ${info.fetchCap})` : ""),
      );
      return null;
    }
    revealNeighborPage(nodeId);
    return info;
  }

  info = emptyNeighborInfo(size);
  const args = ownerArgs({
    node_id: nodeId,
    depth: 1,
    max_nodes: info.fetchCap,
    include_outdated: scopeIncludeOutdated(),
  });
  const data = await callTool("get_context", args);

  const center =
    (data.nodes || []).find((n) => n.node_id === nodeId) || { node_id: nodeId };
  mergeNodes([center], { fresh: true });

  const neighbors = (data.nodes || []).filter(
    (n) => n.node_id && n.node_id !== nodeId,
  );
  info.bufferIds = neighbors.map((n) => n.node_id);
  info.nodeById = new Map(neighbors.map((n) => [n.node_id, n]));
  info.edges = data.edges || [];
  info.capped = (data.nodes || []).length >= info.fetchCap;
  info.revealed = 0;
  info.loaded = true;
  info.pageSize = size;
  info.batchIds = [];
  state.neighborState.set(nodeId, info);

  if (!info.bufferIds.length) {
    syncGraph({ originNodeId: nodeId });
    updateNeighborUi(nodeId);
    log(`neighbors ${nodeId}: none`);
    return data;
  }

  revealNeighborPage(nodeId);
  log(
    `neighbors ${nodeId}: buffered ${info.bufferIds.length}` +
      (info.capped ? ` · capped at ${info.fetchCap}` : ""),
  );
  return data;
}
