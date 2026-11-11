"""Browser editor behavior for the current experiment interface."""
import subprocess
import unittest

from tests.test_unified_library import _app_js, _extract_function


def run_js(script):
    subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)


class CurrentEditorInterfaceTests(unittest.TestCase):
    def test_duplicate_flow_badges_merge_only_within_one_block(self):
        draw = _extract_function(_app_js(), 'drawFlowBadges')
        run_js(r"""
const assert = require('assert');
const state = {activeView:null, flowBadges:{
  a:[{flow_id:'1',state:'waiting'},{flow_id:'1',state:'working'},
     {flow_id:'2',state:'waiting'}],
  b:[{flow_id:'1',state:'waiting'}]}};
let painted=[];
const ctx = {measureText:()=>({width:10}),fill(){},stroke(){},fillText(label){painted.push([label,this.strokeStyle]);}};
function roundRect() {} function flowColor(){return 'red';}
""" + draw + r"""
drawFlowBadges({id:'a',x:0,y:20});
assert.deepStrictEqual(painted, [['1','#fff'],['2','#17202a']]);
painted=[];
drawFlowBadges({id:'b',x:0,y:20});
assert.deepStrictEqual(painted, [['1','#17202a']]);
""")

    def test_flow_events_update_immediately_and_close(self):
        js = _app_js()
        funcs = '\n'.join(_extract_function(js, name) for name in ('stopFlowAnimation', 'startFlowAnimation'))
        run_js(r"""
const assert = require('assert');
const state = {flowBadges:{}};
let lastStream, draws = [];
class EventSource { constructor(url) { this.url=url; lastStream=this; } close() { this.closed=true; } }
function draw() { draws.push(JSON.stringify(state.flowBadges)); }
""" + funcs + r"""
startFlowAnimation('run');
lastStream.onmessage({data:JSON.stringify({blocks:{b:[{flow_id:'1'}]},complete:false})});
assert.deepStrictEqual(state.flowBadges, {b:[{flow_id:'1'}]});
lastStream.onmessage({data:JSON.stringify({blocks:{},complete:true})});
assert.strictEqual(lastStream.closed, true);
assert.deepStrictEqual(state.flowBadges, {});
assert.strictEqual(state.flowRunId, null);
""")

    def test_experiment_and_subsystem_roundtrip(self):
        js = _app_js()
        funcs = '\n'.join(_extract_function(js, name) for name in (
            'containerForView', 'enterSubsystem', 'exitSubsystem',
            'serializeBlocks', 'serializeConnections', 'deserializeBlocks', 'deserializeConnections'))
        run_js(r"""
const assert = require('assert');
const experiment = {id:'b1',type:'typed_experiment',params:{},x:10,y:20};
const state = {blocks:[experiment],connections:[],rootBlocks:null,rootConnections:null,activeView:null};
function setStatus() {} function updateModeButtons() {} function updateBackButton() {}
function draw() {} function renderLibraryTree() {}
""" + funcs + r"""
enterSubsystem('b1');
assert.deepStrictEqual(state.blocks.map(b => b.id), ['P1','P2','P3','J']);
state.blocks.push({id:'b2',type:'subsystem',params:{},x:100,y:100});
enterSubsystem('b2');
assert.strictEqual(state.activeView, 'b1/b2');
assert.deepStrictEqual(state.blocks.map(b => b.id), ['In1','Out1']);
exitSubsystem(); exitSubsystem();
const saved = serializeBlocks(state.blocks);
const loaded = deserializeBlocks(saved);
assert.deepStrictEqual(loaded[0].internal.blocks.map(b => b.id), ['P1','P2','P3','J','b2']);
assert.deepStrictEqual(loaded[0].internal.blocks[4].internal.blocks.map(b => b.id), ['In1','Out1']);
assert.strictEqual(loaded[0].internal.blocks[4].internal.connections.length, 1);
""")

    def test_run_from_experiment_uses_full_scheme(self):
        js = _app_js()
        run_sim = 'async ' + _extract_function(js, 'runSim')
        run_js(r"""
const assert = require('assert');
const exp = {id:'b1',type:'typed_experiment',internal:{blocks:[{id:'P1',type:'experiment_input'}]}};
const root = {blocks:[exp,{id:'start',type:'starter'}],connections:[]};
const state = {blocks:exp.internal.blocks,rootBlocks:root.blocks,activeView:'b1',graphWindows:{}};
const crypto = {randomUUID:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'};
let request, error;
function toActiveDiagramDict() { return {blocks:state.blocks,connections:[]}; }
function toModelDict() { return root; }
async function sessionForRun() { return 'session'; }
async function api(path, opts) { request = {path,body:JSON.parse(opts.body)}; return {run_id:'run',results:{}}; }
function setStatus(kind, key, detail) { if (kind === 'error') error = detail; }
function startFlowAnimation() {} function stopFlowAnimation() {} function updateGraphWindows() {} function updateOutputWindows() {}
function draw() {} function renderRunSummary() {}
""" + run_sim + r"""
(async () => { await runSim(); assert.strictEqual(error, undefined);
assert.strictEqual(request.path, '/api/simulate');
assert.deepStrictEqual(request.body.model, root);
assert.strictEqual(request.body.model.blocks[0].type, 'typed_experiment');
})().catch(err => { console.error(err); process.exitCode = 1; });
""")
