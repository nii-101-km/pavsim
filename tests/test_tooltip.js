'use strict';
// Focused regression tests for connector tooltips (HTML tooltip div).
// Loads the real xcos_mini/web/app.js in a minimal DOM mock and verifies that
// hovering each input/output connector shows the correct tooltip text, for
// single-port, multi-port, input-only, output-only and filesystem-loaded blocks,
// and that it stays correct after diagram reload and library refresh.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

function makeElement(id) {
  const classes = new Set();
  return {
    id, dataset: {}, textContent: '', innerHTML: '', value: '', className: '', style: {},
    classList: {
      add(c){ classes.add(c); }, remove(c){ classes.delete(c); },
      contains(c){ return classes.has(c); }, toggle(c){ classes.has(c) ? classes.delete(c) : classes.add(c); },
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
const canvasMock = {
  id: 'canvas', width: 800, height: 600, title: '',
  parentElement: { clientWidth: 800, clientHeight: 600 },
  getContext: () => ctxMock, addEventListener(){},
  getBoundingClientRect(){ return {left:0, top:0, width:800, height:600}; },
};
// Tooltip element with working classList tracking
const tooltipEl = makeElement('port_tooltip');
tooltipEl.classList.add('hidden'); // starts hidden
const elements = { 'port_tooltip': tooltipEl };
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
const windowMock = { addEventListener(){}, open: () => null, innerWidth: 800, innerHeight: 600 };

// Simulated block library (includes a "filesystem-loaded" custom block).
const BLOCK_TYPES = [
  { name: 'gain', n_inputs: 1, n_outputs: 1, parameters: {k:1}, state_kind: 'none' },
  { name: 'addition', n_inputs: 2, n_outputs: 1, parameters: {}, state_kind: 'none' },
  { name: 'signal_generator', n_inputs: 0, n_outputs: 1, parameters: {type:'sine'}, state_kind: 'none' },
  { name: 'graph_display', n_inputs: 1, n_outputs: 0, parameters: {}, state_kind: 'none' },
  { name: 'custom_fs_block', n_inputs: 3, n_outputs: 2, parameters: {}, state_kind: 'none' },
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

const tick = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  await tick(20);                 // let init() settle
  await sandbox.loadBlockTypes(); // ensure state.blockTypes populated

  const model = {
    blocks: [
      { id: 'b1', type: 'gain', params: {k:1}, x: 100, y: 100 },
      { id: 'b2', type: 'addition', params: {}, x: 300, y: 100 },
      { id: 'b3', type: 'signal_generator', params: {type:'sine'}, x: 100, y: 300 },
      { id: 'b4', type: 'graph_display', params: {}, x: 300, y: 300 },
      { id: 'b5', type: 'custom_fs_block', params: {}, x: 500, y: 100 },
    ],
    connections: [],
  };
  sandbox.fromModelDict(model);

  const b1 = { id:'b1', type:'gain', params:{k:1}, x:100, y:100 };
  const b2 = { id:'b2', type:'addition', params:{}, x:300, y:100 };
  const b3 = { id:'b3', type:'signal_generator', params:{type:'sine'}, x:100, y:300 };
  const b4 = { id:'b4', type:'graph_display', params:{}, x:300, y:300 };
  const b5 = { id:'b5', type:'custom_fs_block', params:{}, x:500, y:100 };

  function check(block, kind, index, expected) {
    const p = (kind === 'in') ? sandbox.inputPort(block, index) : sandbox.outputPort(block, index);
    sandbox.updateCanvasTooltip(p.x, p.y);
    assert.strictEqual(tooltipEl.textContent, expected,
      `expected "${expected}" at ${kind}${index+1} of ${block.id}, got "${tooltipEl.textContent}"`);
    assert.strictEqual(tooltipEl.classList.contains('hidden'), false,
      `tooltip should be visible at ${kind}${index+1} of ${block.id}`);
  }

  // Single-port block (gain): 1 in, 1 out
  check(b1, 'in', 0, 'Input 1');
  check(b1, 'out', 0, 'Output 1');
  // Multi-port block (addition): 2 in, 1 out
  check(b2, 'in', 0, 'Input 1');
  check(b2, 'in', 1, 'Input 2');
  check(b2, 'out', 0, 'Output 1');
  // Output-only block (signal_generator): 0 in, 1 out
  check(b3, 'out', 0, 'Output 1');
  // Input-only block (graph_display): 1 in, 0 out
  check(b4, 'in', 0, 'Input 1');
  // Filesystem-loaded block (custom_fs_block): 3 in, 2 out
  check(b5, 'in', 0, 'Input 1');
  check(b5, 'in', 1, 'Input 2');
  check(b5, 'in', 2, 'Input 3');
  check(b5, 'out', 0, 'Output 1');
  check(b5, 'out', 1, 'Output 2');
  // Off-port location -> tooltip hidden
  sandbox.updateCanvasTooltip(5, 5);
  assert.strictEqual(tooltipEl.classList.contains('hidden'), true,
    'expected tooltip hidden off-port');
  // portTooltip direct
  assert.strictEqual(sandbox.portTooltip({kind:'in', index:0}), 'Input 1');
  assert.strictEqual(sandbox.portTooltip({kind:'out', index:2}), 'Output 3');

  // Diagram reload: re-load the same model, tooltips still correct.
  sandbox.fromModelDict(model);
  check(b1, 'in', 0, 'Input 1');
  check(b2, 'in', 1, 'Input 2');
  check(b5, 'out', 1, 'Output 2');

  // Library refresh: reload block types, tooltips still correct.
  await sandbox.loadBlockTypes();
  check(b1, 'out', 0, 'Output 1');
  check(b5, 'in', 2, 'Input 3');

  // Repeated hover: tooltip must re-appear reliably after being hidden.
  sandbox.updateCanvasTooltip(5, 5); // hide
  assert.strictEqual(tooltipEl.classList.contains('hidden'), true);
  const p1 = sandbox.inputPort(b1, 0);
  sandbox.updateCanvasTooltip(p1.x, p1.y); // re-show
  assert.strictEqual(tooltipEl.textContent, 'Input 1');
  assert.strictEqual(tooltipEl.classList.contains('hidden'), false);

  // Hover after block movement: move block (via model reload), tooltip still correct at new position.
  const modelMoved = {
    blocks: [
      { id: 'b1', type: 'gain', params: {k:1}, x: 200, y: 200 },
      { id: 'b2', type: 'addition', params: {}, x: 300, y: 100 },
    ],
    connections: [],
  };
  sandbox.fromModelDict(modelMoved);
  const b1m = { id:'b1', type:'gain', params:{k:1}, x:200, y:200 };
  const p1m = sandbox.inputPort(b1m, 0);
  sandbox.updateCanvasTooltip(p1m.x, p1m.y);
  assert.strictEqual(tooltipEl.textContent, 'Input 1');
  assert.strictEqual(tooltipEl.classList.contains('hidden'), false);

  console.log('ALL TOOLTIP TESTS PASSED');
})().catch(e => { console.error('TEST FAILED:', e && e.message); process.exit(1); });
