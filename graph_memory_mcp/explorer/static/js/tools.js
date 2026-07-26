import { $ } from "./dom.js";
import { log } from "./dom.js";
import { state } from "./state.js";
import {
  callTool,
  ownerArgs,
  scopeIncludeOutdated,
  scopeMetadataFilter,
  searchFilters,
} from "./api.js";
import { validateTool, persistField } from "./persist.js";
import {
  clearGraph,
  clearPathHighlight,
  mergeNodes,
  mergeEdges,
  mergeToolResult,
  mergeTriplets,
  markSeeds,
  syncGraph,
  centerViewOnNode,
  setBusy,
} from "./graph.js";

export function showToolResult(tool, args, data) {
  state.lastToolResponse = { tool, args, data };
  const parts = [tool];
  if (data.nodes) parts.push(`${data.nodes.length} nodes`);
  if (data.edges) parts.push(`${data.edges.length} edges`);
  if (data.seeds) parts.push(`${data.seeds.length} seeds`);
  if (data.paths) parts.push(`${data.paths.length} paths`);
  if (data.results) parts.push(`${data.results.length} results`);
  if (data.triplets) parts.push(`${data.triplets.length} triplets`);
  if (data.similar_facts) parts.push(`${data.similar_facts.length} similar`);
  if (data.stats) {
    const s = data.stats;
    const bits = [];
    if (s.total_facts != null) bits.push(`${s.total_facts} facts`);
    if (s.total_entities != null) bits.push(`${s.total_entities} entities`);
    if (s.total_relations != null) bits.push(`${s.total_relations} rels`);
    if (bits.length) parts.push(bits.join(", "));
  }
  if (data.message) parts.push(data.message);
  if (data.has_more != null) parts.push(data.has_more ? "has_more" : "end");
  $("tool-summary").textContent = parts.join(" · ");
  $("tool-summary").classList.remove("muted");
  $("tool-raw").textContent = JSON.stringify(
    { tool, arguments: args, response: data },
    null,
    2,
  );
}

export function buildToolCall(tool) {
  switch (tool) {
    case "recall_context": {
      const args = ownerArgs({
        query: $("recall-query").value.trim(),
        limit: Number($("recall-limit").value) || 8,
        depth: Number($("recall-depth").value) || 0,
        max_nodes: Number($("recall-max-nodes").value) || 30,
        include_paths: $("recall-paths").checked,
        include_outdated: scopeIncludeOutdated(),
      });
      const thr = $("recall-threshold").value;
      if (thr !== "") args.similarity_threshold = Number(thr);
      const mf = scopeMetadataFilter();
      if (mf) args.metadata_filter = mf;
      return args;
    }
    case "get_trace":
      return ownerArgs({
        from_id: $("trace-from").value.trim(),
        to_id: $("trace-to").value.trim(),
        max_depth: Number($("trace-depth").value) || 5,
        directed: !$("trace-undirected").checked,
      });
    case "get_context":
      return ownerArgs({
        node_id: $("ctx-node-id").value.trim(),
        depth: Number($("ctx-depth").value) || 0,
        max_nodes: Number($("ctx-max-nodes").value) || 20,
        offset: Number($("ctx-offset").value) || 0,
        include_outdated: scopeIncludeOutdated(),
      });
    case "search":
      return ownerArgs({
        query: $("search-query").value.trim(),
        limit: Number($("search-limit").value) || 10,
        ...searchFilters(),
      });
    case "find_similar": {
      const fact_id =
        $("similar-fact-id").value.trim() ||
        state.selectedId ||
        state.anchorId ||
        "";
      return ownerArgs({
        fact_id,
        limit: Number($("similar-limit").value) || 5,
        similarity_threshold: Number($("similar-threshold").value) || 0.55,
      });
    }
    case "search_triplets": {
      const args = ownerArgs({
        limit: Number($("trip-limit").value) || 10,
      });
      const subject = $("trip-subject").value.trim();
      const predicate = $("trip-predicate").value.trim();
      const object_value = $("trip-object").value.trim();
      if (subject) args.subject = subject;
      if (predicate) args.predicate = predicate;
      if (object_value) args.object_value = object_value;
      return args;
    }
    case "get_stats":
      return ownerArgs({});
    default:
      throw new Error(`unknown tool: ${tool}`);
  }
}

export async function runSelectedTool() {
  const tool = $("llm-tool").value;
  if (!validateTool(tool)) {
    $("tool-summary").textContent = "Fix highlighted fields, then Run again.";
    $("tool-summary").classList.add("muted");
    return null;
  }

  // Abort / ignore previous in-flight Run
  if (state.toolAbort) state.toolAbort.abort();
  const abort = new AbortController();
  state.toolAbort = abort;
  const runId = ++state.toolRunId;
  const args = buildToolCall(tool);

  setBusy(true, `Calling ${tool}…`);
  try {
    if ($("tool-replace").checked && tool !== "get_stats") {
      clearGraph({ quiet: true });
    }
    if (tool !== "get_stats") clearPathHighlight();

    const data = await callTool(tool, args, { signal: abort.signal });
    if (runId !== state.toolRunId) {
      log(`ignored stale ${tool} response`);
      return null;
    }

    if (tool === "get_stats") {
      const s = data.stats || {};
      const bits = [];
      if (s.total_facts != null) bits.push(`${s.total_facts} facts`);
      if (s.total_entities != null) bits.push(`${s.total_entities} entities`);
      if (s.total_relations != null) bits.push(`${s.total_relations} rels`);
      if (s.active_facts != null) bits.push(`${s.active_facts} active`);
      if (bits.length) $("overview-stats").textContent = bits.join(" · ");
      showToolResult(tool, args, data);
      log(`ran ${tool}`);
      return data;
    }

    if (tool === "get_trace") {
      const nodes = data.nodes || [];
      if (!nodes.length) {
        showToolResult(tool, args, data);
        log(data.message || "no path");
        return data;
      }
      markSeeds([]);
      mergeNodes(nodes, { fresh: true });
      mergeEdges(edgesFromTrace(nodes, data.relations || []), { path: true });
      syncGraph({ fullLayout: true, originNodeId: args.from_id });
      centerViewOnNode(args.from_id);
    } else if (tool === "find_similar") {
      const anchor = args.fact_id;
      markSeeds([anchor]);
      const ids = new Set([
        anchor,
        ...(data.similar_facts || []).map((f) => f.node_id),
      ]);
      mergeNodes(data.similar_facts, { fresh: true });
      mergeNodes([{ node_id: anchor }], {});
      const ctx = await callTool(
        "get_context",
        ownerArgs({
          node_id: anchor,
          depth: 2,
          max_nodes: 50,
          include_outdated: scopeIncludeOutdated(),
        }),
        { signal: abort.signal },
      );
      if (runId !== state.toolRunId) {
        log("ignored stale find_similar follow-up");
        return null;
      }
      mergeEdges(
        (ctx.edges || []).filter((e) => ids.has(e.from_id) && ids.has(e.to_id)),
      );
      syncGraph({ originNodeId: anchor, fullLayout: true });
    } else if (tool === "search_triplets") {
      markSeeds([]);
      mergeTriplets(data.triplets || []);
      syncGraph({ fullLayout: true });
    } else if (tool === "recall_context") {
      markSeeds(data.seeds || []);
      mergeToolResult(data, { fresh: true }, { fullLayout: true });
      const seed = data.seeds?.[0]?.node_id;
      if (seed) {
        state.anchorId = seed;
        centerViewOnNode(seed);
      }
    } else {
      markSeeds(data.seeds || data.results || []);
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
  } catch (err) {
    if (err?.name === "AbortError") {
      log(`cancelled ${tool}`);
      return null;
    }
    throw err;
  } finally {
    if (runId === state.toolRunId) {
      setBusy(false);
      if (state.toolAbort === abort) state.toolAbort = null;
    }
  }
}
