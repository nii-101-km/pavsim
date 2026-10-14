'use strict';
// Focused tests for bend-editing mode (xcos_mini/web/app.js).
// Verifies: mode toggle, Escape exit, adding detours to horizontal/vertical
// segments, removing bends (single and pair), orthogonality after repeated
// editing, endpoint attachment, serialization round-trip, and that existing
// drag/fan-out behavior is preserved outside bend-edit mode.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

function makeElement(id) {
  const classes = new Set();
  if (id === 'dialog_overlay') classes.add('hidden');
  return {
    id, textContent: '', innerHTML: '', value: '', className: '', style: {},
    classList: {
      add(c){ classes.add(c); },
      remove(c){ classes.delete(c); },
      contains(c){ return classes.has(c); },
      toggle(c){ if (classes.has(c)) classes.delete(c); else classes.add(c); },
    },
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
vm.runInContext(code, sandbox);
const state = vm.runInContext("state", sandbox);

function assertPts(actual, expected, label) {
  assert.strictEqual(JSON.stringify(actual), JSON.stringify(expected), label || "points mismatch");
}
const tick = ms => new Promise(r => setTimeout(r, ms));

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

  // Shared model: two blocks with a horizontal connection (same y)
  const model = {
    blocks: [
      { id: 'b1', type: 'signal_generator', params: {type:'sine'}, x: 100, y: 100 },
      { id: 'b2', type: 'gain', params: {k:1}, x: 400, y: 100 },
    ],
    connections: [
      { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
    ],
  };

  // ---- 1. Mode toggle -------------------------------------------------------
  {
    assert.strictEqual(state.bendEditMode, false, 'initially off');
    sandbox.toggleBendEditMode();
    assert.strictEqual(state.bendEditMode, true, 'enabled after toggle');
    sandbox.toggleBendEditMode();
    assert.strictEqual(state.bendEditMode, false, 'disabled after second toggle');
  }

  // ---- 2. Escape exits bend-edit mode --------------------------------------
  {
    sandbox.toggleBendEditMode();
    assert.strictEqual(state.bendEditMode, true, 'mode on before Escape');
    fireKey('Escape');
    assert.strictEqual(state.bendEditMode, false, 'Escape exits mode');
  }

  // ---- 3. Adding bends to a horizontal segment -----------------------------
  {
    sandbox.fromModelDict(model);
    const c = state.connections[0];
    // b1 output port: (232, 129), b2 input port: (400, 129) — horizontal
    sandbox.toggleBendEditMode();
    // Click on the horizontal segment at x=300, y=129
    fire('mousedown', 300, 129);
    assert.ok(c.route && c.route.length >= 4, 'detour inserted (>=4 points)');
    const pts = sandbox.routePoints(c);
    assertOrthogonal(pts, 'after horizontal detour insert');
    // Endpoints preserved
    assertPts(pts[0], {x:232, y:129}, 'source port preserved');
    assertPts(pts[pts.length-1], {x:400, y:129}, 'dest port preserved');
    // The detour should have gone up (negative y)
    const hasUpBend = c.route.some(p => p.y < 129);
    assert.ok(hasUpBend, 'detour goes perpendicular (up)');
    sandbox.toggleBendEditMode();
  }

  // ---- 4. Adding bends to a vertical segment -------------------------------
  {
    // Create a vertical connection: b1 at (100,100), b2 at (100,400)
    const vModel = {
      blocks: [
        { id: 'b1', type: 'signal_generator', params: {type:'sine'}, x: 100, y: 100 },
        { id: 'b2', type: 'gain', params: {k:1}, x: 100, y: 400 },
      ],
      connections: [
        { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
      ],
    };
    sandbox.fromModelDict(vModel);
    const c = state.connections[0];
    // b1 output: (232, 129), b2 input: (100, 429) — not vertical, has bends
    // Let's use a model where the connection is vertical:
    // b1 output at (232, 129), b2 input at (232, 429) — need b2.x = 232
    const vModel2 = {
      blocks: [
        { id: 'b1', type: 'signal_generator', params: {type:'sine'}, x: 100, y: 100 },
        { id: 'b2', type: 'gain', params: {k:1}, x: 232, y: 400 },
      ],
      connections: [
        { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
      ],
    };
    sandbox.fromModelDict(vModel2);
    const c2 = state.connections[0];
    // b1 output: (232, 129), b2 input: (232, 429) — vertical (same x=232)
    const pts = sandbox.routePoints(c2);
    assert.strictEqual(pts.length, 2, 'vertical straight line');
    assert.strictEqual(pts[0].x, pts[1].x, 'same x');
    sandbox.toggleBendEditMode();
    // Click on the vertical segment at x=232, y=250
    fire('mousedown', 232, 250);
    assert.ok(c2.route && c2.route.length >= 4, 'vertical detour inserted');
    const pts2 = sandbox.routePoints(c2);
    assertOrthogonal(pts2, 'after vertical detour insert');
    assertPts(pts2[0], {x:232, y:129}, 'source preserved');
    assertPts(pts2[pts2.length-1], {x:232, y:429}, 'dest preserved');
    // Detour should go right (positive x)
    const hasRightBend = c2.route.some(p => p.x > 232);
    assert.ok(hasRightBend, 'detour goes perpendicular (right)');
    sandbox.toggleBendEditMode();
  }

  // ---- 5. Removing existing bends ------------------------------------------
  {
    sandbox.fromModelDict(model);
    const c = state.connections[0];
    // First insert a detour
    sandbox.toggleBendEditMode();
    fire('mousedown', 300, 129);
    const routeLenAfterInsert = c.route.length;
    assert.ok(routeLenAfterInsert >= 4, 'route has bends after insert');
    // Now remove a bend (click on one of the off-line corners)
    // The first off-line corner is at route index 1: (300, 109)
    fire('mousedown', 300, 109);
    const routeLenAfterRemove = c.route.length;
    assert.ok(routeLenAfterRemove < routeLenAfterInsert, 'bend removed (route shorter)');
    const pts = sandbox.routePoints(c);
    assertOrthogonal(pts, 'after bend removal');
    assertPts(pts[0], {x:232, y:129}, 'source still attached');
    assertPts(pts[pts.length-1], {x:400, y:129}, 'dest still attached');
    sandbox.toggleBendEditMode();
  }

  // ---- 6. Removing a bend pair when necessary ------------------------------
  {
    sandbox.fromModelDict(model);
    const c = state.connections[0];
    sandbox.toggleBendEditMode();
    // Insert a detour at x=300
    fire('mousedown', 300, 129);
    // Route should be: [(300,129), (300,109), (320,109), (320,129)]
    assert.strictEqual(c.route.length, 4, '4-point detour');
    // Remove the first off-line corner (300, 109) — this should remove the pair
    fire('mousedown', 300, 109);
    // After pair removal, the route should be valid and orthogonal
    const pts = sandbox.routePoints(c);
    assertOrthogonal(pts, 'after pair removal');
    assertPts(pts[0], {x:232, y:129}, 'source attached');
    assertPts(pts[pts.length-1], {x:400, y:129}, 'dest attached');
    // The route should be back to a straight line (or at least valid)
    assert.ok(c.route.length <= 2, 'pair removed, route simplified');
    sandbox.toggleBendEditMode();
  }

  // ---- 7. Orthogonality after repeated editing -----------------------------
  {
    sandbox.fromModelDict(model);
    const c = state.connections[0];
    sandbox.toggleBendEditMode();
    // Insert multiple detours
    fire('mousedown', 280, 129);
    fire('mousedown', 350, 129);
    const pts = sandbox.routePoints(c);
    assertOrthogonal(pts, 'after multiple inserts');
    assertPts(pts[0], {x:232, y:129}, 'source attached');
    assertPts(pts[pts.length-1], {x:400, y:129}, 'dest attached');
    // Remove one
    if (c.route.length > 0) {
      // Click on the first off-line corner
      const corner = c.route[1];
      fire('mousedown', corner.x, corner.y);
      const pts2 = sandbox.routePoints(c);
      assertOrthogonal(pts2, 'after removal from multi-detour');
    }
    sandbox.toggleBendEditMode();
  }

  // ---- 8. Endpoint attachment ----------------------------------------------
  {
    sandbox.fromModelDict(model);
    const c = state.connections[0];
    sandbox.toggleBendEditMode();
    fire('mousedown', 300, 129);
    const pts = sandbox.routePoints(c);
    assert.strictEqual(pts[0].x, 232, 'source x');
    assert.strictEqual(pts[0].y, 129, 'source y');
    assert.strictEqual(pts[pts.length-1].x, 400, 'dest x');
    assert.strictEqual(pts[pts.length-1].y, 129, 'dest y');
    sandbox.toggleBendEditMode();
  }

  // ---- 9. Route serialization and restoration ------------------------------
  {
    sandbox.fromModelDict(model);
    const c = state.connections[0];
    sandbox.toggleBendEditMode();
    fire('mousedown', 300, 129);
    sandbox.toggleBendEditMode();
    // Serialize
    const dict = sandbox.toModelDict();
    assert.ok(dict.connections[0].route, 'route in serialized form');
    assert.ok(dict.connections[0].route.length >= 4, 'detour points serialized');
    // Restore
    sandbox.fromModelDict(dict);
    const c2 = state.connections[0];
    assert.strictEqual(c2.route.length, c.route.length, 'route length preserved');
    const pts = sandbox.routePoints(c2);
    assertOrthogonal(pts, 'restored route orthogonal');
  }

  // ---- 10. Existing dragging behavior outside bend-edit mode ---------------
  {
    // Use a model where the connection has bends (blocks at different y)
    const dragModel = {
      blocks: [
        { id: 'b1', type: 'signal_generator', params: {type:'sine'}, x: 100, y: 100 },
        { id: 'b2', type: 'gain', params: {k:1}, x: 400, y: 300 },
      ],
      connections: [
        { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
      ],
    };
    sandbox.fromModelDict(dragModel);
    const c = state.connections[0];
    assert.strictEqual(state.bendEditMode, false, 'not in bend edit mode');
    // Materialize and drag a bend (existing behavior)
    sandbox.materializeRoute(c);
    assert.ok(c.route && c.route.length > 0, 'route materialized');
    const before = JSON.stringify(c.route);
    sandbox.dragBend(c, 0, 10, 0);
    const after = JSON.stringify(c.route);
    assert.notStrictEqual(before, after, 'bend drag works outside mode');
    const pts = sandbox.routePoints(c);
    assertOrthogonal(pts, 'orthogonal after drag outside mode');
  }

  // ---- 11. Existing fan-out connections ------------------------------------
  {
    sandbox.fromModelDict(model);
    const cA = {from:'b1', fromPort:0, to:'b2', toPort:0};
    const cB = {from:'b1', fromPort:0, to:'b2', toPort:0};
    // Use different to_port to avoid duplicate
    const cB2 = {from:'b1', fromPort:0, to:'b2', toPort:0};
    // Actually use a different target
    const model2 = {
      blocks: [
        { id: 'b1', type: 'signal_generator', params: {type:'sine'}, x: 100, y: 100 },
        { id: 'b2', type: 'gain', params: {k:1}, x: 400, y: 100 },
        { id: 'b3', type: 'graph_display', params: {}, x: 400, y: 300 },
      ],
      connections: [
        { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
        { from: 'b1', from_port: 0, to: 'b3', to_port: 0 },
      ],
    };
    sandbox.fromModelDict(model2);
    const pA = sandbox.routePoints(state.connections[0]);
    const pB = sandbox.routePoints(state.connections[1]);
    assertOrthogonal(pA, 'fan-out A orthogonal');
    assertOrthogonal(pB, 'fan-out B orthogonal');
    assertPts(pA[0], pB[0], 'shared source port');
    // Both should be independently editable in bend-edit mode
    sandbox.toggleBendEditMode();
    fire('mousedown', 300, 129); // on connection A's horizontal segment
    const ptsA = sandbox.routePoints(state.connections[0]);
    assertOrthogonal(ptsA, 'fan-out A after detour');
    sandbox.toggleBendEditMode();
  }

  console.log('ALL BEND EDIT TESTS PASSED');
})().catch(e => { console.error('TEST FAILED:', e && e.stack || e); process.exit(1); });
