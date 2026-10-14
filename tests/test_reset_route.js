'use strict';
// Focused tests for the Reset Route mode (xcos_mini/web/app.js).
// Verifies: mutual exclusion, toggle-off, Escape, reset behavior (segment click,
// bend click, already-automatic, multiple connections), isolation, orthogonal
// geometry, endpoint preservation, save/load persistence, mode stays active
// after reset, and regression (Add Bend, bend dragging, segment dragging).
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

function makeElement(id) {
  return {
    id, dataset: {}, textContent: '', innerHTML: '', value: '', className: '', style: {},
    classList: {
      _set: new Set(),
      add(c){ this._set.add(c); },
      remove(c){ this._set.delete(c); },
      contains(c){ return this._set.has(c); },
      toggle(c, force){ if (force === undefined) { if (this._set.has(c)) this._set.delete(c); else this._set.add(c); } else if (force) this._set.add(c); else this._set.delete(c); },
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
if (!elements['dialog_overlay']) elements['dialog_overlay'] = makeElement('dialog_overlay');
elements['dialog_overlay'].classList.add('hidden');
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

  // Shared model: b1 (signal) -> b2 (gain) -> b3 (graph)
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

  // ---- 1. Mutual exclusion: activating one mode disables the other ---------
  {
    sandbox.fromModelDict(model);
    // Activate Add Bend
    sandbox.toggleBendEditMode();
    assert.strictEqual(state.bendEditMode, 'edit_bends', 'edit_bends active');
    assert.ok(elements['edit_bends'].classList.contains('active'), 'edit_bends button active');
    assert.ok(!elements['reset_route'].classList.contains('active'), 'reset_route button not active');

    // Activate Reset Route: should disable Add Bend
    sandbox.toggleResetRouteMode();
    assert.strictEqual(state.bendEditMode, 'reset_route', 'reset_route active after switching');
    assert.ok(!elements['edit_bends'].classList.contains('active'), 'edit_bends button deactivated');
    assert.ok(elements['reset_route'].classList.contains('active'), 'reset_route button active');

    // Activate Add Bend again: should disable Reset Route
    sandbox.toggleBendEditMode();
    assert.strictEqual(state.bendEditMode, 'edit_bends', 'edit_bends re-activated');
    assert.ok(elements['edit_bends'].classList.contains('active'), 'edit_bends button active again');
    assert.ok(!elements['reset_route'].classList.contains('active'), 'reset_route button deactivated');

    // Toggle off
    sandbox.toggleBendEditMode();
    assert.strictEqual(state.bendEditMode, null, 'mode off after toggle');
    assert.ok(!elements['edit_bends'].classList.contains('active'), 'edit_bends button off');
    assert.ok(!elements['reset_route'].classList.contains('active'), 'reset_route button off');
  }

  // ---- 2. Toggle-off behavior ---------------------------------------------
  {
    sandbox.fromModelDict(model);
    sandbox.toggleResetRouteMode();
    assert.strictEqual(state.bendEditMode, 'reset_route');
    sandbox.toggleResetRouteMode();
    assert.strictEqual(state.bendEditMode, null, 'reset_route toggled off');
    assert.ok(!elements['reset_route'].classList.contains('active'), 'button off');
  }

  // ---- 3. Escape exits either mode ----------------------------------------
  {
    sandbox.fromModelDict(model);
    sandbox.toggleBendEditMode();
    assert.strictEqual(state.bendEditMode, 'edit_bends');
    fireKey('Escape');
    assert.strictEqual(state.bendEditMode, null, 'Escape exits edit_bends');

    sandbox.toggleResetRouteMode();
    assert.strictEqual(state.bendEditMode, 'reset_route');
    fireKey('Escape');
    assert.strictEqual(state.bendEditMode, null, 'Escape exits reset_route');
  }

  // ---- 4. Reset Route: clicking a segment resets the connection -----------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    sandbox.materializeRoute(c0);
    // Add a detour to create manual bends
    sandbox.insertDetour(c0, 0, 274, 129);
    assert.ok(c0.route.length >= 4, 'route has 4+ bends after detour');
    const routeWithBends = JSON.stringify(c0.route);

    // Activate Reset Route and click on a segment
    sandbox.toggleResetRouteMode();
    // Click on the middle of the first segment
    fire('mousedown', 274, 129);
    // Route should be reset (null means automatic)
    assert.strictEqual(c0.route, null, 'route reset to null (automatic)');
    // Mode should still be active
    assert.strictEqual(state.bendEditMode, 'reset_route', 'mode stays active after reset');
    sandbox.toggleResetRouteMode(); // off
  }

  // ---- 5. Reset Route: clicking a bend resets the connection --------------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    sandbox.materializeRoute(c0);
    sandbox.insertDetour(c0, 0, 274, 129);
    assert.ok(c0.route.length >= 4, 'route has bends');

    sandbox.toggleResetRouteMode();
    // Click on a bend point
    const pts = sandbox.routePoints(c0);
    fire('mousedown', pts[2].x, pts[2].y);
    assert.strictEqual(c0.route, null, 'route reset when clicking a bend');
    sandbox.toggleResetRouteMode(); // off
  }

  // ---- 6. Reset an already-automatic connection (no-op) -------------------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    // Route is already null (automatic)
    assert.ok(c0.route === null || c0.route === undefined, "route is already automatic");

    sandbox.toggleResetRouteMode();
    fire('mousedown', 274, 129);
    assert.ok(c0.route === null || c0.route === undefined, "route remains null after reset of automatic route");
    // Connection still exists
    assert.strictEqual(state.connections.length, 1, 'connection still exists');
    sandbox.toggleResetRouteMode(); // off
  }

  // ---- 7. Reset multiple connections one after another --------------------
  {
    const model2 = {
      blocks: [
        { id: 'b1', type: 'signal_generator', params: {type:'sine'}, x: 100, y: 100 },
        { id: 'b2', type: 'gain', params: {k:1}, x: 400, y: 200 },
        { id: 'b3', type: 'graph_display', params: {}, x: 400, y: 400 },
        { id: 'b4', type: 'gain', params: {k:2}, x: 700, y: 200 },
      ],
      connections: [
        { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
        { from: 'b2', from_port: 0, to: 'b3', to_port: 0 },
      ],
    };
    sandbox.fromModelDict(model2);
    const c0 = state.connections[0];
    const c1 = state.connections[1];
    sandbox.materializeRoute(c0);
    sandbox.materializeRoute(c1);
    // Add detours to both
    sandbox.insertDetour(c0, 0, 274, 129);
    sandbox.insertDetour(c1, 0, 500, 229);
    assert.ok(c0.route.length >= 4, 'c0 has bends');
    assert.ok(c1.route.length >= 4, 'c1 has bends');

    // Reset both in sequence without leaving the mode
    sandbox.toggleResetRouteMode();
    fire('mousedown', 274, 129); // reset c0
    assert.strictEqual(c0.route, null, 'c0 reset');
    assert.strictEqual(state.bendEditMode, 'reset_route', 'mode still active');
    fire('mousedown', 500, 229); // reset c1
    assert.strictEqual(c1.route, null, 'c1 reset');
    assert.strictEqual(state.bendEditMode, 'reset_route', 'mode still active after second reset');
    sandbox.toggleResetRouteMode(); // off
  }

  // ---- 8. Isolation: resetting one connection does not affect another -----
  {
    const model2 = {
      blocks: [
        { id: 'b1', type: 'signal_generator', params: {type:'sine'}, x: 100, y: 100 },
        { id: 'b2', type: 'gain', params: {k:1}, x: 400, y: 200 },
        { id: 'b3', type: 'graph_display', params: {}, x: 400, y: 400 },
      ],
      connections: [
        { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
        { from: 'b2', from_port: 0, to: 'b3', to_port: 0 },
      ],
    };
    sandbox.fromModelDict(model2);
    const c0 = state.connections[0];
    const c1 = state.connections[1];
    sandbox.materializeRoute(c0);
    sandbox.materializeRoute(c1);
    // Add detour to c0 only
    sandbox.insertDetour(c0, 0, 274, 129);
    const c1RouteBefore = JSON.stringify(c1.route);

    // Reset c0
    sandbox.toggleResetRouteMode();
    fire('mousedown', 274, 129);
    assert.strictEqual(c0.route, null, 'c0 reset');
    // c1 should be unchanged
    assert.strictEqual(JSON.stringify(c1.route), c1RouteBefore, 'c1 unchanged');
    sandbox.toggleResetRouteMode(); // off
  }

  // ---- 9. Orthogonal geometry after reset ---------------------------------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    sandbox.materializeRoute(c0);
    sandbox.insertDetour(c0, 0, 274, 129);
    assert.ok(c0.route.length >= 4, 'route has bends before reset');

    sandbox.toggleResetRouteMode();
    fire('mousedown', 274, 129);
    const ptsAfter = sandbox.routePoints(c0);
    assertOrthogonal(ptsAfter, 'after reset');
    sandbox.toggleResetRouteMode(); // off
  }

  // ---- 10. Endpoint preservation after reset ------------------------------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    sandbox.materializeRoute(c0);
    sandbox.insertDetour(c0, 0, 274, 129);

    sandbox.toggleResetRouteMode();
    fire('mousedown', 274, 129);
    const ptsAfter = sandbox.routePoints(c0);
    // Source port: b1 output at (100+132, 100+29) = (232, 129)
    // Dest port: b2 input at (400, 200+29) = (400, 229)
    assertPts(ptsAfter[0], {x: 232, y: 129}, 'source port preserved');
    assertPts(ptsAfter[ptsAfter.length - 1], {x: 400, y: 229}, 'dest port preserved');
    sandbox.toggleResetRouteMode(); // off
  }

  // ---- 11. Save/load persistence after reset ------------------------------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    sandbox.materializeRoute(c0);
    sandbox.insertDetour(c0, 0, 274, 129);
    assert.ok(c0.route.length >= 4, 'route has bends before reset');

    sandbox.toggleResetRouteMode();
    fire('mousedown', 274, 129);
    assert.strictEqual(c0.route, null, 'route reset');
    sandbox.toggleResetRouteMode(); // off

    // Serialize and restore
    const dict = sandbox.toModelDict();
    // route should be null or absent in serialized form
    const serializedRoute = dict.connections[0].route;
    assert.ok(serializedRoute === null || serializedRoute === undefined, 'route is null/absent in serialized form');
    sandbox.fromModelDict(dict);
    const c1 = state.connections[0];
    assert.ok(c1.route === null || c1.route === undefined, "route still null after save/load");
  }

  // ---- 12. Mode stays active after reset (does not auto-exit) -------------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    sandbox.materializeRoute(c0);
    sandbox.insertDetour(c0, 0, 274, 129);

    sandbox.toggleResetRouteMode();
    fire('mousedown', 274, 129);
    assert.strictEqual(state.bendEditMode, 'reset_route', 'mode still active after reset');
    assert.ok(elements['reset_route'].classList.contains('active'), 'button still highlighted');
    sandbox.toggleResetRouteMode(); // off
  }

  // ---- 13. Clicking empty canvas in reset_route mode does nothing ---------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    sandbox.materializeRoute(c0);
    sandbox.insertDetour(c0, 0, 274, 129);
    const routeBefore = JSON.stringify(c0.route);
    const nConns = state.connections.length;

    sandbox.toggleResetRouteMode();
    fire('mousedown', 10, 500); // far from any connection
    assert.strictEqual(JSON.stringify(c0.route), routeBefore, 'route unchanged after empty click');
    assert.strictEqual(state.connections.length, nConns, 'no connection added/removed');
    assert.strictEqual(state.bendEditMode, 'reset_route', 'mode still active');
    sandbox.toggleResetRouteMode(); // off
  }

  // ---- 14. Reset Route mode does not start new connections or move blocks --
  {
    sandbox.fromModelDict(model);
    state.drag = null;
    const b2 = state.blocks[1];
    const bx = b2.x, by = b2.y;
    sandbox.toggleResetRouteMode();
    // Click on a port area (should not start a connection)
    fire('mousedown', 232, 129);
    assert.strictEqual(state.pendingConn, null, 'no pending connection started');
    // Click on a block (should not start block drag)
    fire('mousedown', 450, 220);
    assert.strictEqual(state.drag, null, 'no block drag started');
    assert.strictEqual(b2.x, bx, 'block not moved');
    assert.strictEqual(b2.y, by, 'block not moved');
    sandbox.toggleResetRouteMode(); // off
  }

  // ---- 15. Regression: Add Bend still works --------------------------------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    sandbox.materializeRoute(c0);
    const routeBefore = JSON.stringify(c0.route);

    sandbox.toggleBendEditMode();
    fire('mousedown', 274, 129);
    assert.notStrictEqual(JSON.stringify(c0.route), routeBefore, 'bend added in edit_bends mode');
    assert.ok(c0.route.length > 2, 'route has more bends after insert');
    sandbox.toggleBendEditMode(); // off
  }

  // ---- 16. Regression: Bend dragging still works ---------------------------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    sandbox.materializeRoute(c0);
    sandbox.dragBend(c0, 0, 30, 0);
    assertOrthogonal(sandbox.routePoints(c0), 'after bend drag');
  }

  // ---- 17. Regression: Segment dragging still works ------------------------
  {
    sandbox.fromModelDict(model);
    const c0 = state.connections[0];
    sandbox.materializeRoute(c0);
    sandbox.dragSegment(c0, 1, -10, 0);
    assertOrthogonal(sandbox.routePoints(c0), 'after segment drag');
  }

  console.log('ALL RESET ROUTE TESTS PASSED');
})().catch(e => { console.error('TEST FAILED:', e && e.stack || e); process.exit(1); });
