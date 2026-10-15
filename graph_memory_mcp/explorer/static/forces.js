/* Small, deterministic force step, independent of the renderer and viewport. */
(function (root) {
  function step(bodies, links, center) {
    const forces = bodies.map(b => ({ x: (center.x - b.x) * .0008, y: (center.y - b.y) * .0008 }));
    for (let i = 0; i < bodies.length; i++) {
      for (let j = i + 1; j < bodies.length; j++) {
        let dx = bodies[j].x - bodies[i].x;
        let dy = bodies[j].y - bodies[i].y;
        // Give coincident nodes a repeatable separation direction.
        if (Math.abs(dx) + Math.abs(dy) < .01) {
          const angle = (i * 53 + j * 97) * Math.PI / 180;
          dx = Math.cos(angle); dy = Math.sin(angle);
        }
        const distance = Math.hypot(dx, dy);
        const repulsion = 2200 / Math.max(distance * distance, 400) + Math.max(0, 110 - distance) * .025;
        const fx = dx / distance * repulsion, fy = dy / distance * repulsion;
        forces[i].x -= fx; forces[i].y -= fy;
        forces[j].x += fx; forces[j].y += fy;
      }
    }
    for (const [i, j] of links) {
      if (i === j) continue;
      const dx = bodies[j].x - bodies[i].x, dy = bodies[j].y - bodies[i].y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const spring = (distance - 170) * .008;
      const fx = dx / distance * spring, fy = dy / distance * spring;
      forces[i].x += fx; forces[i].y += fy;
      forces[j].x -= fx; forces[j].y -= fy;
    }
    let motion = 0;
    bodies.forEach((body, i) => {
      if (body.fixed) { body.vx = 0; body.vy = 0; return; }
      body.vx = Math.max(-12, Math.min(12, ((body.vx || 0) + forces[i].x) * .82));
      body.vy = Math.max(-12, Math.min(12, ((body.vy || 0) + forces[i].y) * .82));
      body.x += body.vx; body.y += body.vy;
      motion = Math.max(motion, Math.hypot(body.vx, body.vy));
    });
    return motion;
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { step };
  else root.ExplorerForces = { step };
})(typeof globalThis === "undefined" ? this : globalThis);
