/* Shared app state */
export const KNOWN_EDGE_TYPES = new Set([
  "RELATED_TO",
  "MENTIONS",
  "SUMMARIZES",
  "FOLLOWS_FROM",
  "CONTRADICTS",
  "EXTRACTED_FROM",
]);

export const state = {
  ownerId: localStorage.getItem("gm_owner_id") || "default",
  anchorId: null,
  nodes: new Map(),
  edges: new Map(),
  /** @type {Map<string, object>} neighbor buffer state per node */
  neighborState: new Map(),
  seedIds: new Set(),
  selectedId: null,
  hoverId: null,
  pathEdgeKeys: new Set(),
  nodesLocked: false,
  spacePan: false,
  layoutName: localStorage.getItem("gm_layout") || "cose",
  lastToolResponse: null,
  busy: false,
  toolRunId: 0,
  toolAbort: null,
  /** @type {{ active: boolean, cx: number, cy: number, lastAngle: number } | null} */
  rotateDrag: null,
};
