// Load production localization before the editor/plot, matching script order in HTML.
const fs=require('fs'),path=require('path'),vm=require('vm');
module.exports=function(sandbox){
  const get=sandbox.document.getElementById;
  sandbox.document.getElementById=function(id){const el=get.call(this,id);if(el&&!el.dataset)el.dataset={};return el;};
  if(!sandbox.document.querySelectorAll)sandbox.document.querySelectorAll=()=>[];
  const create=sandbox.document.createElement;
  if(create)sandbox.document.createElement=function(tag){const el=create.call(this,tag);if(!el.dataset)el.dataset={};return el;};
  for(const file of ['i18n-catalog.js','i18n.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'..','xcos_mini','web',file),'utf8'),sandbox);
};
