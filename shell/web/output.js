const t=I18n.t;
const query=new URLSearchParams(location.search);
let output=null, error=null, retries=0;
function show(){
  I18n.apply();
  document.getElementById('title').textContent=t('output.title')+' · '+(query.get('block')||'');
  const info=document.getElementById('info');
  if(error){info.textContent=error;return;}
  if(!query.get('run')){info.textContent=t('plot.run_first');return;}
  if(!output){info.textContent=t('plot.loading');return;}
  info.textContent=t('output.count',{n:output.data.entries.length})+(output.complete?'':' · '+t('output.running'));
  const body=document.getElementById('entries');body.replaceChildren();
  for(const entry of output.data.entries){
    const row=document.createElement('tr');
    for(const value of [entry.trial,entry.flow_id||'',entry.values.p1,entry.values.p2,entry.values.p3,entry.J]){
      const cell=document.createElement('td');
      cell.textContent=typeof value==='number'?Number(value.toPrecision(6)).toString():String(value);
      row.appendChild(cell);
    }
    body.appendChild(row);
  }
}
document.getElementById('language').addEventListener('change',event=>I18n.setLanguage(event.target.value));
I18n.onChange(show);show();
async function refresh(){
  if(!query.get('run'))return;
  try{
    const response=await fetch('/api/output?run='+encodeURIComponent(query.get('run'))+'&block='+encodeURIComponent(query.get('block')||''));
    if(response.status===404&&query.get('live')==='1'&&retries++<60){setTimeout(refresh,500);return;}
    const data=await response.json();if(!response.ok)throw new Error(data.error);
    output=data;error=null;show();if(!data.complete)setTimeout(refresh,500);
  }catch(exc){error=I18n.message(exc.message);show();}
}
refresh();
