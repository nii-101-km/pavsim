'use strict';
// Focused tests for orthogonal editable connections (xcos_mini/web/app.js).
// Loads the real app.js in a minimal DOM mock (same pattern as test_tooltip.js)
// and verifies: default orthogonal route generation, segment dragging, bend
// dragging, endpoint attachment after block moves, route serialization and
// restoration, legacy loading, connection creation/deletion, and fan-out.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

function makeElement(id) {
  return {
    id, dataset: {}, textContent: '', innerHTML: '', value: '', className: '', style: {},
    classList: { add(){}, remove(){}, contains(){ return false; }, toggle(){} },
    appendChild(c){ return c; }, addEventListener(){}, removeEventListener(){},
    querySelectorAll(){ return []; },
    getBoundingClientRect(){ return {left:0, top:0, width:800, height:600}; },
    clientWidth: 800, clientHeight: 600,
  };
}
const ctxMock = new Proxy({}, {
  get: (t, p) => (p in t) ? t[p] : (() => {}),
  set: (t, p, v) => { t[p] = v; return true; },
});
const canvasHandlers = {};
const canvasMock = {
  id: 'canvas', width: 800, height: 600, title: '',
  parentElement: { clientWidth: 800, clientHeight: 600 },
  getContext: () => ctxMock,
  addEventListener: (type, fn) => { canvasHandlers[type] = fn; },
  getBoundingClientRect(){ return {left:0, top:0, width:800, height:600}; },
};
const elements = {};
function getElementById(id) {
  if (id === 'canvas') return canvasMock;
  if (!elements[id]) elements[id] = makeElement(id);
  return elements[id];
}
const documentMock = {
  getElementById, createElement: t => makeElement(t),
  querySelectorAll: () => [], activeElement: null, addEventListener(){},
  body: makeElement('body'), documentElement: makeElement('html'),
};
const windowHandlers = {};
const windowMock = {
  addEventListener: (t, fn) => { windowHandlers[t] = fn; },
  open: () => null, innerWidth: 800, innerHeight: 600,
};
const BLOCK_TYPES = [
  { name: 'gain', n_inputs: 1, n_outputs: 1, parameters: {k:1}, state_kind: 'none' },
  { name: 'addition', n_inputs: 2, n_outputs: 1, parameters: {}, state_kind: 'none' },
  { name: 'signal_generator', n_inputs: 0, n_outputs: 1, parameters: {type:'sine'}, state_kind: 'none' },
  { name: 'graph_display', n_inputs: 1, n_outputs: 0, parameters: {}, state_kind: 'none' },
];
const fetchMock = async (p) => ({
  ok: true,
  json: async () => {
    if (p === '/api/blocks') return { blocks: BLOCK_TYPES };
    if (p === '/api/library') return { tree: [], load_errors: [] };
    if (p === '/api/models') return { models: [] };
    return {};
  },
});
const sandbox = {
  document: documentMock, window: windowMock, fetch: fetchMock,
  confirm: () => true, console, setTimeout, clearTimeout,
  Math, JSON, Object, Array, String, Number, Promise, Proxy,
};
vm.createContext(sandbox);
const code = fs.readFileSync(path.join(__dirname, '..', 'xcos_mini', 'web', 'app.js'), 'utf8');
require('./load_i18n')(sandbox);
vm.runInContext(code, sandbox);
const state = vm.runInContext("state", sandbox); // top-level const in app.js is not a sandbox property
// deepStrictEqual fails across vm realms (different Object.prototype); compare via JSON.
function assertPts(actual, expected, label) {
  assert.strictEqual(JSON.stringify(actual), JSON.stringify(expected), label || "points mismatch");
}
const tick = ms => new Promise(r => setTimeout(r, ms));

// Synthetic event dispatch on the canvas (coords map 1:1, rect at 0,0).
function fire(type, x, y, extra) {
  const fn = canvasHandlers[type];
  if (!fn) throw new Error('no canvas handler for ' + type);
  fn(Object.assign({button: 0, clientX: x, clientY: y, preventDefault(){}, target: canvasMock, currentTarget: canvasMock}, extra || {}));
}
function fireKey(key) {
  if (windowHandlers.keydown) windowHandlers.keydown({key: key, preventDefault(){}});
}
function assertOrthogonal(pts, label) {
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i-1], b = pts[i];
    assert.ok((a.x === b.x) || (a.y === b.y),
      label + ': segment ' + i + ' not axis-aligned: ' + JSON.stringify(a) + ' -> ' + JSON.stringify(b));
    assert.ok(a.x !== b.x || a.y !== b.y, label + ': zero-length segment ' + i);
  }
}

(async () => {
  await tick(20);
  await sandbox.loadBlockTypes();

  // ---- shared model -------------------------------------------------------
  const model = {
    blocks: [
      { id: 'b1', type: 'signal_generator', params: {type:'sine'}, x: 100, y: 100 },
      { id: 'b2', type: 'gain', params: {k:1}, x: 400, y: 200 },
      { id: 'b3', type: 'graph_display', params: {}, x: 400, y: 400 },
    ],
    connections: [
      { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
    ],
  };
  sandbox.fromModelDict(model);
  const c0 = state.connections[0];

  // ---- 1. default orthogonal route generation -----------------------------
  {
    const pts = sandbox.routePoints(c0);
    assert.strictEqual(pts.length, 4, 'expected 2 bends for diagonal ports');
    assertPts(pts[0], {x:232, y:129}, 'source port');
    assertPts(pts[3], {x:400, y:229}, 'dest port');
    assertPts(pts[1], {x:316, y:129}, 'bend 1');
    assertPts(pts[2], {x:316, y:229}, 'bend 2');
    assertOrthogonal(pts, 'default route');
  }
  // straight horizontal (same row, dest to the right): 0 bends
  {
    state.blocks[1].y = 100; // b2 input port now (400,129), same y as source
    const pts = sandbox.routePoints(c0);
    assert.strictEqual(pts.length, 2, 'straight line has no bends');
    assertPts(pts, [{x:232,y:129},{x:400,y:129}]);
    state.blocks[1].y = 200; // restore
  }
  // feedback (dest to the left): exits right, 2 bends
  {
    const fb = {from:'b2', fromPort:0, to:'b1', toPort:0}; // b1 has no inputs; use b3 instead
    const cfb = {from:'b2', fromPort:0, to:'b3', toPort:0};
    state.connections.push(cfb);
    const pts = sandbox.routePoints(cfb);
    // p1=(532,229), p2=(400,429): p2.x < p1.x -> exitX=572
    assertPts(pts[1], {x:572, y:229}, 'feedback bend 1');
    assertPts(pts[2], {x:572, y:429}, 'feedback bend 2');
    assertOrthogonal(pts, 'feedback route');
    state.connections.pop();
  }

  // ---- 2. segment dragging -------------------------------------------------
  {
    sandbox.materializeRoute(c0);
    assertPts(c0.route, [{x:316,y:129},{x:316,y:229}], 'materialized default');
    // middle vertical segment (segIdx 1) slides horizontally
    sandbox.dragSegment(c0, 1, 50, 0);
    assertPts(c0.route, [{x:366,y:129},{x:366,y:229}], 'vertical segment moved horizontally');
    assertOrthogonal(sandbox.routePoints(c0), 'after segment drag');
    // end segments are locked (touch a port): no change
    sandbox.dragSegment(c0, 0, 0, 30);
    sandbox.dragSegment(c0, 2, 0, 30);
    assertPts(c0.route, [{x:366,y:129},{x:366,y:229}], 'end segments locked');
    // vertical drag of a vertical segment is ignored
    sandbox.dragSegment(c0, 1, 0, 40);
    assertPts(c0.route, [{x:366,y:129},{x:366,y:229}], 'vertical segment ignores vertical drag');
  }

  // ---- 3. bend dragging ----------------------------------------------------
  {
    // horizontal drag of bend 0 slides the vertical channel (both bends)
    sandbox.dragBend(c0, 0, -20, 0);
    assertPts(c0.route, [{x:346,y:129},{x:346,y:229}], 'bend drag slides channel');
    assertOrthogonal(sandbox.routePoints(c0), 'after bend drag');
    // vertical drag of an end-adjacent bend is not free: ignored
    sandbox.dragBend(c0, 0, 0, 30);
    assertPts(c0.route, [{x:346,y:129},{x:346,y:229}], 'locked bend vertical drag ignored');
    // endpoints never disconnected
    const pts = sandbox.routePoints(c0);
    assertPts(pts[0], {x:232,y:129});
    assertPts(pts[3], {x:400,y:229});
  }

  // ---- 4. endpoint attachment after moving blocks --------------------------
  {
    const b2 = state.blocks[1];
    const ox = b2.x, oy = b2.y;
    const ddx = 10, ddy = 20;
    // use the real adjustment (must run before the block position changes)
    for (const c of state.connections)
      if (c.from === b2.id || c.to === b2.id) sandbox.adjustRouteForBlockMove(c, b2.id, ddx, ddy);
    b2.x += ddx; b2.y += ddy;
    // last bend (346,229) had a horizontal last segment -> only its y follows the port
    assertPts(c0.route, [{x:346,y:129},{x:346,y:249}], 'only port-adjacent bend coordinate adjusted');
    const pts = sandbox.routePoints(c0);
    assertPts(pts[3], {x:410, y:249}, 'dest port follows block');
    assertOrthogonal(pts, 'after block move');
    // move back; manual routing must be restored exactly
    for (const c of state.connections)
      if (c.from === b2.id || c.to === b2.id) sandbox.adjustRouteForBlockMove(c, b2.id, -ddx, -ddy);
    b2.x = ox; b2.y = oy;
    assertPts(c0.route, [{x:346,y:129},{x:346,y:229}], 'route restored after move-back');
  }

  // ---- 5. route serialization and restoration ------------------------------
  {
    const dict = sandbox.toModelDict();
    const saved = dict.connections[0];
    assert.ok(Array.isArray(saved.route), 'route serialized');
    assert.strictEqual(saved.route.length, 2);
    sandbox.fromModelDict(dict);
    const c1 = state.connections[0];
    assertPts(c1.route, c0.route.map(p => ({x:Math.round(p.x), y:Math.round(p.y)})), 'route restored');
  }

  // ---- 6. legacy project without route metadata ----------------------------
  {
    const legacy = {
      blocks: model.blocks,
      connections: [{from:'b1', from_port:0, to:'b2', to_port:0}],
    };
    sandbox.fromModelDict(legacy);
    const c2 = state.connections[0];
    assert.ok(!c2.route || c2.route.length === 0, 'legacy has no stored route');
    const pts = sandbox.routePoints(c2);
    assert.strictEqual(pts.length, 4, 'legacy gets default route');
    assertOrthogonal(pts, 'legacy default route');
  }

  // ---- 7. connection creation and deletion ---------------------------------
  {
    sandbox.fromModelDict(model);
    const nBefore = state.connections.length;
    // create b1.out0 -> b3.in0 via the real mousedown/mouseup handlers
    fire('mousedown', 232, 129);           // on b1 output port
    fire('mousemove', 300, 300);
    fire('mouseup', 400, 429);             // on b3 input port
    assert.strictEqual(state.connections.length, nBefore + 1, 'connection created');
    const nc = state.connections[nBefore];
    assert.strictEqual(nc.from, 'b1'); assert.strictEqual(nc.to, 'b3');
    // duplicate (same 4-tuple) is rejected
    fire('mousedown', 232, 129);
    fire('mouseup', 400, 429);
    assert.strictEqual(state.connections.length, nBefore + 1, 'duplicate rejected');
    // select + delete via Delete key
    fire('click', 316, 129);               // on the new connection's route
    assert.ok(state.selected && state.selected.kind === 'conn', 'connection selected');
    fireKey('Delete');
    assert.strictEqual(state.connections.length, nBefore, 'connection deleted');
  }

  // ---- 8. fan-out: multiple connections from one output --------------------
  {
    sandbox.fromModelDict(model);
    const cA = {from:'b1', fromPort:0, to:'b2', toPort:0};
    const cB = {from:'b1', fromPort:0, to:'b3', toPort:0};
    state.connections.push(cA, cB);
    const pA = sandbox.routePoints(cA), pB = sandbox.routePoints(cB);
    assertOrthogonal(pA, 'fan-out A');
    assertOrthogonal(pB, 'fan-out B');
    // both start at the same output port
    assertPts(pA[0], pB[0], 'shared source port');
    // distinct default routes (offset) so they remain individually editable
    assert.notDeepStrictEqual(pA.slice(1,-1), pB.slice(1,-1), 'fan-out routes differ');
    // each can be dragged independently
    sandbox.materializeRoute(cA); sandbox.materializeRoute(cB);
    sandbox.dragBend(cA, 0, 30, 0);
    assert.notDeepStrictEqual(sandbox.routePoints(cA).slice(1,-1), sandbox.routePoints(cB).slice(1,-1), 'independent after drag');
    assertOrthogonal(sandbox.routePoints(cA), 'fan-out A after drag');
    assertOrthogonal(sandbox.routePoints(cB), 'fan-out B after drag');
  }

  console.log('ALL ROUTE TESTS PASSED');
})().catch(e => { console.error('TEST FAILED:', e && e.stack || e); process.exit(1); });
