'use strict';
// Behavioral regression: root/visible diagram synchronization after Clear and
// after individual block/wire deletion. Drives the PRODUCTION event handlers and
// serialization (fromModelDict/toModelDict, clear click, placement click,
// mousedown/mouseup connection, deleteBlock, deleteConnection, enter/exit
// subsystem, runSim, saveModel) inside a Node vm sandbox. Emits each scenario's
// Run and Save model JSON on a SYNC_RESULT_JSON line so the Python test can pass
// it through production model construction + Engine.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

function makeElement(id) {
  return {
    id, dataset: {}, textContent: '', innerHTML: '', value: '', className: '', style: {},
    classList: {
      _set: new Set(),
      add(c){ this._set.add(c); }, remove(c){ this._set.delete(c); },
      contains(c){ return this._set.has(c); },
      toggle(c, force){ if (force === undefined) { this._set.has(c) ? this._set.delete(c) : this._set.add(c); } else if (force) this._set.add(c); else this._set.delete(c); },
    },
    appendChild(c){ return c; }, _ls: {}, addEventListener(t, fn){ (this._ls[t] = this._ls[t] || []).push(fn); }, removeEventListener(){}, click(){ (this._ls["click"] || []).forEach(fn => fn({ preventDefault(){} })); },
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
  addEventListener: (t, fn) => { canvasHandlers[t] = fn; },
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
const windowMock = { addEventListener: (t, fn) => { windowHandlers[t] = fn; }, open: () => null, innerWidth: 800, innerHeight: 600 };

const BLOCK_TYPES = [
  { name: 'constant', n_inputs: 0, n_outputs: 1, parameters: {value:1}, state_kind: 'none' },
  { name: 'gain', n_inputs: 1, n_outputs: 1, parameters: {k:1}, state_kind: 'none' },
  { name: 'graph_display', n_inputs: 1, n_outputs: 0, parameters: {}, state_kind: 'none' },
  { name: 'subsystem', n_inputs: 1, n_outputs: 1, parameters: {}, state_kind: 'none' },
];

// Capture the bodies of Run and Save requests the production handlers would send.
const simulateBodies = [];
const saveBodies = [];
const fetchMock = async (p, opts) => {
  const ok = () => ({ ok: true, status: 200, json: async () => ({}) });
  if (p === '/api/blocks') return { ok: true, status: 200, json: async () => ({ blocks: BLOCK_TYPES }) };
  if (p === '/api/library') return { ok: true, status: 200, json: async () => ({ tree: [], load_errors: [] }) };
  if (p === '/api/models') return { ok: true, status: 200, json: async () => ({ models: [] }) };
  if (p === '/api/simulate') {
    let body = {};
    try { body = JSON.parse(opts.body); } catch (e) { throw new Error('simulate body not JSON'); }
    simulateBodies.push(body);
    return { ok: true, status: 200, json: async () => ({ ok: true, results: {}, n_steps: 100 }) };
  }
  if (p === '/api/save') {
    let body = {};
    try { body = JSON.parse(opts.body); } catch (e) { throw new Error('save body not JSON'); }
    saveBodies.push(body);
    return { ok: true, status: 200, json: async () => ({ saved: body.name }) };
  }
  if (p.startsWith('/api/load')) return { ok: true, status: 200, json: async () => ({ name: 'x', model: { blocks: [], connections: [] } }) };
  return ok();
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
const state = vm.runInContext('state', sandbox);
const tick = ms => new Promise(r => setTimeout(r, ms));

function fire(type, x, y) {
  const fn = canvasHandlers[type];
  if (!fn) throw new Error('no canvas handler for ' + type);
  fn({ button: 0, clientX: x, clientY: y, preventDefault(){}, target: canvasMock, currentTarget: canvasMock });
}
// Geometry mirrors app.js: BLOCK_W=132, TOP_PAD=18, PORT_SPACING=22.
function outPortOf(id, j) { const b = state.blocks.find(x => x.id === id); return { x: b.x + 132, y: b.y + 18 + (j + 0.5) * 22 }; }
function inPortOf(id, i) { const b = state.blocks.find(x => x.id === id); return { x: b.x, y: b.y + 18 + (i + 0.5) * 22 }; }

async function place(type, px, py) {
  state.placingType = type;
  fire('click', px, py);
  return state.blocks[state.blocks.length - 1];
}
function connect(fromId, toId, fromPort, toPort) {
  const p1 = outPortOf(fromId, fromPort || 0);
  const p2 = inPortOf(toId, toPort || 0);
  fire('mousedown', p1.x, p1.y);
  fire('mouseup', p2.x, p2.y);
}
async function captureRun() {
  simulateBodies.length = 0;
  getElementById('t_end').value = '1'; getElementById('h').value = '0.01'; getElementById('method').value = 'rk4';
  await sandbox.runSim();
  assert.strictEqual(simulateBodies.length, 1, 'runSim must send one /api/simulate request');
  return simulateBodies[0].model;
}
async function captureSave(name) {
  saveBodies.length = 0;
  getElementById('model_name').value = name;
  await sandbox.saveModel();
  assert.strictEqual(saveBodies.length, 1, 'saveModel must send one /api/save request');
  return saveBodies[0].model;
}
function blockIds(model) { return model.blocks.map(b => String(b.id)).sort(); }
function connSet(model) {
  return model.connections.map(c => c.from + ':' + c.from_port + '->' + c.to + ':' + c.to_port).sort();
}
function gdBlocks(model) { return model.blocks.filter(b => b.type === 'graph_display').map(b => String(b.id)); }

(async () => {
  await tick(20);
  await sandbox.loadBlockTypes();
  const out = { scenarios: {} };

  // ---- S1: Load -> Clear -> rebuild -> Run & Save ----
  {
    sandbox.fromModelDict({
      blocks: [
        { id: 'b1', type: 'constant', params: {value: 9}, x: 100, y: 100 },
        { id: 'b2', type: 'gain', params: {k: 3}, x: 400, y: 200 },
        { id: 'b3', type: 'graph_display', params: {}, x: 700, y: 150 },
      ],
      connections: [ { from: 'b1', from_port: 0, to: 'b2', to_port: 0 }, { from: 'b2', from_port: 0, to: 'b3', to_port: 0 } ],
    });
    assert.strictEqual(state.blocks.length, 3, 'precondition: loaded 3 blocks');
    // Clear (confirm auto-true)
    getElementById('clear').click();
    assert.strictEqual(state.blocks.length, 0, 'REGRESSION S1: blocks must be empty after Clear');
    assert.strictEqual(state.rootBlocks.length, 0, 'REGRESSION S1: rootBlocks must be empty after Clear');
    assert.strictEqual(state.rootBlocks, state.blocks, 'REGRESSION S1: rootBlocks and blocks must share one array');
    assert.strictEqual(state.rootConnections, state.connections, 'REGRESSION S1: rootConnections and connections must share one array');
    // Rebuild constant(1) -> graph_display
    await place('constant', 200, 200);
    await place('graph_display', 600, 200);
    const c = state.blocks.find(b => b.type === 'constant');
    const g = state.blocks.find(b => b.type === 'graph_display');
    c.params.value = 1;
    connect(c.id, g.id, 0, 0);
    assert.strictEqual(state.connections.length, 1, 'REGRESSION S1: new wire must exist');
    const run = await captureRun();
    const save = await captureSave('s1_disposable');
    for (const m of [run, save]) {
      assert.deepStrictEqual(blockIds(m), [c.id, g.id].sort(), 'S1: model must contain exactly the new blocks');
      assert.strictEqual(connSet(m).length, 1, 'S1: model must contain exactly the new wire');
      assert.strictEqual(connSet(m)[0], c.id + ':0->' + g.id + ':0', 'S1: wire must be c->g');
    }
    out.scenarios.s1_clear_rebuild = { run, save, runnable: true };
  }

  // ---- S2: Load -> delete all blocks individually -> rebuild -> Run & Save ----
  {
    sandbox.fromModelDict({
      blocks: [
        { id: 'b1', type: 'constant', params: {value: 5}, x: 100, y: 100 },
        { id: 'b2', type: 'graph_display', params: {}, x: 500, y: 150 },
      ],
      connections: [ { from: 'b1', from_port: 0, to: 'b2', to_port: 0 } ],
    });
    assert.strictEqual(state.blocks.length, 2, 'precondition S2: loaded 2 blocks');
    const ids = state.blocks.map(b => b.id).slice();
    for (const id of ids) sandbox.deleteBlock(id);
    assert.strictEqual(state.blocks.length, 0, 'REGRESSION S2: blocks must be empty after deleting all');
    assert.strictEqual(state.connections.length, 0, 'REGRESSION S2: incident wire must be removed');
    assert.strictEqual(state.rootConnections.length, 0, 'REGRESSION S2: rootConnections must be empty (stale-ref bug)');
    await place('constant', 200, 200);
    await place('graph_display', 600, 200);
    const c = state.blocks.find(b => b.type === 'constant');
    const g = state.blocks.find(b => b.type === 'graph_display');
    c.params.value = 1;
    connect(c.id, g.id, 0, 0);
    const run = await captureRun();
    const save = await captureSave('s2_disposable');
    for (const m of [run, save]) {
      assert.deepStrictEqual(blockIds(m), [c.id, g.id].sort(), 'S2: model must contain exactly the new blocks, no deleted ids');
      assert.deepStrictEqual(connSet(m), [c.id + ':0->' + g.id + ':0'], 'S2: model must contain only the new wire, no b1->b2');
      assert.ok(!m.connections.some(cc => String(cc.from) === 'b1' || String(cc.to) === 'b1'), 'S2: no reference to deleted block b1');
      assert.ok(!m.connections.some(cc => String(cc.from) === 'b2' || String(cc.to) === 'b2'), 'S2: no reference to deleted block b2');
    }
    out.scenarios.s2_delete_all_rebuild = { run, save, runnable: true };
  }

  // ---- S3: Delete one connected block, preserve unrelated wire ----
  {
    sandbox.fromModelDict({
      blocks: [
        { id: 'b1', type: 'constant', params: {value: 1}, x: 50, y: 50 },
        { id: 'b2', type: 'gain', params: {k: 1}, x: 300, y: 50 },
        { id: 'b3', type: 'graph_display', params: {}, x: 550, y: 50 },
        { id: 'b4', type: 'constant', params: {value: 1}, x: 50, y: 300 },
        { id: 'b5', type: 'graph_display', params: {}, x: 550, y: 300 },
      ],
      connections: [
        { from: 'b1', from_port: 0, to: 'b2', to_port: 0 },
        { from: 'b2', from_port: 0, to: 'b3', to_port: 0 },
        { from: 'b4', from_port: 0, to: 'b5', to_port: 0 },
      ],
    });
    assert.strictEqual(state.connections.length, 3, 'precondition S3: 3 wires');
    sandbox.deleteBlock('b3'); // delete the consumer in the b1->b2->b3 chain
    assert.strictEqual(state.blocks.length, 4, 'S3: one block removed');
    assert.ok(!state.blocks.some(b => b.id === 'b3'), 'S3: b3 removed');
    const model = sandbox.toModelDict();
    assert.deepStrictEqual(blockIds(model), ['b1', 'b2', 'b4', 'b5'], 'S3: b1,b2,b4,b5 preserved');
    assert.deepStrictEqual(connSet(model), ['b1:0->b2:0', 'b4:0->b5:0'], 'S3: b1->b2 and b4->b5 preserved; b2->b3 removed');
    assert.ok(!model.connections.some(c => String(c.to) === 'b3'), 'S3: no wire to deleted b3');
    // Runnable: b4(1)->b5 => 1.0 ; b1(1)->b2(gain1) valid, b2 output unused.
    out.scenarios.s3_delete_one_block = { model, runnable: true, expect_1: ['b5'] };
  }

  // ---- S4: Delete an old wire, create a replacement, navigate out/back ----
  {
    // Root: b1 constant(1) -> sub1(identity) -> b2 graph_display.
    const sub1Internal = {
      blocks: [ { id: 'in1', type: 'in1_terminal', params: {}, x: 50, y: 50 }, { id: 'out1', type: 'out1_terminal', params: {}, x: 400, y: 50 } ],
      connections: [ { from: 'in1', from_port: 0, to: 'out1', to_port: 0 } ],
    };
    sandbox.fromModelDict({
      blocks: [
        { id: 'b1', type: 'constant', params: {value: 1}, x: 50, y: 50 },
        { id: 'sub1', type: 'subsystem', params: {}, x: 300, y: 50, internal: sub1Internal },
        { id: 'b2', type: 'graph_display', params: {}, x: 550, y: 50 },
      ],
      connections: [ { from: 'b1', from_port: 0, to: 'sub1', to_port: 0 }, { from: 'sub1', from_port: 0, to: 'b2', to_port: 0 } ],
    });
    assert.strictEqual(state.connections.length, 2, 'precondition S4: 2 wires');
    // Delete the old wire sub1->b2 (index 1).
    sandbox.deleteConnection(1);
    assert.strictEqual(state.connections.length, 1, 'S4: old wire removed');
    assert.deepStrictEqual(connSet(sandbox.toModelDict()), ['b1:0->sub1:0'], 'S4: only b1->sub1 remains');
    // Create a replacement: sub1 -> b3 gain(1) -> b2.
    await place('gain', 480, 250);
    const b3 = state.blocks.find(b => b.type === 'gain');
    b3.params.k = 1;
    connect('sub1', b3.id, 0, 0);
    connect(b3.id, 'b2', 0, 0);
    assert.strictEqual(state.connections.length, 3, 'S4: b1->sub1, sub1->b3, b3->b2');
    // Navigate out/back.
    sandbox.enterSubsystem('sub1');
    assert.strictEqual(state.activeView, 'sub1', 'S4: inside sub1');
    sandbox.exitSubsystem();
    assert.strictEqual(state.activeView, null, 'S4: back at root');
    assert.strictEqual(state.connections.length, 3, 'S4: wires survive navigation (stale-ref bug)');
    const run = await captureRun();
    const save = await captureSave('s4_disposable');
    for (const m of [run, save]) {
      assert.ok(m.blocks.some(b => b.id === b3.id), 'S4: replacement gain present');
      assert.ok(m.connections.some(c => String(c.from) === 'sub1' && String(c.to) === b3.id), 'S4: sub1->b3 present');
      assert.ok(m.connections.some(c => String(c.from) === b3.id && String(c.to) === 'b2'), 'S4: b3->b2 present');
      assert.ok(!m.connections.some(c => String(c.from) === 'sub1' && String(c.to) === 'b2'), 'S4: deleted old wire sub1->b2 absent');
    }
    out.scenarios.s4_wire_replace_navigate = { run, save, runnable: true, expect_1: ['b2'] };
  }

  // ---- S5: Two independent Subsystems; edit one, preserve other + root ----
  {
    const mkSub = () => ({
      blocks: [ { id: 'in1', type: 'in1_terminal', params: {}, x: 50, y: 50 }, { id: 'out1', type: 'out1_terminal', params: {}, x: 400, y: 50 } ],
      connections: [ { from: 'in1', from_port: 0, to: 'out1', to_port: 0 } ],
    });
    const sub1 = mkSub(); const sub2 = mkSub();
    sandbox.fromModelDict({
      blocks: [
        { id: 'c1', type: 'constant', params: {value: 1}, x: 30, y: 100 },
        { id: 'sub1', type: 'subsystem', params: {}, x: 250, y: 50, internal: sub1 },
        { id: 'sub2', type: 'subsystem', params: {}, x: 250, y: 300, internal: sub2 },
        { id: 'gd', type: 'graph_display', params: {}, x: 520, y: 50 },
        { id: 'gd2', type: 'graph_display', params: {}, x: 520, y: 300 },
      ],
      connections: [
        { from: 'c1', from_port: 0, to: 'sub1', to_port: 0 },
        { from: 'sub1', from_port: 0, to: 'gd', to_port: 0 },
        { from: 'c1', from_port: 0, to: 'sub2', to_port: 0 },
        { from: 'sub2', from_port: 0, to: 'gd2', to_port: 0 },
      ],
    });
    // Enter sub1 and edit its internal: in1 -> g(1) -> out1.
    sandbox.enterSubsystem('sub1');
    assert.strictEqual(state.activeView, 'sub1', 'S5: inside sub1');
    assert.strictEqual(state.blocks.length, 2, 'S5: sub1 internal has in1,out1');
    await place('gain', 200, 50);
    const g = state.blocks.find(b => b.type === 'gain');
    g.params.k = 1;
    // Rewire: remove in1->out1, add in1->g and g->out1.
    const oldIdx = state.connections.findIndex(c => c.from === 'in1' && c.to === 'out1');
    sandbox.deleteConnection(oldIdx);
    connect('in1', g.id, 0, 0);
    connect(g.id, 'out1', 0, 0);
    // While inside sub1, Run/Save must still serialize the FULL root.
    const run = await captureRun();
    const save = await captureSave('s5_disposable');
    for (const m of [run, save]) {
      const ids = blockIds(m);
      for (const req of ['c1', 'sub1', 'sub2', 'gd', 'gd2']) assert.ok(ids.includes(req), 'S5: root block ' + req + ' present in full-root serialization');
      const s1 = m.blocks.find(b => b.id === 'sub1');
      const s2 = m.blocks.find(b => b.id === 'sub2');
      assert.ok(s1.internal && s1.internal.blocks.some(b => b.id === g.id), 'S5: sub1 internal contains the new gain');
      assert.ok(s1.internal.connections.some(c => String(c.from) === 'in1' && String(c.to) === g.id), 'S5: in1->g in sub1');
      assert.ok(s1.internal.connections.some(c => String(c.from) === g.id && String(c.to) === 'out1'), 'S5: g->out1 in sub1');
      assert.ok(!s1.internal.connections.some(c => String(c.from) === 'in1' && String(c.to) === 'out1'), 'S5: old in1->out1 removed in sub1');
      // Other child preserved.
      assert.strictEqual(s2.internal.blocks.length, 2, 'S5: sub2 internal still in1,out1 (other child preserved)');
      assert.deepStrictEqual(s2.internal.connections.map(c => c.from + '->' + c.to), ['in1->out1'], 'S5: sub2 internal unchanged');
    }
    // Exit; verify sub2 unchanged and root intact.
    sandbox.exitSubsystem();
    assert.strictEqual(state.activeView, null, 'S5: back at root');
    assert.strictEqual(state.blocks.length, 5, 'S5: root still has 5 blocks');
    out.scenarios.s5_two_subsystems = { run, save, runnable: true, expect_1: ['gd', 'gd2'] };
  }

  // ---- S6: Clear inside a Subsystem -> place a new parent diagram ----
  {
    const sub1 = {
      blocks: [ { id: 'in1', type: 'in1_terminal', params: {}, x: 50, y: 50 }, { id: 'out1', type: 'out1_terminal', params: {}, x: 400, y: 50 } ],
      connections: [ { from: 'in1', from_port: 0, to: 'out1', to_port: 0 } ],
    };
    sandbox.fromModelDict({
      blocks: [
        { id: 'c1', type: 'constant', params: {value: 1}, x: 30, y: 100 },
        { id: 'sub1', type: 'subsystem', params: {}, x: 250, y: 50, internal: sub1 },
        { id: 'gd', type: 'graph_display', params: {}, x: 520, y: 50 },
      ],
      connections: [ { from: 'c1', from_port: 0, to: 'sub1', to_port: 0 }, { from: 'sub1', from_port: 0, to: 'gd', to_port: 0 } ],
    });
    sandbox.enterSubsystem('sub1');
    assert.strictEqual(state.activeView, 'sub1', 'S6: inside sub1 before Clear');
    getElementById('clear').click();
    assert.strictEqual(state.activeView, null, 'S6: Clear returns to parent view');
    assert.strictEqual(state.blocks.length, 0, 'REGRESSION S6: root cleared (blocks empty)');
    assert.strictEqual(state.rootBlocks.length, 0, 'REGRESSION S6: rootBlocks empty');
    assert.strictEqual(state.rootBlocks, state.blocks, 'REGRESSION S6: shared array after Clear-inside-subsystem');
    await place('constant', 200, 200);
    await place('graph_display', 600, 200);
    const c = state.blocks.find(b => b.type === 'constant');
    const g = state.blocks.find(b => b.type === 'graph_display');
    c.params.value = 1;
    connect(c.id, g.id, 0, 0);
    const run = await captureRun();
    const save = await captureSave('s6_disposable');
    for (const m of [run, save]) {
      assert.deepStrictEqual(blockIds(m), [c.id, g.id].sort(), 'S6: only the new parent diagram blocks');
      assert.deepStrictEqual(connSet(m), [c.id + ':0->' + g.id + ':0'], 'S6: only the new wire');
    }
    out.scenarios.s6_clear_inside_sub = { run, save, runnable: true };
  }

  process.stdout.write('SYNC_RESULT_JSON:' + JSON.stringify(out) + '\n');
  console.log('ALL SYNC FIX REGRESSION TESTS PASSED');
})().catch(err => {
  console.error('SYNC FIX TEST FAILED: ' + (err && err.stack ? err.stack : err));
  process.exit(1);
});
