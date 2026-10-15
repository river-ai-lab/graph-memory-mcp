const { test } = require('node:test');
const assert = require('node:assert/strict');
const { step } = require('../static/forces.js');
const gap = b => Math.hypot(b[0].x-b[1].x,b[0].y-b[1].y);

test('connected, distant nodes converge while a dragged node stays fixed', () => {
  const bodies = [{ x: 0, y: 0, fixed: true }, { x: 600, y: 0 }];
  for (let i=0;i<300;i++) step(bodies, [[0,1]], {x:300,y:0});
  assert.equal(bodies[0].x, 0);
  assert.equal(bodies[0].y, 0);
  assert.ok(gap(bodies)<250 && gap(bodies)>100);
});

test('coincident nodes separate into finite positions', () => {
  const bodies = Array.from({length:20}, () => ({x:0,y:0}));
  for (let i=0;i<500;i++) step(bodies, [], {x:0,y:0});
  assert.ok(bodies.every(b => [b.x,b.y,b.vx,b.vy].every(Number.isFinite)));
  assert.ok(gap(bodies)>30);
});

test('isolated nodes repel and the simulation cools down', () => {
  const bodies = [{x:-5,y:0}, {x:5,y:0}];
  let motion;
  for (let i=0;i<1000;i++) motion=step(bodies, [], {x:0,y:0});
  assert.ok(gap(bodies)>100);
  assert.ok(motion<.08);
});
