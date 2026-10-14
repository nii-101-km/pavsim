const canvas=document.getElementById('plot'),ctx=canvas.getContext('2d'),tip=document.getElementById('tip');
let packet=null,pixels=[];
const colors=['#e6194b','#2f6fb3','#3cb44b','#b05ac4'];
function range(values){let lo=Infinity,hi=-Infinity;values.forEach(v=>{lo=Math.min(lo,v);hi=Math.max(hi,v);});if(!Number.isFinite(lo))return [0,1];if(lo===hi){lo-=1;hi+=1;}return [lo,hi];}
function axisRange(text,fallback){
 if(!String(text||'').trim())return fallback;
 const parts=String(text).split(':').map(v=>Number(v.trim().replace(',','.')));
 if(parts.length!==2||!parts.every(Number.isFinite)||parts[1]<=parts[0])throw new Error('Диапазон оси: минимум:максимум, например 0:5');
 return parts;
}
function pointLabel(index){
 const step=packet.config.axis==='trial'?packet.data.t[index]:index+1;
 const data=packet.data.outputs||[];
 return String(step)+(packet.config.kind==='xy_score'&&packet.config.score_connected!==false&&data[2]?' | '+Number(data[2][index]).toPrecision(5):'');
}
function draw(){
 if(!packet)return;const d=packet.data,cfg=packet.config,p=cfg.params||{},channels=d.outputs||[d.y];
 const xy=cfg.kind==='xy'||cfg.kind==='xy_score';const xs=xy?channels[0]:d.t,ys=xy?[channels[1]]:channels;
 if(!xs||!xs.length)return;
 canvas.width=canvas.clientWidth;canvas.height=canvas.clientHeight;const W=canvas.width,H=canvas.height;
 ctx.clearRect(0,0,W,H);const pad={l:65,r:20,t:35,b:40};
 const [xmin,xmax]=xy?axisRange(p.x_range,range(xs)):range(xs),[ymin,ymax]=xy?axisRange(p.y_range,range(ys.flat())):range(ys.flat());
 const sx=v=>pad.l+(v-xmin)/(xmax-xmin)*(W-pad.l-pad.r),sy=v=>H-pad.b-(v-ymin)/(ymax-ymin)*(H-pad.t-pad.b);
 ctx.font='11px system-ui';ctx.lineWidth=1;
 for(let i=0;i<=5;i++){const xv=xmin+(xmax-xmin)*i/5,yv=ymin+(ymax-ymin)*i/5;ctx.strokeStyle='#e2e9ef';ctx.beginPath();ctx.moveTo(sx(xv),pad.t);ctx.lineTo(sx(xv),H-pad.b);ctx.moveTo(pad.l,sy(yv));ctx.lineTo(W-pad.r,sy(yv));ctx.stroke();ctx.fillStyle='#526477';ctx.textAlign='center';ctx.fillText(xv.toPrecision(4),sx(xv),H-20);ctx.textAlign='right';ctx.fillText(yv.toPrecision(4),pad.l-7,sy(yv)+4);}
 const labels=cfg.labels||[];ctx.textAlign='left';ctx.fillStyle='#526477';ctx.fillText(xy?(labels[0]||'x'):(cfg.axis||'t'),pad.l,H-3);ctx.fillText(xy?(labels[1]||'y'):'y',5,20);
 pixels=[];
 ys.forEach((values,series)=>{
   ctx.lineWidth=1.8;ctx.strokeStyle=xy?'#2f6fb3':colors[series%colors.length];
   ctx.save();ctx.beginPath();ctx.rect(pad.l,pad.t,W-pad.l-pad.r,H-pad.t-pad.b);ctx.clip();
   for(let i=0;i<values.length;i++){
     const x=sx(xs[i]),y=sy(values[i]);
     if(xy&&x>=pad.l&&x<=W-pad.r&&y>=pad.t&&y<=H-pad.b)pixels.push({x,y,index:i});
     if(i){ctx.beginPath();ctx.moveTo(sx(xs[i-1]),sy(values[i-1]));ctx.lineTo(x,y);ctx.stroke();}
     if(xy||values.length===1){ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.arc(x,y,xy?3:4,0,Math.PI*2);ctx.fill();}
   }
   ctx.restore();
   if(!xy){ctx.fillStyle=colors[series%colors.length];ctx.fillText(labels[series]||'y'+(series+1),pad.l+series*140,20);}
 });
 if(cfg.kind==='xy_score'){
   // Show readable labels; coincident/dense points remain inspectable on hover.
   const placed=[];ctx.fillStyle='#213247';ctx.textAlign='left';ctx.textBaseline='bottom';
   pixels.slice().reverse().forEach(point=>{
     const text=pointLabel(point.index),width=ctx.measureText(text).width;
     const x=Math.max(pad.l,Math.min(W-pad.r-width,point.x+7)),y=Math.max(pad.t+13,point.y-5);
     const box={x,y:y-13,w:width+4,h:15};
     if(placed.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y))return;
     placed.push(box);ctx.fillText(text,x,y);
   });
   ctx.textBaseline='alphabetic';
 }
}
canvas.addEventListener('mousemove',e=>{
 if(!packet||!pixels.length)return;const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;let best=null,dist=100;
 pixels.forEach(point=>{const d=(point.x-x)**2+(point.y-y)**2;if(d<dist){dist=d;best=point;}});
 if(!best){tip.style.display='none';return;}
 const data=packet.data.outputs,i=best.index;
 tip.textContent=pointLabel(i)+' · x='+data[0][i].toPrecision(6)+', y='+data[1][i].toPrecision(6);
 tip.style.left=Math.max(0,Math.min(window.innerWidth-320,e.clientX+12))+'px';tip.style.top=Math.min(window.innerHeight-45,e.clientY+12)+'px';tip.style.display='block';
});
canvas.addEventListener('mouseleave',()=>tip.style.display='none');window.addEventListener('resize',draw);
(async()=>{try{const q=new URLSearchParams(location.search);if(!q.get('run'))throw new Error('Сначала выполните Run.');const r=await fetch('/api/plot?run='+encodeURIComponent(q.get('run'))+'&block='+encodeURIComponent(q.get('block')));packet=await r.json();if(!r.ok)throw new Error(packet.error);document.title=packet.config.params.label||q.get('block');document.getElementById('title').textContent=document.title;document.getElementById('info').textContent=packet.data.t.length+' точек · '+(packet.config.axis==='trial'?'пробы оптимизатора':'модельное время')+(packet.config.kind==='xy_score'?' · подпись: шаг | ошибка':'');draw();}catch(e){document.getElementById('info').textContent=e.message;}})();
