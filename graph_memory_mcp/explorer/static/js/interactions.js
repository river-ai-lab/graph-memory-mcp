import { $, log } from "./dom.js";
import { state } from "./state.js";
import {
  cy,
  runLayout,
  rotateGraph,
  rotateGraphAround,
  graphCenterModel,
  renderedToModel,
  angleFromCenter,
  updateSelAction,
} from "./graph.js";
import { showDetail, loadNodeDetail } from "./detail.js";
import { loadNeighbors } from "./neighbors.js";

export function bindGraphInteractions() {
  const hoverPlus = $("hover-plus");
  let hidePlusTimer = null;

  function positionHoverPlus(node) {
    const bb = node.renderedBoundingBox({
      includeLabels: false,
      includeOverlays: false,
    });
    hoverPlus.style.left = `${bb.x2}px`;
    hoverPlus.style.top = `${bb.y1}px`;
  }

  function refreshHoverPlusPosition() {
    if (!state.hoverId || !hoverPlus.classList.contains("visible")) return;
    const node = cy.getElementById(state.hoverId);
    if (node.nonempty()) positionHoverPlus(node);
  }

  function showHoverPlus(node) {
    clearTimeout(hidePlusTimer);
    state.hoverId = node.id();
    positionHoverPlus(node);
    hoverPlus.classList.add("visible");
  }

  function scheduleHideHoverPlus() {
    clearTimeout(hidePlusTimer);
    hidePlusTimer = setTimeout(() => {
      hoverPlus.classList.remove("visible");
      state.hoverId = null;
    }, 250);
  }

  cy.on("tap", "node", (evt) => {
    const id = evt.target.id();
    cy.$(":selected").unselect();
    evt.target.select();
    showDetail(id);
    updateSelAction();
    loadNodeDetail(id).catch((e) => log(`detail error: ${e.message}`));
  });

  cy.on("tap", (evt) => {
    if (evt.target === cy) {
      $("sel-action").hidden = true;
    }
  });

  cy.on("dbltap", "node", (evt) => {
    const id = evt.target.id();
    loadNeighbors(id, { reset: !state.neighborState.has(id) }).catch((err) =>
      log(`expand: ${err.message}`),
    );
  });

  cy.on("mouseover", "node", (evt) => {
    showHoverPlus(evt.target);
  });

  cy.on("mouseout", "node", () => {
    scheduleHideHoverPlus();
  });

  cy.on("pan zoom", () => {
    refreshHoverPlusPosition();
    updateSelAction();
  });

  cy.on("drag", "node", (evt) => {
    if (state.hoverId === evt.target.id()) positionHoverPlus(evt.target);
    if (state.selectedId === evt.target.id()) updateSelAction();
  });

  cy.on("position", "node", (evt) => {
    if (state.hoverId === evt.target.id()) positionHoverPlus(evt.target);
    if (state.selectedId === evt.target.id()) updateSelAction();
  });

  hoverPlus.addEventListener("mouseenter", () => {
    clearTimeout(hidePlusTimer);
  });

  hoverPlus.addEventListener("mouseleave", () => {
    scheduleHideHoverPlus();
  });

  hoverPlus.addEventListener("click", (e) => {
    e.stopPropagation();
    const id = state.hoverId;
    if (!id) return;
    const reset = !state.neighborState.has(id);
    loadNeighbors(id, { reset }).catch((err) => log(`neighbors: ${err.message}`));
  });

  function isTypingTarget(el) {
    if (!el || el === document.body) return false;
    const tag = el.tagName;
    return (
      tag === "INPUT" ||
      tag === "TEXTAREA" ||
      tag === "SELECT" ||
      el.isContentEditable
    );
  }

  window.addEventListener("keydown", (e) => {
    if (isTypingTarget(e.target)) return;
    if (e.code === "Space") {
      e.preventDefault();
      state.spacePan = true;
      cy.userPanningEnabled(true);
      cy.boxSelectionEnabled(false);
      cy.container().classList.add("space-pan");
    }
    if (e.key === "f" && !e.metaKey && !e.ctrlKey) {
      cy.fit(undefined, 40);
    }
    if (e.key === "r" && !e.metaKey && !e.ctrlKey) {
      runLayout(state.layoutName);
    }
    if (e.key === "[" && !e.metaKey && !e.ctrlKey) {
      rotateGraph(-15);
    }
    if (e.key === "]" && !e.metaKey && !e.ctrlKey) {
      rotateGraph(15);
    }
  });

  window.addEventListener("keyup", (e) => {
    if (e.code === "Space") {
      state.spacePan = false;
      cy.boxSelectionEnabled(true);
      cy.container().classList.remove("space-pan");
    }
  });

  cy.on("mousedown", (evt) => {
    if (!evt.originalEvent?.altKey) return;
    if (evt.target !== cy) return;
    const c = graphCenterModel();
    const mpos = renderedToModel(evt.renderedPosition.x, evt.renderedPosition.y);
    state.rotateDrag = {
      active: true,
      cx: c.x,
      cy: c.y,
      lastAngle: angleFromCenter(mpos.x, mpos.y, c.x, c.y),
    };
    cy.userPanningEnabled(false);
    cy.userZoomingEnabled(false);
    cy.container().classList.add("rotating");
  });

  cy.on("mousemove", (evt) => {
    const rd = state.rotateDrag;
    if (!rd?.active) return;
    const mpos = renderedToModel(evt.renderedPosition.x, evt.renderedPosition.y);
    const ang = angleFromCenter(mpos.x, mpos.y, rd.cx, rd.cy);
    let delta = ang - rd.lastAngle;
    if (delta > Math.PI) delta -= 2 * Math.PI;
    if (delta < -Math.PI) delta += 2 * Math.PI;
    rd.lastAngle = ang;
    rotateGraphAround((delta * 180) / Math.PI, rd.cx, rd.cy);
  });

  function endRotateDrag() {
    if (!state.rotateDrag?.active) return;
    state.rotateDrag = null;
    cy.userPanningEnabled(true);
    cy.userZoomingEnabled(true);
    cy.container().classList.remove("rotating");
    log("rotated (alt+drag)");
  }

  cy.on("mouseup", endRotateDrag);
  window.addEventListener("mouseup", endRotateDrag);
}
