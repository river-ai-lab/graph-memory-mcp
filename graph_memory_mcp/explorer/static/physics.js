/* Optional live forces. Settles to idle; dragging or graph changes wake it up. */
const graphPhysics = {
  enabled: false, frame: null, bodies: [], links: [], center: null, quietFrames: 0, lastTime: 0,
};
function pausePhysics() {
  if (graphPhysics.frame !== null) cancelAnimationFrame(graphPhysics.frame);
  graphPhysics.frame = null;
}
function restartPhysics() {
  pausePhysics();
  if (!graphPhysics.enabled || document.hidden || cy.nodes().length < 2) return;
  const nodes = cy.nodes().toArray();
  const indices = new Map(nodes.map((node, index) => [node.id(), index]));
  graphPhysics.bodies = nodes.map(node => ({ node, ...node.position(), vx: 0, vy: 0, fixed: false }));
  const seen = new Set();
  graphPhysics.links = [];
  cy.edges().forEach(edge => {
    const a = indices.get(edge.source().id()), b = indices.get(edge.target().id());
    if (a === b) return;
    const key = `${Math.min(a, b)}|${Math.max(a, b)}`;
    if (!seen.has(key)) { seen.add(key); graphPhysics.links.push([a, b]); }
  });
  graphPhysics.center = {
    x: graphPhysics.bodies.reduce((sum, b) => sum + b.x, 0) / nodes.length,
    y: graphPhysics.bodies.reduce((sum, b) => sum + b.y, 0) / nodes.length,
  };
  graphPhysics.quietFrames = 0;
  graphPhysics.lastTime = 0;
  graphPhysics.frame = requestAnimationFrame(physicsFrame);
}
function physicsFrame(time) {
  graphPhysics.frame = null;
  if (!graphPhysics.enabled || document.hidden) return;
  if (time - graphPhysics.lastTime < 1000 / 30) {
    graphPhysics.frame = requestAnimationFrame(physicsFrame); return;
  }
  graphPhysics.lastTime = time;
  let grabbed = false;
  for (const body of graphPhysics.bodies) {
    if (body.node.removed()) { restartPhysics(); return; }
    Object.assign(body, body.node.position());
    body.fixed = body.node.grabbed() || body.node.locked();
    grabbed ||= body.node.grabbed();
  }
  const motion = ExplorerForces.step(graphPhysics.bodies, graphPhysics.links, graphPhysics.center);
  cy.batch(() => {
    for (const body of graphPhysics.bodies) if (!body.fixed) body.node.position({ x: body.x, y: body.y });
  });
  graphPhysics.quietFrames = !grabbed && motion < .08 ? graphPhysics.quietFrames + 1 : 0;
  if (graphPhysics.quietFrames < 45) graphPhysics.frame = requestAnimationFrame(physicsFrame);
}
$("btn-physics").addEventListener("click", () => {
  graphPhysics.enabled = !graphPhysics.enabled;
  $("btn-physics").setAttribute("aria-pressed", String(graphPhysics.enabled));
  $("btn-physics").textContent = graphPhysics.enabled ? "Physics on" : "Physics";
  $("btn-physics").title = graphPhysics.enabled ? "Disable forces and keep current positions" : "Enable attraction along connections and node repulsion";
  if (graphPhysics.enabled) restartPhysics(); else pausePhysics();
});
cy.on("grab free", "node", restartPhysics);
cy.on("layoutstop", restartPhysics);
document.addEventListener("visibilitychange", () => { if (document.hidden) pausePhysics(); else restartPhysics(); });
window.addEventListener("pagehide", pausePhysics);
