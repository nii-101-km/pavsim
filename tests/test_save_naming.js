'use strict';
// Regression tests: saved-diagram naming, selection, and refresh behavior.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

function makeElement(id) {
  const el = {
    id, dataset: {}, textContent: '', value: '', className: '', style: {},
    classList: {
      _set: new Set(),
      add(c){ this._set.add(c); },
      remove(c){ this._set.delete(c); },
      contains(c){ return this._set.has(c); },
      toggle(c, force){ if (force === undefined) { if (this._set.has(c)) this._set.delete(c); else this._set.add(c); } else if (force) this._set.add(c); else this._set.delete(c); },
    },
    appendChild(c){ this._children = this._children || []; this._children.push(c); return c; },
    addEventListener(){}, removeEventListener(){},
    querySelectorAll(){ return []; },
    getBoundingClientRect(){ return {left:0, top:0, width:800, height:600}; },
    clientWidth: 800, clientHeight: 600,
  };
  // Simulate select behavior: setting innerHTML resets value
  let _innerHTML = '';
  Object.defineProperty(el, 'innerHTML', {
    get: () => _innerHTML,
    set: (v) => { _innerHTML = v; if (v === '') el.value = ''; },
  });
  return el;
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

// Configurable fetch mock for testing different scenarios
let fetchBehavior = { models: ['alpha', 'beta', 'gamma'], loadOk: true, saveOk: true, modelsError: false };
const fetchMock = async (p, opts) => {
  if (p === '/api/blocks') return { ok: true, json: async () => ({ blocks: BLOCK_TYPES }) };
  if (p === '/api/library') return { ok: true, json: async () => ({ tree: [], load_errors: [] }) };
  if (p === '/api/models') {
    if (fetchBehavior.modelsError) return { ok: false, status: 500, json: async () => ({ error: 'server error' }) };
    return { ok: true, json: async () => ({ models: fetchBehavior.models }) };
  }
  if (p.startsWith('/api/load')) {
    if (!fetchBehavior.loadOk) return { ok: false, status: 404, json: async () => ({ error: 'not found' }) };
    const name = new URL('http://x' + p).searchParams.get('name');
    return { ok: true, json: async () => ({ name, model: {
      blocks: [{ id: 'b1', type: 'constant', params: {value:42}, x: 100, y: 100 }],
      connections: [],
    }}) };
  }
  if (p === '/api/save') {
    if (!fetchBehavior.saveOk) return { ok: false, status: 500, json: async () => ({ error: 'save failed' }) };
    return { ok: true, json: async () => ({ saved: 'ok' }) };
  }
  return { ok: true, json: async () => ({}) };
};

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
const tick = ms => new Promise(r => setTimeout(r, ms));

// Helper: get element via the same mechanism app.js uses
function el(id) { return getElementById(id); }

(async () => {
  await tick(20);
  await sandbox.loadBlockTypes();

  // ---- Test 1: Load diagram B while model_name contains A: save name becomes B ----
  {
    el('model_name').value = 'alpha';
    fetchBehavior.models = ['alpha', 'beta', 'gamma'];
    fetchBehavior.loadOk = true;
    await sandbox.refreshModels();
    el('load_list').value = 'beta';
    await sandbox.loadModel();
    assert.strictEqual(el('model_name').value, 'beta',
      'After loading beta, model_name must be beta (was alpha)');
  }

  // ---- Test 2: A failed load leaves the existing diagram and save name unchanged ----
  {
    el('model_name').value = 'my_diagram';
    const blocksBefore = state.blocks.length;
    fetchBehavior.loadOk = false;
    el('load_list').value = 'nonexistent';
    await sandbox.loadModel();
    assert.strictEqual(el('model_name').value, 'my_diagram',
      'Failed load must not change model_name');
    assert.strictEqual(state.blocks.length, blocksBefore,
      'Failed load must not change blocks');
    fetchBehavior.loadOk = true;
  }

  // ---- Test 3: Save under C with other alphabetically earlier names: dropdown selects C ----
  {
    fetchBehavior.models = ['alpha', 'beta', 'charlie'];
    el('model_name').value = 'charlie';
    await sandbox.saveModel();
    // After save, refreshModels is called with 'charlie' as preferred
    assert.strictEqual(el('load_list').value, 'charlie',
      'After saving charlie, dropdown must select charlie (not alpha)');
  }

  // ---- Test 4: Refresh preserves B when B still exists ----
  {
    fetchBehavior.models = ['alpha', 'beta', 'gamma'];
    el('load_list').value = 'beta';
    await sandbox.refreshModels();
    assert.strictEqual(el('load_list').value, 'beta',
      'Refresh must preserve current selection beta when it still exists');
  }

  // ---- Test 5: Refresh with missing name falls back to first entry ----
  {
    fetchBehavior.models = ['alpha', 'gamma'];
    el('load_list').value = 'beta'; // beta no longer exists
    await sandbox.refreshModels();
    assert.strictEqual(el('load_list').value, 'alpha',
      'When current selection is missing, fall back to first entry');
  }

  // ---- Test 6: Empty model list handled normally ----
  {
    fetchBehavior.models = [];
    el('load_list').value = 'beta';
    await sandbox.refreshModels();
    // With empty list, no option is selected (value is '')
    assert.strictEqual(el('load_list').value, '',
      'Empty model list: no selection');
  }

  // ---- Test 7: A failed refresh preserves the previous dropdown contents/selection ----
  {
    fetchBehavior.models = ['alpha', 'beta', 'gamma'];
    el('load_list').value = 'beta';
    fetchBehavior.modelsError = true;
    await sandbox.refreshModels();
    // The dropdown should still have its previous content (beta selected)
    assert.strictEqual(el('load_list').value, 'beta',
      'Failed refresh must preserve previous dropdown selection');
    fetchBehavior.modelsError = false;
  }

  // ---- Test 8: Loading still clears stale Add Bend/Reset Route and drag state ----
  {
    sandbox.toggleBendEditMode();
    assert.strictEqual(state.bendEditMode, 'edit_bends', 'precondition: edit_bends active');
    state.drag = { kind: 'block', block: {id:'old'}, dx: 0, dy: 0 };
    fetchBehavior.loadOk = true;
    fetchBehavior.models = ['alpha', 'beta'];
    el('load_list').value = 'beta';
    await sandbox.loadModel();
    assert.strictEqual(state.bendEditMode, null, 'Load must reset bendEditMode');
    assert.strictEqual(state.drag, null, 'Load must reset drag');
  }

  console.log('ALL SAVE NAMING REGRESSION TESTS PASSED');
})().catch(err => {
  console.error('TEST FAILED:', err.message);
  process.exit(1);
});
