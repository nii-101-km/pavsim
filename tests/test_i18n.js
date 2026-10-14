'use strict';
// Behavioral localization checks run the production editor in a DOM harness.
// Python supplies the REAL registered library, models and API diagnostics.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const payload=JSON.parse(fs.readFileSync(0,'utf8'));
const web='xcos_mini/web/';
function makeEditor(storage={},denyStorage=false) {
 const nodes=new Set(),elements={},events={},drawn=[],requests=[];
 function element(tag,id='') {
  let text='',children=[];
  const classes=new Set();
  const el={tagName:tag.toUpperCase(),dataset:{},style:{},value:'',checked:false,parentElement:null,handlers:{},
   classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c),toggle(c,force){force=force??!classes.has(c);force?classes.add(c):classes.delete(c);}},
   appendChild(c){children.push(c);c.parentElement=el;return c;},
   addEventListener(k,f){el.handlers[k]=f;},
   getBoundingClientRect:()=>({left:0,top:0,width:900,height:700}),clientWidth:900,clientHeight:700,
   closest(){return {style:{}};},
  };
  let eid=id;
  Object.defineProperties(el,{
   id:{get:()=>eid,set:v=>{eid=v;elements[v]=el;}},
   textContent:{get:()=>text+children.map(c=>c.textContent||'').join(''),set:v=>{text=String(v);children.forEach(c=>c.parentElement=null);children=[];}},
   innerHTML:{get:()=>'',set:()=>{text='';children.forEach(c=>c.parentElement=null);children=[];}},
   children:{get:()=>children},
  });
  nodes.add(el);if(id)elements[id]=el;return el;
 }
 const body=element('body'),html=element('html');
 const attrsToDataset=attrs=>Object.fromEntries([...attrs.matchAll(/data-([\w-]+)="([^"]*)"/g)].map(m=>[m[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),m[2]]));
 for(const match of fs.readFileSync(web+'index.html','utf8').matchAll(/<(\w+)([^>]*\bid="([^"]+)"[^>]*)>/g)){
  const el=element(match[1],match[3]);el.dataset=attrsToDataset(match[2]);body.appendChild(el);
 }
 const ctx=new Proxy({fillText:s=>drawn.push(String(s))},{get:(o,k)=>k in o?o[k]:()=>{}});
 elements.canvas.getContext=()=>ctx;elements.canvas.parentElement=elements.canvas_wrap;
 ['t_end','h','method'].forEach((id,i)=>elements[id].value=['1','.01','rk4'][i]);
 elements.dialog_overlay.classList.add('hidden');
 function query(selector){
  const field=/^\[data-([\w-]+)\]$/.exec(selector);
  if(!field)return [];
  const key=field[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
  return [...nodes].filter(el=>el.parentElement&&key in el.dataset);
 }
 const doc={body,documentElement:html,activeElement:null,addEventListener(){},getElementById:id=>elements[id],createElement:tag=>element(tag),createTextNode:text=>({textContent:text}),querySelectorAll:query};
 let saved=null;
 const result={ok:true,run_id:'r1',results:{graph:{t:[0,1],y:[0,1]}},n_steps:1};
 const sandbox={document:doc,window:{addEventListener:(k,f)=>events[k]=f,open:()=>null},console,
  localStorage:{getItem:k=>{if(denyStorage)throw Error('blocked');return storage[k]??null;},setItem:(k,v)=>{if(denyStorage)throw Error('blocked');storage[k]=v;}},
  confirm:()=>true,URLSearchParams,
  fetch:async(path,options)=>{
   if(options)requests.push({path,body:JSON.parse(options.body)});
   let data=path==='/api/blocks'?{blocks:payload.blocks}:path==='/api/library'?{tree:payload.tree}:path==='/api/models'?{models:['test']}:
    path==='/api/save'?(saved=JSON.parse(options.body).model,{}):path.startsWith('/api/load')?{model:saved}:path==='/api/simulate'?result:{};
   return {ok:true,json:async()=>data};
  }};
 vm.createContext(sandbox);
 require('./load_i18n')(sandbox);
 vm.runInContext(fs.readFileSync(web+'app.js','utf8'),sandbox);
 return {sandbox,elements,events,requests,drawn,storage,get saved(){return saved;},state:vm.runInContext('state',sandbox)};
}
const clone=o=>JSON.parse(JSON.stringify(o));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const editor=makeEditor(),{sandbox:s,elements:els,state}=editor;
 await tick();await tick();
 const I=s.I18n;
 const name=process.argv[2];
 if(name==='default'){
  assert.strictEqual(I.language,'en');assert.strictEqual(els.run.textContent,'▶ Run');
  I.setLanguage('ru');assert.strictEqual(els.run.textContent,'▶ Запуск');assert.strictEqual(editor.storage['pavsim.language'],'ru');
  const reopened=makeEditor(editor.storage);await tick();assert.strictEqual(reopened.sandbox.I18n.language,'ru');assert.strictEqual(reopened.elements.run.textContent,'▶ Запуск');
  I.setLanguage('unsupported');assert.strictEqual(I.language,'en');
 } else if(name==='fallback'){
  I.setLanguage('ru');delete s.PAVSIM_CATALOG.ru['ui.save'];assert.strictEqual(I.t('ui.save'),'Save');
  assert.strictEqual(I.t('custom.unknown'),'custom.unknown');
  const noStorage=makeEditor({},true);assert.strictEqual(noStorage.sandbox.I18n.language,'en');noStorage.sandbox.I18n.setLanguage('ru');assert.strictEqual(noStorage.sandbox.I18n.language,'ru');
 } else if(name==='metadata'){
  for(const language of ['en','ru']){
   I.setLanguage(language);
   for(const bt of payload.blocks){
    assert.strictEqual(I.blockName(bt),s.PAVSIM_CATALOG[language]['block.'+bt.name+'.name']);
    assert(I.blockDescription(bt));
    for(const key of Object.keys(bt.parameters))assert.notStrictEqual(I.parameter(key),'param.'+key);
   }
  }
  assert.strictEqual(I.blockName({name:'custom',display_name:'My block'}),'My block');
 } else if(name==='state'){
  for(const model of payload.models){
   s.fromModelDict(model);
   const before=JSON.stringify(s.toModelDict());
   const blocks=state.blocks,connections=state.connections;
   state.selected={kind:'block',id:state.blocks[0].id};state.pendingConn={from:'source',fromPort:0};state.placingType='gain';state._mouse={x:1,y:2};
   state.lastResults={sentinel:[1,2,3]};state.lastRunId='existing';
   const selected=state.selected,pending=state.pendingConn,results=state.lastResults;
   I.setLanguage('ru');I.setLanguage('en');
   assert.strictEqual(JSON.stringify(s.toModelDict()),before);assert.strictEqual(state.blocks,blocks);assert.strictEqual(state.connections,connections);
   assert.strictEqual(state.selected,selected);assert.strictEqual(state.pendingConn,pending);assert.strictEqual(state.lastResults,results);assert.strictEqual(state.lastRunId,'existing');assert.strictEqual(state.placingType,'gain');
  }
 } else if(name==='roundtrip'){
  const models=[];
  for(const model of payload.models){
   s.fromModelDict(model);I.setLanguage('en');const before=clone(s.toModelDict());
   I.setLanguage('ru');els.model_name.value='test';await s.saveModel();
   els.load_list.value='test';await s.loadModel();I.setLanguage('en');
   assert.deepStrictEqual(clone(s.toModelDict()),before);assert.deepStrictEqual(editor.saved,before);
   models.push(before);
  }
  console.log('MODELS:'+JSON.stringify(models));
 } else if(name==='dialog'){
  s.fromModelDict({blocks:[{id:'c',type:'constant',params:{value:1}},{id:'g',type:'graph_series2',params:{label:'График 2 серий'}}],connections:[]});
  s.openDialog(state.blocks[0]);els.dlg_value.value='7.25';I.setLanguage('ru');assert.strictEqual(els.dlg_value.value,'7.25');assert.match(els.dialog_title.textContent,/Константа/);
  I.setLanguage('en');assert.match(els.dialog_title.textContent,/Constant/);s.applyDialog();assert.strictEqual(state.blocks[0].params.value,7.25);
  s.openDialog(state.blocks[1]);assert.strictEqual(els.dlg_label.value,'2-series graph');I.setLanguage('ru');assert.strictEqual(els.dlg_label.value,'График 2 серий');I.setLanguage('en');s.applyDialog();assert.strictEqual(state.blocks[1].params.label,'График 2 серий');
  s.openDialog(state.blocks[1]);els.dlg_label.value='My custom label';I.setLanguage('ru');assert.strictEqual(els.dlg_label.value,'My custom label');s.applyDialog();assert.strictEqual(state.blocks[1].params.label,'My custom label');
 } else if(name==='dynamic'){
  for(const lang of ['ru','en']){
   I.setLanguage(lang);await s.loadLibrary();
   for(const bt of payload.blocks){s.openDialog({id:'x',type:bt.name,params:clone(bt.parameters)});assert(els.dialog_title.textContent.includes(I.blockName(bt)));s.closeDialog();}
   s.setStatus('error','status.sim_failed',{error:"Block 'x' (first_order) parameters: 'tau' must be positive"});
   assert(els.statusbar.textContent.includes(lang==='ru'?'положительным':'positive'));
  }
  I.setLanguage('ru');s.setStatus('error','status.sim_failed',{error:'Неизвестный алгоритм оптимизации'});I.setLanguage('en');assert(els.statusbar.textContent.includes('Unknown optimization algorithm'));
 } else if(name==='errors'){
  for(const source of payload.diagnostics){
   const sample=source.replace(/\{\d+\}/g,'sample');
   I.setLanguage('en');const en=I.message(sample);I.setLanguage('ru');const ru=I.message(sample);
   assert.notStrictEqual(en,ru,source);assert(!/[а-яё]/i.test(en),'English diagnostic: '+en);
  }
  assert.strictEqual(I.message("Input port 0 of block 'Эксперимент' has multiple connections; only one source per input is supported.").includes('Эксперимент'),true,'machine/user identifiers must be preserved');
  I.setLanguage('en');assert.strictEqual(I.message("Block 'b' (first_order) parameters: 'tau' must be positive"),"Block 'b' (first_order) parameters: 'tau' must be positive");
 } else if(name==='boundary'){
  s.fromModelDict({blocks:[{id:'s',type:'subsystem',params:{},internal:{blocks:[{id:'In1',type:'in1_terminal',params:{},x:0,y:0}],connections:[]}}],connections:[]});s.enterSubsystem('s');
  const before=JSON.stringify(s.toModelDict());
  for(const lang of ['en','ru']){I.setLanguage(lang);s.deleteBlock('In1');assert.strictEqual(JSON.stringify(s.toModelDict()),before);assert(els.statusbar.textContent.includes(lang==='ru'?'нельзя удалить':'cannot be deleted'));}
 } else throw Error('Unknown scenario '+name);
 console.log('I18N '+name+' PASSED');
})().catch(e=>{console.error(e);process.exit(1);});
