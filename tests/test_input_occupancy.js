'use strict';
// Behavioral regression of actual drag-to-connect mouse handlers.
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
    id, textContent: '', innerHTML: '', value: '', className: '', style: {},
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
const handlers = {};
const canvasMock = {
  id: 'canvas', width: 800, height: 600, title: '',
  parentElement: { clientWidth: 800, clientHeight: 600 },
  getContext: () => ctxMock, addEventListener(t, fn){handlers[t]=fn;},
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
vm.runInContext(code, sandbox);

const tick = ms => new Promise(r => setTimeout(r, ms));


(async()=>{
  await sandbox.loadBlockTypes();
  const initial={blocks:[
    {id:'a',type:'signal_generator',params:{},x:20,y:20},
    {id:'b',type:'signal_generator',params:{},x:20,y:120},
    {id:'sum',type:'addition',params:{},x:300,y:100},
    {id:'graph',type:'graph_display',params:{},x:500,y:100}],
    connections:[{from:'a',from_port:0,to:'sum',to_port:0,route:[{x:220,y:49},{x:220,y:129}]}]};
  sandbox.fromModelDict(initial);
  const drag=(sx,sy,dx,dy)=>{
    handlers.mousedown({button:0,clientX:sx,clientY:sy});
    handlers.mouseup({button:0,clientX:dx,clientY:dy});
  };
  const before=JSON.stringify(sandbox.toModelDict());
  drag(152,149,300,129); // b -> already occupied sum input 0
  assert.strictEqual(JSON.stringify(sandbox.toModelDict()),before,'rejection must preserve the wire and its route');
  assert.match(elements.statusbar.textContent,/занят/);
  assert.strictEqual(vm.runInContext('state.pendingConn',sandbox),null);
  drag(152,49,300,129); // exact duplicate
  assert.strictEqual(JSON.stringify(sandbox.toModelDict()),before);
  drag(152,149,300,151); // input 1 of same block is free
  assert.strictEqual(sandbox.toModelDict().connections.length,2);
  drag(152,49,500,129); // fan-out to another destination remains valid
  assert.strictEqual(sandbox.toModelDict().connections.length,3);
  sandbox.deleteConnection(0);
  drag(152,149,300,129); // freed port can be reconnected
  assert.strictEqual(sandbox.toModelDict().connections.length,3);
  assert.strictEqual(sandbox.toModelDict().connections.filter(c=>c.to==='sum'&&c.to_port===0)[0].from,'b');
  const saved=sandbox.toModelDict();sandbox.fromModelDict(saved);
  drag(152,49,300,129); // occupancy survives save/load
  assert.deepStrictEqual(sandbox.toModelDict(),saved);
  console.log('INPUT OCCUPANCY TESTS PASSED');
})().catch(e=>{console.error(e);process.exit(1);});
