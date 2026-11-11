'use strict';
// Regression test for canvas panning (drag empty canvas to pan the view).
// Loads the real xcos_mini/web/app.js in a minimal DOM mock and verifies:
//  - panX/panY state variables exist and start at 0
//  - worldPos() correctly subtracts pan offset
//  - draw() uses ctx.translate (static source check)
//  - mousedown on empty space starts pan drag
//  - mousemove during pan updates panX/panY
//  - window-level mouseup stops pan
//  - _panMoved guard prevents click action after pan
//  - pan is reset on fromModelDict (load)
//  - block logical positions are NOT modified by panning
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
const canvasHandlers = {};
const canvasMock = {
  id: 'canvas', width: 800, height: 600, title: '',
  parentElement: { clientWidth: 800, clientHeight: 600 },
  getContext: () => ctxMock,
  addEventListener: (type, fn) => { canvasHandlers[type] = fn; },
  getBoundingClientRect(){ return {left:0, top:0, width:800, height:600}; },
};
const tooltipEl = makeElement('port_tooltip');
tooltipEl.classList.add('hidden');
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
const windowHandlers = {};
const windowMock = {
  addEventListener: (t, fn) => { windowHandlers[t] = fn; },
  open: () => null, innerWidth: 800, innerHeight: 600,
};

const BLOCK_TYPES = [
  { name: 'gain', n_inputs: 1, n_outputs: 1, parameters: {k:1}, state_kind: 'none' },
  { name: 'signal_generator', n_inputs: 0, n_outputs: 1, parameters: {type:'sine'}, state_kind: 'none' },
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

const tick = ms => new Promise(r => setTimeout(r, ms));

function fire(type, x, y, extra) {
  const fn = canvasHandlers[type];
  if (!fn) throw new Error('no canvas handler for ' + type);
  fn(Object.assign({button: 0, clientX: x, clientY: y, preventDefault(){}, target: canvasMock, currentTarget: canvasMock}, extra || {}));
}

(async () => {
  await tick(20);
  await sandbox.loadBlockTypes();

  // Load a model with two blocks and a connection
  const model = {
    blocks: [
      { id: 'b1', type: 'signal_generator', params: {type:'sine'}, x: 100, y: 100 },
      { id: 'b2', type: 'gain', params: {k:2}, x: 300, y: 100 },
    ],
    connections: [
      { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
    ],
  };
  sandbox.fromModelDict(model);

  // 1. panX/panY start at 0
  assert.strictEqual(state.panX, 0, 'panX should start at 0');
  assert.strictEqual(state.panY, 0, 'panY should start at 0');
  assert.strictEqual(state.panDrag, null, 'panDrag should start null');

  // 2. worldPos subtracts pan offset
  state.panX = 50; state.panY = 30;
  const wp = sandbox.worldPos({ clientX: 200, clientY: 150 });
  assert.strictEqual(wp.x, 150, 'worldPos.x should be canvasX - panX');
  assert.strictEqual(wp.y, 120, 'worldPos.y should be canvasY - panY');
  state.panX = 0; state.panY = 0;

  // 3. draw() uses ctx.translate (static source check)
  const src = fs.readFileSync(path.join(__dirname, '..', 'xcos_mini', 'web', 'app.js'), 'utf8');
  assert(src.includes('ctx.translate(state.panX, state.panY)'), 'draw() must use ctx.translate with panX/panY');
  assert(src.includes('ctx.save()'), 'draw() must use ctx.save()');
  assert(src.includes('ctx.restore()'), 'draw() must use ctx.restore()');

  // 4. Mousedown on empty space starts pan
  // Click at (500, 400) which is empty canvas (blocks are at 100,100 and 300,100)
  fire('mousedown', 500, 400);
  assert.ok(state.panDrag !== null, 'mousedown on empty space must start pan drag');
  assert.strictEqual(state.panDrag.startX, 500, 'panDrag.startX should be canvas x');
  assert.strictEqual(state.panDrag.startY, 400, 'panDrag.startY should be canvas y');
  assert.strictEqual(state.panDrag.startPanX, 0, 'panDrag.startPanX should be current panX');
  assert.strictEqual(state.panDrag.startPanY, 0, 'panDrag.startPanY should be current panY');

  // 5. Mousemove during pan updates panX/panY
  fire('mousemove', 530, 420);
  assert.strictEqual(state.panX, 30, 'panX should be startPanX + (530-500) = 30');
  assert.strictEqual(state.panY, 20, 'panY should be startPanY + (420-400) = 20');
  assert.strictEqual(state._panMoved, true, '_panMoved should be true after mousemove');

  // 6. Window-level mouseup stops pan
  assert.ok(windowHandlers['mouseup'], 'window-level mouseup listener must exist');
  windowHandlers['mouseup']({button: 0, clientX: 530, clientY: 420});
  assert.strictEqual(state.panDrag, null, 'panDrag must be null after window mouseup');

  // 7. After window mouseup (outside canvas), _panMoved is reset so next click works
  assert.strictEqual(state._panMoved, false, '_panMoved must be reset by window mouseup (outside canvas)');
  // Next click on empty space should work normally (deselect)
  state.selected = {kind: 'block', id: 'b1'};
  fire('click', 530, 420);
  assert.strictEqual(state.selected, null, 'click after pan+release-outside should work normally (deselect)');

  // 7b. Canvas mouseup (inside canvas) + click: _panMoved guard suppresses click
  // Simulate: mousedown on empty, mousemove, canvas mouseup (inside), then click
  state.selected = {kind: 'block', id: 'b1'};
  fire('mousedown', 500, 400);
  fire('mousemove', 530, 420);
  assert.strictEqual(state._panMoved, true, '_panMoved true after mousemove');
  // Canvas mouseup fires first (inside canvas), clears panDrag but NOT _panMoved
  canvasHandlers['mouseup']({button: 0, clientX: 530, clientY: 420});
  assert.strictEqual(state.panDrag, null, 'panDrag cleared by canvas mouseup');
  assert.strictEqual(state._panMoved, true, '_panMoved still true after canvas mouseup (inside)');
  // Click fires: guard suppresses it
  fire('click', 530, 420);
  assert.strictEqual(state._panMoved, false, '_panMoved reset by click guard');
  assert.ok(state.selected !== null, 'selection preserved: click suppressed by _panMoved guard');

  // 8. Pan is reset on fromModelDict (load)
  state.panX = 100; state.panY = 200;
  sandbox.fromModelDict(model);
  assert.strictEqual(state.panX, 0, 'panX must reset to 0 on load');
  assert.strictEqual(state.panY, 0, 'panY must reset to 0 on load');

  // 9. Block logical positions are NOT modified by panning
  const b1 = state.blocks.find(b => b.id === 'b1');
  const b2 = state.blocks.find(b => b.id === 'b2');
  assert.strictEqual(b1.x, 100, 'b1.x must remain 100');
  assert.strictEqual(b1.y, 100, 'b1.y must remain 100');
  assert.strictEqual(b2.x, 300, 'b2.x must remain 300');
  assert.strictEqual(b2.y, 100, 'b2.y must remain 100');

  // 10. Serialize does NOT include pan offset
  const serialized = sandbox.toModelDict();
  const sb1 = serialized.blocks.find(b => b.id === 'b1');
  assert.strictEqual(sb1.x, 100, 'serialized b1.x must be logical position');
  assert.strictEqual(sb1.y, 100, 'serialized b1.y must be logical position');

  // 11. Mousedown on a block does NOT start pan (starts block drag instead)
  fire('mousedown', 100, 100); // on b1
  assert.strictEqual(state.panDrag, null, 'mousedown on block must NOT start pan');
  assert.ok(state.drag !== null, 'mousedown on block must start block drag');
  assert.strictEqual(state.drag.kind, 'block', 'drag kind should be block');
  state.drag = null; // cleanup

  // 12. Mousedown on empty space after pan still works
  state.panX = 10; state.panY = 20;
  fire('mousedown', 600, 500);
  assert.ok(state.panDrag !== null, 'second pan drag should start');
  assert.strictEqual(state.panDrag.startPanX, 10, 'startPanX should capture current panX');
  assert.strictEqual(state.panDrag.startPanY, 20, 'startPanY should capture current panY');
  fire('mousemove', 610, 510);
  assert.strictEqual(state.panX, 20, 'panX should be 10 + 10 = 20');
  assert.strictEqual(state.panY, 30, 'panY should be 20 + 10 = 30');
  windowHandlers['mouseup']({button: 0, clientX: 610, clientY: 510});
  assert.strictEqual(state.panDrag, null, 'panDrag cleared after second pan');

  console.log('ALL CANVAS PAN TESTS PASSED');
})().catch(err => { console.error('TEST FAILED:', err.message); process.exit(1); });
