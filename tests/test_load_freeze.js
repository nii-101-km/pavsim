'use strict';
// Regression test: loading a diagram must reset bendEditMode and drag state,
// preventing the canvas from becoming unresponsive ("frozen").
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

function makeElement(id) {
  return {
    id, textContent: '', innerHTML: '', value: '', className: '', style: {},
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
  { name: 'constant', n_inputs: 0, n_outputs: 1, parameters: {value:1}, state_kind: 'none' },
  { name: 'gain', n_inputs: 1, n_outputs: 1, parameters: {k:1}, state_kind: 'none' },
  { name: 'graph_display', n_inputs: 1, n_outputs: 0, parameters: {}, state_kind: 'none' },
];
const fetchMock = async (p) => ({
  ok: true,
  json: async () => {
    if (p === '/api/blocks') return { blocks: BLOCK_TYPES };
    if (p === '/api/library') return { tree: [], load_errors: [] };
    if (p === '/api/models') return { models: ['test_model'] };
    if (p.startsWith('/api/load')) return { name: 'test_model', model: {
      blocks: [
        { id: 'b1', type: 'constant', params: {value:1}, x: 100, y: 100 },
        { id: 'b2', type: 'gain', params: {k:2}, x: 400, y: 200 },
      ],
      connections: [
        { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
      ],
    }};
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

const tick = ms => new Promise(r => setTimeout(r, ms));

function fire(type, x, y, extra) {
  const fn = canvasHandlers[type];
  if (!fn) throw new Error('no canvas handler for ' + type);
  fn(Object.assign({button: 0, clientX: x, clientY: y, preventDefault(){}, target: canvasMock, currentTarget: canvasMock}, extra || {}));
}

(async () => {
  await tick(20);
  await sandbox.loadBlockTypes();

  // ---- Test 1: fromModelDict resets bendEditMode (edit_bends) ----
  {
    // Enter Add Bend mode
    sandbox.toggleBendEditMode();
    assert.strictEqual(state.bendEditMode, 'edit_bends', 'precondition: edit_bends active');
    assert.ok(elements['edit_bends'].classList.contains('active'), 'precondition: button active');

    // Load a diagram (simulates user clicking Load while in Add Bend mode)
    sandbox.fromModelDict({
      blocks: [{ id: 'b1', type: 'constant', params: {value:1}, x: 100, y: 100 }],
      connections: [],
    });

    assert.strictEqual(state.bendEditMode, null,
      'REGRESSION: fromModelDict must reset bendEditMode to null');
    assert.ok(!elements['edit_bends'].classList.contains('active'),
      'REGRESSION: edit_bends button must be deactivated after load');
    assert.ok(!elements['reset_route'].classList.contains('active'),
      'REGRESSION: reset_route button must be deactivated after load');
  }

  // ---- Test 2: fromModelDict resets bendEditMode (reset_route) ----
  {
    // Enter Reset Route mode
    sandbox.toggleResetRouteMode();
    assert.strictEqual(state.bendEditMode, 'reset_route', 'precondition: reset_route active');

    // Load a diagram
    sandbox.fromModelDict({
      blocks: [{ id: 'b1', type: 'constant', params: {value:1}, x: 100, y: 100 }],
      connections: [],
    });

    assert.strictEqual(state.bendEditMode, null,
      'REGRESSION: fromModelDict must reset bendEditMode (reset_route) to null');
    assert.ok(!elements['reset_route'].classList.contains('active'),
      'REGRESSION: reset_route button must be deactivated after load');
  }

  // ---- Test 3: fromModelDict resets state.drag ----
  {
    // Simulate a stale drag state
    state.drag = { kind: 'block', block: {id:'old'}, dx: 0, dy: 0 };

    sandbox.fromModelDict({
      blocks: [{ id: 'b1', type: 'constant', params: {value:1}, x: 100, y: 100 }],
      connections: [],
    });

    assert.strictEqual(state.drag, null,
      'REGRESSION: fromModelDict must reset state.drag to null');
  }

  // ---- Test 4: Canvas is interactive after load (block click works) ----
  {
    // Load a diagram with a block at (100, 100)
    sandbox.fromModelDict({
      blocks: [{ id: 'b1', type: 'constant', params: {value:1}, x: 100, y: 100 }],
      connections: [],
    });

    // Simulate a mousedown on the block (should set state.drag for block drag)
    fire('mousedown', 120, 120);
    assert.ok(state.drag !== null,
      'REGRESSION: mousedown on a block after load must initiate drag (canvas is interactive)');
    assert.strictEqual(state.drag.kind, 'block', 'drag kind should be block');
    state.drag = null; // cleanup
  }

  // ---- Test 5: Repeated loads do not accumulate state ----
  {
    const model = {
      blocks: [{ id: 'b1', type: 'constant', params: {value:1}, x: 100, y: 100 }],
      connections: [],
    };
    for (let i = 0; i < 5; i++) {
      sandbox.fromModelDict(model);
    }
    assert.strictEqual(state.blocks.length, 1, 'repeated loads must not duplicate blocks');
    assert.strictEqual(state.connections.length, 0, 'repeated loads must not duplicate connections');
    assert.strictEqual(state.bendEditMode, null, 'bendEditMode must remain null after repeated loads');
    assert.strictEqual(state.drag, null, 'drag must remain null after repeated loads');
  }

  // ---- Test 6: Load with connections preserves them correctly ----
  {
    sandbox.fromModelDict({
      blocks: [
        { id: 'b1', type: 'constant', params: {value:1}, x: 100, y: 100 },
        { id: 'b2', type: 'gain', params: {k:2}, x: 400, y: 200 },
      ],
      connections: [
        { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
      ],
    });
    assert.strictEqual(state.blocks.length, 2, 'both blocks loaded');
    assert.strictEqual(state.connections.length, 1, 'connection loaded');
    assert.strictEqual(state.connections[0].from, 'b1');
    assert.strictEqual(state.connections[0].to, 'b2');
  }

  // ---- Test 7: Load with manual routes preserves them ----
  {
    sandbox.fromModelDict({
      blocks: [
        { id: 'b1', type: 'constant', params: {value:1}, x: 100, y: 100 },
        { id: 'b2', type: 'gain', params: {k:2}, x: 400, y: 300 },
      ],
      connections: [
        { from: 'b1', from_port: 0, to: 'b2', to_port: 0,
          route: [{x: 200, y: 100}, {x: 200, y: 300}] },
      ],
    });
    assert.strictEqual(state.connections[0].route.length, 2, 'manual route preserved');
    assert.strictEqual(state.connections[0].route[0].x, 200);
    assert.strictEqual(state.connections[0].route[1].y, 300);
  }

  console.log('ALL LOAD FREEZE REGRESSION TESTS PASSED');
})().catch(err => { console.error('FAIL:', err.message); process.exit(1); });
