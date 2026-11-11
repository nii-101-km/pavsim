'use strict';
const t = I18n.t;
let statusPresentation = null;
const state = {
  blocks: [], connections: [], blockTypes: {}, libraryTree: null, _libSeq: 0,
  selected: null, placingType: null, pendingConn: null, drag: null,
  panX: 0, panY: 0, panDrag: null, _panMoved: false,
  bendEditMode: null,
  nextId: 1, lastResults: null, graphWindows: {}, outputWindows: {},
  flowBadges: {}, flowRunId: null,
  // Subsystem view system
  rootBlocks: null,       // parent diagram blocks (source of truth)
  rootConnections: null,  // parent diagram connections (source of truth)
  activeView: null,       // null = parent view, string = subsystem block ID (internal view)
};
const COLORS = ['#e6194b','#3cb44b','#4363d8','#f58231','#911eb4','#008080'];
const BLOCK_W = 132, PORT_SPACING = 22, TOP_PAD = 18, BOTTOM_PAD = 12;
function instancePorts(b) {
  const bt = state.blockTypes[b.type] || {};
  let nIn = bt.n_inputs || 0, nOut = bt.n_outputs || 0;
  let inLabels = bt.input_labels || [], outLabels = bt.output_labels || [];
  return {nIn, nOut, inLabels, outLabels};
}
function blockDims(typeOrBlock) {
  const b = typeof typeOrBlock === 'string' ? {type: typeOrBlock, params: {}} : typeOrBlock;
  const {nIn, nOut} = instancePorts(b);
  const n = Math.max(nIn, nOut, 1);
  return {W: BLOCK_W, H: TOP_PAD + n * PORT_SPACING + BOTTOM_PAD};
}
function inputPort(b, i) { const {H} = blockDims(b); return {x: b.x, y: b.y + TOP_PAD + (i+0.5)*PORT_SPACING}; }
function outputPort(b, j) { return {x: b.x + BLOCK_W, y: b.y + TOP_PAD + (j+0.5)*PORT_SPACING}; }
function blockById(id) { return state.blocks.find(b => b.id === id); }
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
function resizeCanvas() {
  const wrap = canvas.parentElement;
  canvas.width = wrap.clientWidth; canvas.height = wrap.clientHeight; draw();
}
window.addEventListener('resize', resizeCanvas);
// The toolbar can wrap when entering a nested view without a window resize.
// Keep the drawing buffer in sync with the actual canvas container.
if (typeof ResizeObserver !== 'undefined') {
  new ResizeObserver(resizeCanvas).observe(document.getElementById('canvas_wrap'));
}
function canvasPos(ev) {
  const r = canvas.getBoundingClientRect();
  return {x: (ev.clientX - r.left) * (r.width ? canvas.width / r.width : 1),
          y: (ev.clientY - r.top) * (r.height ? canvas.height / r.height : 1)};
}
function worldPos(ev) { const p = canvasPos(ev); return {x: p.x - state.panX, y: p.y - state.panY}; }
function setStatus(kind, key, values = {}) {
  statusPresentation = {kind, key, values};
  const el = document.getElementById('statusbar');
  const localized = {...values};
  if ('loadErrors' in localized) localized.error=localized.loadErrors.map(e=>e[0]+': '+I18n.message(e[1])).join('; ');
  if ('blockType' in localized) localized.name=I18n.blockName(state.blockTypes[localized.blockType] || {name:localized.blockType});
  if ('error' in localized) localized.error = I18n.message(localized.error);
  el.textContent = t(key, localized); el.className = (kind === 'error') ? 'error' : '';
}
function roundRect(c, x, y, w, h, r) {
  c.beginPath(); c.moveTo(x+r,y); c.arcTo(x+w,y,x+w,y+h,r); c.arcTo(x+w,y+h,x,y+h,r);
  c.arcTo(x,y+h,x,y,r); c.arcTo(x,y,x+w,y,r); c.closePath();
}
function drawConnection(pts, sel, dashed) {
  if (!pts || pts.length < 2) return;
  ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
  ctx.strokeStyle = sel?'#e6194b':'#5a7184'; ctx.lineWidth = sel?3:2;
  ctx.setLineDash(dashed?[6,4]:[]); ctx.stroke(); ctx.setLineDash([]);
  const p2 = pts[pts.length-1], pp = pts[pts.length-2];
  let ax = p2.x-pp.x, ay = p2.y-pp.y;
  const len = Math.hypot(ax, ay) || 1; ax/=len; ay/=len;
  const bx = -ay, by = ax;
  ctx.fillStyle = sel?'#e6194b':'#5a7184';
  ctx.beginPath(); ctx.moveTo(p2.x,p2.y);
  ctx.lineTo(p2.x-ax*9-bx*5, p2.y-ay*9-by*5);
  ctx.lineTo(p2.x-ax*9+bx*5, p2.y-ay*9+by*5);
  ctx.closePath(); ctx.fill();
}

// The executor traverses a block's outgoing connections in their stored order,
// irrespective of which output port each connection uses.
function outgoingConnectionOrders(connections) {
  const totals = new Map(), positions = new Map();
  connections.forEach(c => totals.set(c.from, (totals.get(c.from) || 0) + 1));
  return connections.map(c => {
    const n = (positions.get(c.from) || 0) + 1;
    positions.set(c.from, n);
    return totals.get(c.from) > 1 ? n : null;
  });
}
function drawConnectionOrder(pts, order) {
  if (!order || !pts || pts.length < 2) return;
  const end = pts[pts.length - 1];
  let prev = pts[pts.length - 2], i = pts.length - 2;
  while (i > 0 && Math.hypot(end.x - prev.x, end.y - prev.y) < 1) prev = pts[--i];
  const dx = end.x - prev.x, dy = end.y - prev.y, len = Math.hypot(dx, dy) || 1;
  const x = end.x - dx / len * Math.min(24, len / 2);
  const y = end.y - dy / len * Math.min(24, len / 2);
  ctx.save();
  ctx.font = 'bold 10px system-ui,sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  const label = String(order), width = Math.max(16, ctx.measureText(label).width + 6);
  ctx.fillStyle = '#fff'; ctx.strokeStyle = '#5a7184'; ctx.lineWidth = 1;
  roundRect(ctx, x - width / 2, y - 8, width, 16, 3); ctx.fill(); ctx.stroke();
  ctx.fillStyle = '#263b4b'; ctx.fillText(label, x, y);
  ctx.restore();
}

// ---- orthogonal routing ----------------------------------------------------
const ROUTE_EPS = 1e-6;
function sameX(a, b) { return Math.abs(a.x - b.x) < ROUTE_EPS; }
function sameY(a, b) { return Math.abs(a.y - b.y) < ROUTE_EPS; }

// Minimal-bend orthogonal route between two ports. Returns bend points only.
function defaultRoute(p1, p2, offset) {
  offset = offset || 0;
  const ox = offset * 14;
  if (sameX(p1, p2)) return [];
  if (sameY(p1, p2)) {
    if (p2.x > p1.x) return [];
    const ex = p1.x + 40, dy = p1.y + 40;
    return [{x: ex, y: p1.y}, {x: ex, y: dy}, {x: p2.x, y: dy}];
  }
  if (p2.x > p1.x) {
    const mid = (p1.x + p2.x) / 2 + ox;
    return [{x: mid, y: p1.y}, {x: mid, y: p2.y}];
  }
  const ex = p1.x + 40 + ox;
  return [{x: ex, y: p1.y}, {x: ex, y: p2.y}];
}

// Index of this connection among those sharing the same (from, fromPort).
function fanOutOffset(c) {
  let n = 0;
  for (const o of state.connections) {
    if (o === c) break;
    if (o.from === c.from && o.fromPort === c.fromPort) n++;
  }
  return n;
}

// Full polyline for a connection: [sourcePort, ...bends, destPort].
function routePoints(c) {
  const from = blockById(c.from), to = blockById(c.to);
  if (!from || !to) return null;
  const p1 = outputPort(from, c.fromPort), p2 = inputPort(to, c.toPort);
  let bends;
  if (c.route && c.route.length) bends = c.route;
  else bends = defaultRoute(p1, p2, fanOutOffset(c));
  return [p1].concat(bends).concat([p2]);
}

// Materialize the (possibly default) route into c.route so it can be edited.
function materializeRoute(c) {
  if (c.route && c.route.length) return;
  const pts = routePoints(c);
  if (pts && pts.length > 2) c.route = pts.slice(1, -1).map(p => ({x: p.x, y: p.y}));
  else c.route = [];
}

// Remove zero-length and collinear points; store the cleaned bends in c.route.
function normalizeRoute(c) {
  const pts = routePoints(c);
  if (!pts || pts.length < 2) { c.route = []; return; }
  const cleaned = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    const p = pts[i];
    const last = cleaned[cleaned.length - 1];
    if (last.x === p.x && last.y === p.y) continue;
    if (cleaned.length >= 2) {
      const prev = cleaned[cleaned.length - 2];
      if ((sameX(prev, last) && sameX(last, p)) || (sameY(prev, last) && sameY(last, p))) {
        cleaned.pop();
      }
    }
    cleaned.push(p);
  }
  c.route = cleaned.slice(1, -1).map(p => ({x: p.x, y: p.y}));
}

// Channel helpers: a maximal run of consecutive bends sharing one coordinate
// is a "channel"; it can slide perpendicular to itself only when both bounding
// segments are parallel to it (i.e. the channel is not locked to a port).
function routeEndpoints(c) {
  const from = blockById(c.from), to = blockById(c.to);
  if (!from || !to) return null;
  return {p1: outputPort(from, c.fromPort), p2: inputPort(to, c.toPort)};
}

// Block moved by (ddx, ddy): adjust only the bend adjacent to the moved port,
// and only the coordinate constrained to that port. All other user-placed
// bends stay put. Must be called BEFORE the block position is updated so the
// old port positions are available.
function adjustRouteForBlockMove(c, blockId, ddx, ddy) {
  if (!c.route || !c.route.length) return;
  const ep = routeEndpoints(c);
  if (!ep) return;
  if (c.from === blockId) {
    const b = c.route[0];
    if (sameY(b, ep.p1)) b.y += ddy;        // first segment horizontal
    else if (sameX(b, ep.p1)) b.x += ddx;   // first segment vertical
  } else if (c.to === blockId) {
    const b = c.route[c.route.length - 1];
    if (sameY(b, ep.p2)) b.y += ddy;        // last segment horizontal
    else if (sameX(b, ep.p2)) b.x += ddx;   // last segment vertical
  }
}
function xChannelFree(r, lo, hi, p1, p2) {
  const before = (lo > 0) ? r[lo-1] : p1;
  if (!sameY(before, r[lo])) return false;
  const after = (hi < r.length-1) ? r[hi+1] : p2;
  return sameY(r[hi], after);
}
function yChannelFree(r, lo, hi, p1, p2) {
  const before = (lo > 0) ? r[lo-1] : p1;
  if (!sameX(before, r[lo])) return false;
  const after = (hi < r.length-1) ? r[hi+1] : p2;
  return sameX(r[hi], after);
}

// Drag bend i by (dx, dy): slide the free channel(s) through the bend.
function dragBend(c, i, dx, dy) {
  const r = c.route;
  if (!r || i < 0 || i >= r.length) return;
  const ep = routeEndpoints(c);
  if (!ep) return;
  if (dx) {
    let lo = i, hi = i;
    while (lo > 0 && sameX(r[lo-1], r[i])) lo--;
    while (hi < r.length-1 && sameX(r[hi+1], r[i])) hi++;
    if (xChannelFree(r, lo, hi, ep.p1, ep.p2))
      for (let k = lo; k <= hi; k++) r[k].x += dx;
  }
  if (dy) {
    let lo = i, hi = i;
    while (lo > 0 && sameY(r[lo-1], r[i])) lo--;
    while (hi < r.length-1 && sameY(r[hi+1], r[i])) hi++;
    if (yChannelFree(r, lo, hi, ep.p1, ep.p2))
      for (let k = lo; k <= hi; k++) r[k].y += dy;
  }
}

// Drag segment segIdx (between pts[segIdx] and pts[segIdx+1]) by (dx, dy).
// Segments touching a port are locked; middle segments slide their channel.
function dragSegment(c, segIdx, dx, dy) {
  const r = c.route;
  if (!r) return;
  if (segIdx === 0 || segIdx === r.length) return;
  const a = r[segIdx - 1], b = r[segIdx];
  const ep = routeEndpoints(c);
  if (!ep) return;
  if (sameX(a, b)) {
    if (!dx) return;
    let lo = segIdx - 1, hi = segIdx;
    while (lo > 0 && sameX(r[lo-1], a)) lo--;
    while (hi < r.length-1 && sameX(r[hi+1], b)) hi++;
    if (xChannelFree(r, lo, hi, ep.p1, ep.p2))
      for (let k = lo; k <= hi; k++) r[k].x += dx;
  } else {
    if (!dy) return;
    let lo = segIdx - 1, hi = segIdx;
    while (lo > 0 && sameY(r[lo-1], a)) lo--;
    while (hi < r.length-1 && sameY(r[hi+1], b)) hi++;
    if (yChannelFree(r, lo, hi, ep.p1, ep.p2))
      for (let k = lo; k <= hi; k++) r[k].y += dy;
  }
}

// ---- bend editing mode ----------------------------------------------------
const DETOUR_OFFSET = 20, DETOUR_WIDTH = 20;

function insertDetour(c, segIdx, clickX, clickY) {
  const pts = routePoints(c);
  if (!pts) return -1;
  const a = pts[segIdx], b = pts[segIdx + 1];
  let newPoints;
  if (sameY(a, b)) {
    const cy = a.y, cx = clickX;
    newPoints = [
      {x: cx, y: cy},
      {x: cx, y: cy - DETOUR_OFFSET},
      {x: cx + DETOUR_WIDTH, y: cy - DETOUR_OFFSET},
      {x: cx + DETOUR_WIDTH, y: cy}
    ];
  } else {
    const cx = a.x, cy = clickY;
    newPoints = [
      {x: cx, y: cy},
      {x: cx + DETOUR_OFFSET, y: cy},
      {x: cx + DETOUR_OFFSET, y: cy + DETOUR_WIDTH},
      {x: cx, y: cy + DETOUR_WIDTH}
    ];
  }
  if (!c.route) c.route = [];
  const insertIdx = segIdx;
  c.route.splice(insertIdx, 0, ...newPoints);
  return insertIdx + 1;
}

function toggleBendEditMode() {
  if (state.bendEditMode === 'edit_bends') {
    state.bendEditMode = null;
  } else {
    state.bendEditMode = 'edit_bends';
  }
  updateModeButtons();
  if (state.bendEditMode === 'edit_bends') {
    setStatus('info', 'status.add_bend');
  } else if (state.bendEditMode === null) {
    setStatus('info', 'status.bend_off');
  }
  draw();
}

function toggleResetRouteMode() {
  if (state.bendEditMode === 'reset_route') {
    state.bendEditMode = null;
  } else {
    state.bendEditMode = 'reset_route';
  }
  updateModeButtons();
  if (state.bendEditMode === 'reset_route') {
    setStatus('info', 'status.reset_route');
  } else if (state.bendEditMode === null) {
    setStatus('info', 'status.bend_off');
  }
  draw();
}

function updateModeButtons() {
  const eb = document.getElementById('edit_bends');
  const db = document.getElementById('reset_route');
  if (eb) eb.classList.toggle('active', state.bendEditMode === 'edit_bends');
  if (db) db.classList.toggle('active', state.bendEditMode === 'reset_route');
}

// Distance from point (x,y) to an axis-aligned segment a-b.
function distToSeg(x, y, a, b) {
  if (sameX(a, b)) {
    const cy = Math.max(Math.min(a.y, b.y), Math.min(Math.max(a.y, b.y), y));
    return Math.hypot(a.x - x, cy - y);
  }
  const cx = Math.max(Math.min(a.x, b.x), Math.min(Math.max(a.x, b.x), x));
  return Math.hypot(cx - x, a.y - y);
}

// Hit-test a connection's route. Returns {type, index} or null.
function hitRoute(c, x, y, tol) {
  tol = tol || 7;
  const pts = routePoints(c);
  if (!pts) return null;
  const nBends = pts.length - 2;
  for (let i = 0; i < nBends; i++) {
    const p = pts[i + 1];
    if (Math.hypot(p.x - x, p.y - y) < tol) return {type: 'bend', index: i};
  }
  for (let s = 0; s < pts.length - 1; s++) {
    if (distToSeg(x, y, pts[s], pts[s+1]) < tol) return {type: 'segment', index: s};
  }
  return null;
}
function drawBlock(b) {
  const {W,H} = blockDims(b.type);
  const bt = state.blockTypes[b.type] || {};
  const sel = state.selected && state.selected.kind==='block' && state.selected.id===b.id;
  const stateful = bt.state_kind && bt.state_kind!=='none';
  const isGraph = b.type.startsWith('graph_');
  ctx.fillStyle = isGraph?'#fdeef4':(stateful?'#e8f0fb':'#ffffff');
  ctx.strokeStyle = sel?'#e6194b':(isGraph?'#c2185b':(stateful?'#2f6fb3':'#8496a8'));
  ctx.lineWidth = sel?3:1.5;
  roundRect(ctx, b.x, b.y, W, H, 8); ctx.fill(); ctx.stroke();
  ctx.fillStyle='#1c2733'; ctx.font='600 13px system-ui,sans-serif';
  ctx.textAlign='center'; ctx.textBaseline='middle';
  ctx.fillText((b.id+' · '+I18n.blockName({...bt,name:b.type})).slice(0,22), b.x+W/2, b.y+12);
  if (isGraph) { ctx.font='10px system-ui,sans-serif'; ctx.fillStyle='#c2185b'; ctx.fillText(t('ui.plot'), b.x+W/2, b.y+H-8); }
  else if (stateful) { ctx.font='10px system-ui,sans-serif'; ctx.fillStyle='#2f6fb3'; ctx.fillText(t('ui.'+bt.state_kind), b.x+W/2, b.y+H-8); }
  const nIn=bt.n_inputs||0, nOut=bt.n_outputs||0;
  for (let i=0;i<nIn;i++){const p=inputPort(b,i);ctx.beginPath();ctx.arc(p.x,p.y,5,0,Math.PI*2);ctx.fillStyle='#3cb44b';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();}
  for (let j=0;j<nOut;j++){const p=outputPort(b,j);ctx.beginPath();ctx.arc(p.x,p.y,5,0,Math.PI*2);ctx.fillStyle='#e6194b';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();}
  if (bt.input_labels) {
    ctx.font='11px system-ui,sans-serif'; ctx.fillStyle='#1c2733'; ctx.textAlign='left';
    bt.input_labels.forEach((label,i)=>{const p=inputPort(b,i);ctx.fillText(I18n.port(label),p.x+9,p.y);});
    ctx.textAlign='center';
  }
  if (bt.output_labels) {
    ctx.font='11px system-ui,sans-serif'; ctx.fillStyle='#1c2733'; ctx.textAlign='right';
    bt.output_labels.forEach((label,i)=>{const p=outputPort(b,i);ctx.fillText(I18n.port(label),p.x-9,p.y);});
    ctx.textAlign='center';
  }
}
function flowColor(id) {
  const parts=String(id).split('.').map(Number), root=parts[0]||1;
  const hue=((root*137.508)%360+360)%360;
  const shade=parts.slice(1).reduce((value,part)=>value*17+part,0);
  return `hsl(${hue.toFixed(1)}, 65%, ${38+(shade%4)*7}%)`;
}
function drawFlowBadges(b) {
  const key=(state.activeView?state.activeView+'/':'')+String(b.id);
  const badges=new Map();
  for (const badge of state.flowBadges[key]||[]) {
    const id=String(badge.flow_id), current=badges.get(id);
    if (!current || (current.state==='waiting' && badge.state!=='waiting')) badges.set(id,badge);
  }
  let x=b.x, y=b.y-15;
  ctx.font='bold 10px system-ui,sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
  badges.forEach(badge=>{
    const label=String(badge.flow_id), width=Math.max(22,ctx.measureText(label).width+12);
    ctx.fillStyle=flowColor(label);ctx.strokeStyle=badge.state==='waiting'?'#17202a':'#fff';ctx.lineWidth=badge.state==='waiting'?2:1;
    roundRect(ctx,x,y-10,width,20,10);ctx.fill();ctx.stroke();
    ctx.fillStyle='#fff';ctx.fillText(label,x+width/2,y);
    x+=width+3;
  });
}
function draw() {
  updateOwnershipBadge();
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.save();
  ctx.translate(state.panX, state.panY);
  // Grid in world coordinates covering visible viewport
  const vx0 = -state.panX, vy0 = -state.panY;
  const vx1 = vx0 + canvas.width, vy1 = vy0 + canvas.height;
  ctx.strokeStyle='#eef2f6'; ctx.lineWidth=1;
  for(let x=Math.floor(vx0/24)*24; x<=vx1; x+=24){ctx.beginPath();ctx.moveTo(x,vy0);ctx.lineTo(x,vy1);ctx.stroke();}
  for(let y=Math.floor(vy0/24)*24; y<=vy1; y+=24){ctx.beginPath();ctx.moveTo(vx0,y);ctx.lineTo(vx1,y);ctx.stroke();}
  const wireOrders = outgoingConnectionOrders(state.connections);
  state.connections.forEach((c,idx)=>{
    const pts=routePoints(c); if(!pts)return;
    const sel=state.selected&&state.selected.kind==='conn'&&state.selected.index===idx;
    drawConnection(pts,sel);
  });
  state.connections.forEach((c,idx)=>drawConnectionOrder(routePoints(c),wireOrders[idx]));
  if(state.pendingConn&&state._mouse){const from=blockById(state.pendingConn.from);if(from){const p1=outputPort(from,state.pendingConn.fromPort);drawConnection([p1].concat(defaultRoute(p1,state._mouse)).concat([state._mouse]),false,true);}}
  state.blocks.forEach(b=>drawBlock(b));
  state.blocks.forEach(b=>drawFlowBadges(b));
  if(state.placingType&&state._mouse){const{W,H}=blockDims(state.placingType);ctx.globalAlpha=0.5;ctx.fillStyle='#cfe3f7';ctx.strokeStyle='#2f6fb3';ctx.lineWidth=1.5;roundRect(ctx,state._mouse.x-W/2,state._mouse.y-H/2,W,H,8);ctx.fill();ctx.stroke();ctx.globalAlpha=1;}
  ctx.restore();
}

// ---- hit testing ---------------------------------------------------------
function portAt(x, y) {
  const hitRadius = 16;
  let nearest = null, nearestDistance = hitRadius;
  for (const b of state.blocks) {
    const {nIn, nOut} = instancePorts(b);
    for (const [kind, count, position] of [['in', nIn, inputPort], ['out', nOut, outputPort]]) {
      for (let i = 0; i < count; i++) {
        const p = position(b, i), distance = Math.hypot(p.x - x, p.y - y);
        if (distance < nearestDistance) {
          nearest = {block: b, kind, index: i};
          nearestDistance = distance;
        }
      }
    }
  }
  return nearest;
}
// ---- connector tooltips (HTML tooltip div) --------------------------------
const portTooltipEl = document.getElementById('port_tooltip');
function portTooltip(port) {
  const dir = t(port.kind === 'in' ? 'ui.input' : 'ui.output');
  const b = port.block;
  if (!b) return dir;
  const {inLabels, outLabels} = instancePorts(b);
  const labels = port.kind === 'in' ? inLabels : outLabels;
  if (labels && labels[port.index]) return I18n.port(labels[port.index]);
  return dir + ' ' + (port.index + 1);
}
function updateCanvasTooltip(x, y) {
  const port = portAt(x, y);
  if (port) {
    portTooltipEl.textContent = portTooltip(port);
    portTooltipEl.style.left = (x + state.panX + 12) + 'px';
    portTooltipEl.style.top = (y + state.panY - 28) + 'px';
    portTooltipEl.classList.remove('hidden');
  } else {
    portTooltipEl.classList.add('hidden');
  }
}
function blockAt(x, y) {
  for (let i = state.blocks.length - 1; i >= 0; i--) {
    const b = state.blocks[i]; const {W, H} = blockDims(b);
    if (x >= b.x && x <= b.x + W && y >= b.y && y <= b.y + H) return b;
  }
  return null;
}
function connectionAt(x, y) {
  for (let idx = 0; idx < state.connections.length; idx++) {
    if (hitRoute(state.connections[idx], x, y)) return idx;
  }
  return null;
}

// ---- model (de)serialization ---------------------------------------------
function serializeBlocks(blocks) {
  return blocks.map(b => {
    const o = {id: b.id, type: b.type, params: b.params, x: Math.round(b.x), y: Math.round(b.y)};
    if (['subsystem','typed_experiment'].includes(b.type) && b.internal) {
      o.internal = {
        blocks: serializeBlocks(b.internal.blocks || []),
        connections: (b.internal.connections || []).map(c => {
          const oc = {from: c.from, from_port: c.fromPort, to: c.to, to_port: c.toPort};
          if (c.route && c.route.length) oc.route = c.route.map(p => ({x: Math.round(p.x), y: Math.round(p.y)}));
          return oc;
        }),
      };
    }
    return o;
  });
}
function serializeConnections(conns) {
  return conns.map(c => {
    const o = {from: c.from, from_port: c.fromPort, to: c.to, to_port: c.toPort};
    if (c.route && c.route.length) o.route = c.route.map(p => ({x: Math.round(p.x), y: Math.round(p.y)}));
    return o;
  });
}
function toModelDict() {
  // Always serialize the ROOT (parent) diagram, including internal data
  const rootBlocks = state.rootBlocks || state.blocks;
  const rootConns = state.rootConnections || state.connections;
  return {
    blocks: serializeBlocks(rootBlocks),
    connections: serializeConnections(rootConns),
  };
}
function toActiveDiagramDict() {
  // Serialize the ACTIVE diagram (root or nested view) for local execution
  const blocks = state.blocks;
  const conns = state.connections;
  return {
    blocks: serializeBlocks(blocks),
    connections: serializeConnections(conns),
  };
}
function deserializeBlocks(arr) {
  return (arr || []).map(b => {
    const o = {
      id: String(b.id), type: b.type, params: Object.assign({}, b.params || {}),
      x: Number(b.x) || 0, y: Number(b.y) || 0,
    };
    if (['subsystem','typed_experiment'].includes(b.type) && b.internal) {
      o.internal = {
        blocks: deserializeBlocks(b.internal.blocks),
        connections: deserializeConnections(b.internal.connections),
      };
    }
    return o;
  });
}
function deserializeConnections(arr) {
  return (arr || []).map(c => {
    const o = {
      from: String(c.from), fromPort: Number(c.from_port) || 0,
      to: String(c.to), toPort: Number(c.to_port) || 0,
    };
    if (Array.isArray(c.route) && c.route.length) {
      o.route = c.route.map(p => ({x: Number(p.x) || 0, y: Number(p.y) || 0}));
    }
    return o;
  });
}
function fromModelDict(d) {
  // Load into root, reset to parent view
  state.rootBlocks = deserializeBlocks(d.blocks);
  state.rootConnections = deserializeConnections(d.connections);
  state.blocks = state.rootBlocks;
  state.connections = state.rootConnections;
  state.activeView = null;
  state.selected = null; state.placingType = null; state.pendingConn = null;
  state.bendEditMode = null; state.drag = null; state.panX = 0; state.panY = 0; state.panDrag = null;
  updateModeButtons();
  updateBackButton();
  let mx = 0;
  state.blocks.forEach(b => { const m = /^b(\d+)$/.exec(b.id); if (m) mx = Math.max(mx, parseInt(m[1], 10)); });
  state.nextId = mx + 1;
}

// ---- subsystem view management ---------------------------------------------
function containerForView(path) {
 let nodes=state.rootBlocks || state.blocks,found=null;
 for(const id of (path || '').split('/').filter(Boolean)){found=nodes.find(b=>String(b.id)===id);if(!found)return null;nodes=(found.internal || {}).blocks || [];}
 return found;
}
function enterSubsystem(subId) {
  if (!state.rootBlocks) {
    state.rootBlocks = state.blocks;
    state.rootConnections = state.connections;
  }
  const sub = state.blocks.find(b => b.id === subId && ['subsystem','typed_experiment'].includes(b.type));
  const parentView=state.activeView;
  if (!sub) { setStatus('error', 'status.subsystem_missing', {id:subId}); return; }
  if (!sub.internal) {
    sub.internal = {blocks: [], connections: []};
    if (sub.type === 'typed_experiment') {
      [0,1,2].forEach(port => sub.internal.blocks.push({id:'P'+(port+1),type:'experiment_input',params:{port},x:40,y:70+port*90}));
      sub.internal.blocks.push({id:'J',type:'experiment_result',params:{},x:430,y:70});
    } else {
      sub.internal.blocks.push({id:'In1',type:'in1_terminal',params:{},x:40,y:120});
      sub.internal.blocks.push({id:'Out1',type:'out1_terminal',params:{},x:300,y:120});
      sub.internal.connections.push({from:'In1',fromPort:0,to:'Out1',toPort:0});
    }
  }
  state.blocks = sub.internal.blocks;
  state.connections = sub.internal.connections;
  state.activeView = subId;
  if(parentView)state.activeView=parentView+'/'+subId;
  // Clear stale interaction state
  state.selected = null; state.placingType = null; state.pendingConn = null;
  state.bendEditMode = null; state.drag = null; state.panX = 0; state.panY = 0; state.panDrag = null;
  updateModeButtons();
  updateBackButton();
  // Set nextId for this view
  let mx = 0;
  state.blocks.forEach(b => { const m = /^b(\d+)$/.exec(b.id); if (m) mx = Math.max(mx, parseInt(m[1], 10)); });
  state.nextId = mx + 1;
  draw();
  setStatus('ok', 'status.in_subsystem', {id:subId});
  renderLibraryTree();
}
function exitSubsystem() {
  if(state.activeView && state.activeView.includes('/')) {
    state.activeView=state.activeView.split('/').slice(0,-1).join('/');
    const parent=containerForView(state.activeView);state.blocks=parent.internal.blocks;state.connections=parent.internal.connections;
    state.selected=null;state.drag=null;state.pendingConn=null;state.placingType=null;state.bendEditMode=null;state.panX=0;state.panY=0;state.panDrag=null;
    state.nextId=1+state.blocks.reduce((n,b)=>{const match=/^b(\d+)$/.exec(b.id);return Math.max(n,match?Number(match[1]):0);},0);
    updateModeButtons();updateBackButton();draw();renderLibraryTree();return;
  }
  state.blocks = state.rootBlocks;
  state.connections = state.rootConnections;
  state.activeView = null;
  state.selected = null; state.placingType = null; state.pendingConn = null;
  state.bendEditMode = null; state.drag = null; state.panX = 0; state.panY = 0; state.panDrag = null;
  updateModeButtons();
  updateBackButton();
  let mx = 0;
  state.blocks.forEach(b => { const m = /^b(\d+)$/.exec(b.id); if (m) mx = Math.max(mx, parseInt(m[1], 10)); });
  state.nextId = mx + 1;
  draw();
  setStatus('ok', 'status.back');
  renderLibraryTree();
}
function updateBackButton() {
  const btn = document.getElementById('back_to_parent');
  if (btn) btn.classList.toggle('hidden', !state.activeView);

}
function resultKeyForBlock(block) {
  if (_isInsideNumerical()) return state.activeView + '/' + block.id;
  return block.id;
}

// ---- API ------------------------------------------------------------------
async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch (e) { /* non-JSON */ }
  if (!res.ok) {
    throw new Error(data.error || data.message || ('HTTP ' + res.status));
  }
  return data;
}

// Keep one heap per tab. Web Locks prevent a duplicated tab from reusing
// the original tab's sessionStorage-backed identifier.
let heapSessionPromise = null;
function acquireSessionLock(id) {
  if (!navigator.locks) return Promise.resolve(false);
  return new Promise((resolve, reject) => {
    navigator.locks.request('pavsim-session:' + id, {ifAvailable:true}, lock => {
      resolve(Boolean(lock));
      if (lock) return new Promise(() => {}); // released automatically when this document closes
    }).catch(reject);
  });
}
async function ensureHeapSession() {
  if (!heapSessionPromise) heapSessionPromise = (async () => {
    let id = sessionStorage.getItem('pavsim.heapSession');
    if (id && await acquireSessionLock(id)) {
      const response = await fetch('/api/session/touch', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:id})});
      if (response.ok) return id;
      if (response.status !== 404) throw new Error('Не удалось проверить сессию.');
    }
    const created = await api('/api/session', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
    id = created.session_id;
    if (navigator.locks && !(await acquireSessionLock(id))) throw new Error('Не удалось открыть сессию вкладки.');
    sessionStorage.setItem('pavsim.heapSession', id);
    return id;
  })().catch(error => { heapSessionPromise = null; throw error; });
  return heapSessionPromise;
}
async function sessionForRun() {
  let id = await ensureHeapSession();
  const response = await fetch('/api/session/touch', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:id})});
  if (response.status === 404) {
    heapSessionPromise = null;
    id = await ensureHeapSession();
  } else if (!response.ok) {
    throw new Error('Не удалось проверить сессию.');
  }
  return id;
}
setInterval(() => {
  if (heapSessionPromise) heapSessionPromise.then(id => fetch('/api/session/touch', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:id})
  }).then(response => { if (response.status === 404) heapSessionPromise = null; })).catch(() => {});
}, 300000);

// ---- library (file-system tree) -------------------------------------------
async function loadBlockTypes() {
  const data = await api('/api/blocks');
  state.blockTypes = {};
  (data.blocks || []).forEach(bt => { state.blockTypes[bt.name] = bt; });
  // Boundary terminals (not in library, hardcoded dimensions for rendering)
  state.blockTypes['experiment_input']={name:'experiment_input',display_name:'Параметр эксперимента',n_inputs:0,n_outputs:1,parameters:{port:0},output_labels:['p']};
  state.blockTypes['experiment_result']={name:'experiment_result',display_name:'Итоговая оценка',n_inputs:1,n_outputs:0,parameters:{},input_labels:['J']};
  state.blockTypes['in1_terminal'] = {name:'in1_terminal', display_name:'Вход подсистемы', input_labels:[], output_labels:['In1'], n_inputs:0, n_outputs:1, state_kind:'none', parameters:{name:'', mapping:''}, parameter_labels:{name:'Port name', mapping:'Maps to (block_id.param)'}};
  state.blockTypes['out1_terminal'] = {name:'out1_terminal', display_name:'Выход подсистемы', input_labels:['Out1'], output_labels:[], n_inputs:1, n_outputs:0, state_kind:'none', parameters:{name:'', mapping:''}, parameter_labels:{name:'Port name', mapping:'Maps to (block_id)'}};
}
function _isInsideNumerical() {
  return _currentContext() === 'numerical';
}
// Current placement context: 'numerical' if any ancestor (or the view itself)
// is a numerical engine block, otherwise 'outer'. Nested subsystems inherit
// the context of the nearest parent engine block.
function _currentContext() {
  if (!state.activeView) return 'outer';
  const path = state.activeView.split('/').filter(Boolean);
  let nodes = state.rootBlocks || state.blocks;
  for (const id of path) {
    const b = nodes.find(x => String(x.id) === id);
    if (!b) return 'outer';
    if (b.type === 'typed_experiment') return 'numerical';
    nodes = (b.internal || {}).blocks || [];
  }
  return 'outer';
}
function _blockAvailable(name) {
  const ctx = _currentContext();
  const contexts = (state.blockContexts || {})[name];
  if (!contexts) return true; // unknown block: allow (legacy)
  return contexts.includes(ctx);
}
async function loadLibrary() {
  const seq = ++state._libSeq;
  const data = await api('/api/library');
  if (seq !== state._libSeq) return; // stale response, discard
  state.libraryTree = data.tree || [];
  state.blockContexts = data.block_contexts || {};
  await loadBlockTypes();
  if (seq !== state._libSeq) return; // stale response, discard
  renderLibraryTree();
  if (data.load_errors && data.load_errors.length) {
    setStatus('error', 'status.library_errors', {loadErrors:data.load_errors});
  }
}
function renderLibraryTree() {
  const root = document.getElementById('library_tree');
  root.innerHTML = '';
  const ul = document.createElement('ul'); ul.className = 'tree';
  const groups = new Map();
  (state.libraryTree || []).forEach(node => {
    const section = node.section || 'shell';
    if (!groups.has(section)) groups.set(section, []);
    groups.get(section).push(node);
  });
  state.libraryGroupOpen = state.libraryGroupOpen || {};
  groups.forEach((nodes, section) => {
    const li = document.createElement('li');
    const row = document.createElement('div'); row.className = 'tree-folder';
    const arrow = document.createElement('span'); arrow.className = 'arrow';
    const children = document.createElement('ul'); children.className = 'tree-children';
    const update = () => {
      const open = state.libraryGroupOpen[section] !== false;
      arrow.textContent = open ? '\u25be' : '\u25b8';
      children.style.display = open ? '' : 'none';
    };
    row.appendChild(arrow);
    row.appendChild(localizedText('section.' + section, section));
    nodes.forEach(node => children.appendChild(renderNode(node)));
    row.addEventListener('click', () => {
      state.libraryGroupOpen[section] = state.libraryGroupOpen[section] === false;
      update();
    });
    update(); li.appendChild(row); li.appendChild(children); ul.appendChild(li);
  });
  root.appendChild(ul);
}
function renderNode(node) {
  const li = document.createElement('li');
  if (node.type === 'category') {
    const row = document.createElement('div'); row.className = 'tree-category';
    const arrow = document.createElement('span'); arrow.className = 'arrow'; arrow.textContent = '\u25be';
    row.appendChild(arrow); row.appendChild(localizedText('category.'+node.name,node.name));
    const ul = document.createElement('ul'); ul.className = 'tree-blocks';
    (node.blocks || []).forEach(name => {
      const b = document.createElement('li'); b.className = 'tree-block'; b.textContent = I18n.blockName(state.blockTypes[name] || {name}); b.dataset.blockType=name;
      b.title = I18n.blockDescription(state.blockTypes[name] || {name});
      b.addEventListener('click', () => selectPlacingBlock(name));
      ul.appendChild(b);
    });
    li.appendChild(row); li.appendChild(ul);
    row.addEventListener('click', () => {
      const open = ul.style.display !== 'none';
      ul.style.display = open ? 'none' : '';
      arrow.textContent = open ? '\u25b8' : '\u25be';
    });
  }
  return li;
}
function selectPlacingBlock(name) {
  if (!_blockAvailable(name)) {
    setStatus('error', 'status.block_context', {name: I18n.blockName(state.blockTypes[name] || {name}), context: _currentContext()});
    return;
  }
  state.placingType = name;
  document.querySelectorAll('.tree-block.active').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tree-block').forEach(el => { if (el.dataset.blockType === name) el.classList.add('active'); });
  setStatus('info', 'status.placing', {blockType:name});
}

// ---- simulation -----------------------------------------------------------

// Update ownership badge display
function updateOwnershipBadge() {
  const badge = document.getElementById('ownership_badge');
  if (!badge) return;
  // Check the ACTIVE diagram's blocks (not always root)
  const blocks = state.blocks;
  const hasIn = blocks.some(b => b.type === 'in1_terminal');
  const hasOut = blocks.some(b => b.type === 'out1_terminal');
  if (hasIn || hasOut) {
    badge.textContent = 'EXTERNALLY CONTROLLED';
    badge.className = 'ownership-external';
    badge.title = 'This diagram has declared external ports. Internal execution is prohibited. Use /api/invoke.';
  } else {
    badge.textContent = 'STANDALONE';
    badge.className = 'ownership-standalone';
    badge.title = 'No external ports declared. This diagram can run internally.';
  }
}

async function runSim() {
  if (state.runInProgress) return;
  state.stopRequested = false;
  if (state.blocks.length === 0) {
    setStatus('error', 'status.empty');
    return;
  }
  // Ownership check: reject if ACTIVE diagram has external ports
  const hasExternal = state.blocks.some(b => b.type === 'in1_terminal' || b.type === 'out1_terminal');
  if (hasExternal) {
    setStatus('error', 'status.externally_controlled');
    return;
  }
  setStatus('info', 'status.running');
  state.runInProgress = true;
  try {
    let model = toActiveDiagramDict();
    let inTypedExperiment = false;
    let pathBlocks = state.rootBlocks || state.blocks;
    for (const id of (state.activeView || '').split('/').filter(Boolean)) {
      const block = pathBlocks.find(b => String(b.id) === id);
      if (!block) break;
      if (block.type === 'typed_experiment') inTypedExperiment = true;
      pathBlocks = (block.internal || {}).blocks || [];
    }
    if (inTypedExperiment) model = toModelDict();
    const body = {
      model: model,
      session_id: await sessionForRun(),
      run_id: crypto.randomUUID().replaceAll('-', ''),
    };
    const fingerprint = JSON.stringify(body.model);
    const pendingRun = api('/api/simulate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    state.lastRunId = body.run_id;
    state.runInProgress = true;
    startFlowAnimation(body.run_id);
    state.lastResults = {};
    function findLiveGraphs(diagram, prefix='') {
      (diagram.blocks || []).forEach(block => {
        const key = prefix + String(block.id);
        if (block.type.startsWith('graph_outer')) state.lastResults[key] = true;
        if (block.type==='optimizer') state.lastResults[key] = true;
        if (block.internal) findLiveGraphs(block.internal, key + '/');
      });
    }
    findLiveGraphs(body.model);
    updateGraphWindows();
    updateOutputWindows();
    const data = await pendingRun;
    state.runInProgress = false;
    const tuning = data.optimization || [];
    if ((tuning.length || (data.experiments || []).length) && JSON.stringify(inTypedExperiment ? toModelDict() : toActiveDiagramDict()) !== fingerprint) {
      setStatus('error', 'status.changed'); return;
    }
    draw();
    state.lastRunId=data.run_id;
    state.lastResults = data.results || {};
    updateGraphWindows();
    updateOutputWindows();
    const nGraph = state.blocks.filter(b => b.type.startsWith('graph_')).length;
    renderRunSummary(data);

  } catch (err) {
    state.runInProgress = false;
    stopFlowAnimation();
    if (state.stopRequested) setStatus('info', 'status.session_stopped');
    else setStatus('error', 'status.sim_failed', {error:err.message});
  }
}

// Show process state as events arrive, without delaying the calculation.
function stopFlowAnimation() {
  if (state.flowStream) state.flowStream.close();
  state.flowStream = null;
  state.flowRunId = null;
  state.flowBadges = {};
  draw();
}
function startFlowAnimation(runId) {
  if (state.flowStream) state.flowStream.close();
  state.flowRunId = runId;
  state.flowBadges = {};
  const stream = new EventSource('/api/flow-events?run=' + encodeURIComponent(runId));
  state.flowStream = stream;
  stream.onmessage = event => {
    if (state.flowRunId !== runId || state.flowStream !== stream) return;
    const data = JSON.parse(event.data);
    state.flowBadges = data.blocks || {};
    draw();
    if (data.complete) stopFlowAnimation();
  };
}

// ---- save / load ----------------------------------------------------------
async function saveModel() {
  const name = document.getElementById('model_name').value.trim();
  if (!name) { setStatus('error', 'status.name_required'); return; }
  try {
    await api('/api/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, model: toModelDict()}),
    });
    await refreshModels(name);
    setStatus('ok', 'status.saved', {name});
  } catch (err) {
    setStatus('error', 'status.save_failed', {error:err.message});
  }
}
async function refreshModels(preferredName) {
  try {
    const data = await api('/api/models');
    const sel = document.getElementById('load_list');
    const prevSel = sel.value;
    sel.innerHTML = '';
    (data.models || []).forEach(n => {
      const o = document.createElement('option'); o.value = n; o.textContent = n;
      sel.appendChild(o);
    });
    // Select the preferred name (e.g. just-saved), else preserve current selection,
    // else fall back to first entry.
    const names = data.models || [];
    if (preferredName && names.includes(preferredName)) {
      sel.value = preferredName;
    } else if (names.includes(prevSel)) {
      sel.value = prevSel;
    } else if (names.length > 0) {
      sel.value = names[0];
    }
  } catch (err) { /* non-fatal: preserve existing dropdown contents */ }
}
async function loadModel() {
  const name = document.getElementById('load_list').value;
  if (!name) { setStatus('error', 'status.choose_model'); return; }
  try {
    const data = await api('/api/load?name=' + encodeURIComponent(name));
    const missing = [];
    (data.model.blocks || []).forEach(b => {
      if (!state.blockTypes[b.type]) missing.push(b.type);
      if (b.internal && b.internal.blocks) {
        b.internal.blocks.forEach(ib => { if (!state.blockTypes[ib.type]) missing.push(ib.type); });
      }
      if (b.params && b.params.model && b.params.model.blocks) {
        b.params.model.blocks.forEach(ib => { if (!state.blockTypes[ib.type]) missing.push(ib.type); });
      }
    });
    if (missing.length) {
      const uniq = Array.from(new Set(missing));
      // Allow loading: show warning that some blocks are from an unavailable engine
      fromModelDict(data.model);
      draw();
      document.getElementById('model_name').value = name;
      setStatus('info', 'status.unknown_blocks', {name,types:uniq.join(', ')});
    } else {
      fromModelDict(data.model);
      draw();
      document.getElementById('model_name').value = name;
      setStatus('ok', 'status.loaded', {name,blocks:state.blocks.length,connections:state.connections.length});
    }
  } catch (err) {
    setStatus('error', 'status.load_failed', {error:err.message});
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ---- graph windows (separate browser windows) -----------------------------
function openGraphWindow(block) {
  const key=resultKeyForBlock(block);
  const url='/plot.html?run='+encodeURIComponent(state.lastRunId || '')+'&block='+encodeURIComponent(key)+(state.runInProgress?'&live=1':'');
  const existing=state.graphWindows[key];
  if(existing&&!existing.closed){existing.location.href=url;try{existing.focus();}catch(e){}return existing;}
  const win=window.open(url,'_blank','width=860,height=600');
  if(!win){setStatus('error','status.popup');return null;}
  state.graphWindows[key]=win;return win;
}

function updateGraphWindows() {
  Object.entries(state.graphWindows).forEach(([key,win])=>{
    if(win.closed){delete state.graphWindows[key];return;}
    if (!state.lastResults[key]) return;
    win.location.href='/plot.html?run='+encodeURIComponent(state.lastRunId || '')+'&block='+encodeURIComponent(key)+(state.runInProgress?'&live=1':'');
  });
}

function openOptimizerOutput(block) {
  const key=resultKeyForBlock(block);
  const url='/output.html?run='+encodeURIComponent(state.lastRunId||'')+'&block='+encodeURIComponent(key)+(state.runInProgress?'&live=1':'');
  const existing=state.outputWindows[key];
  if(existing&&!existing.closed){existing.location.href=url;try{existing.focus();}catch(e){}return existing;}
  const win=window.open(url,'_blank','width=860,height=600');
  if(!win){setStatus('error','status.popup');return null;}
  state.outputWindows[key]=win;return win;
}
function updateOutputWindows() {
  Object.entries(state.outputWindows).forEach(([key,win])=>{
    if(win.closed){delete state.outputWindows[key];return;}
    if(!state.lastResults[key])return;
    win.location.href='/output.html?run='+encodeURIComponent(state.lastRunId||'')+'&block='+encodeURIComponent(key)+(state.runInProgress?'&live=1':'');
  });
}

// ---- parameters dialog ----------------------------------------------------
let dialogBlock = null;
function openDialog(block) {
  dialogBlock = block;
  const bt = state.blockTypes[block.type] || {parameters: {}};
  document.getElementById('dialog_title').textContent = block.id + ' \u2014 ' + I18n.blockName({...bt,name:block.type});
  const body = document.getElementById('dialog_body');
  body.innerHTML = '';
  const params = bt.parameters || {};
  // Structured values (including the nested model) are edited on the canvas,
  // not in scalar parameter controls; preserve them when applying the dialog.
  const keys = Object.keys(params).filter(k => params[k] !== null && typeof params[k] !== 'object');
  if (keys.length === 0) {
    const p = document.createElement('p');
    p.dataset.i18n='ui.no_parameters'; p.textContent = t('ui.no_parameters');
    body.appendChild(p);
  }
  keys.forEach(k => {
    const def = params[k];
    const label = document.createElement('label');
    label.appendChild(localizedText('param.'+k,(bt.parameter_labels || {})[k] || k)); label.title=PAVSIM_CATALOG.en['hint.param.'+k]?t('hint.param.'+k):k;
    let input;
    if (typeof def === 'boolean') {
      input = document.createElement('input'); input.type = 'checkbox';
    } else if (bt.parameter_choices && bt.parameter_choices[k]) {
      input = document.createElement('select');
      bt.parameter_choices[k].forEach(choice=>{
        const value = typeof choice === 'string' ? choice : choice.value;
        const label = typeof choice === 'string' ? choice : (choice.label || value);
        const o=document.createElement('option');o.value=value;o.dataset.choice=value;
        o.dataset.choiceFallback=label;o.textContent=choiceText(value,label);input.appendChild(o);
      });
    } else if (typeof def === 'string') {
      if (k === 'type' && block.type === 'signal_generator') {
        input = document.createElement('select');
        ['sine', 'square', 'ramp', 'step'].forEach(v => {
          const o = document.createElement('option'); o.value = v; o.dataset.choice=v; o.textContent=t('choice.'+v);
          input.appendChild(o);
        });
      } else {
        input = document.createElement('input'); input.type = 'text';
      }
    } else {
      input = document.createElement('input'); input.type = 'number'; input.step = 'any';
    }
    input.value = (block.params && k in block.params) ? block.params[k] : def;
    if (block.type==='graph_outer_xy_score' && !(k in (block.params||{}))) {
      const match=/^([xy])_(start|end)$/.exec(k);
      if (match) {
        const previous=String((block.params||{})[match[1]+'_range']||'').split(':');
        if (previous.length===2) input.value=previous[match[2]==='start'?0:1].trim();
      }
    }
    if (typeof def === 'boolean') input.checked = (block.params && k in block.params) ? Boolean(block.params[k]) : def;
    input.id = 'dlg_' + k;
    if (k==='label') { input.dataset.rawLabel=input.value; input.dataset.displayLabel=I18n.plotLabel(input.value); input.value=input.dataset.displayLabel; }
    if(k==='x_range' || k==='y_range'){input.dataset.i18nPlaceholder='ui.range_placeholder';input.dataset.i18nTitle='ui.range_hint'; input.placeholder=t('ui.range_placeholder');input.title=t('ui.range_hint');}
    if(k==='algorithm_options'){input.placeholder='initial_step=0.1; tolerance=0.0005';input.dataset.i18nTitle='ui.algorithm_hint';input.title=t('ui.algorithm_hint');}
    label.appendChild(input);
    body.appendChild(label);
  });
  document.getElementById('dialog_overlay').classList.remove('hidden');
}
function closeDialog() {
  document.getElementById('dialog_overlay').classList.add('hidden');
  dialogBlock = null;
}
function applyDialog() {
  if (!dialogBlock) return;
  const id = dialogBlock.id;
  const bt = state.blockTypes[dialogBlock.type] || {parameters: {}};
  Object.keys(bt.parameters || {}).forEach(k => {
    const el = document.getElementById('dlg_' + k);
    if (!el) return;
    const def = bt.parameters[k];
    if (typeof def === 'boolean') {
      dialogBlock.params[k] = el.checked;
    } else if (typeof def === 'number') {
      const v = parseFloat(el.value);
      dialogBlock.params[k] = isNaN(v) ? def : v;
    } else {
      dialogBlock.params[k] = k==='label' && el.value===el.dataset.displayLabel ? el.dataset.rawLabel : el.value;
    }
  });
  if (dialogBlock.type==='graph_outer_xy_score') {
    delete dialogBlock.params.x_range;
    delete dialogBlock.params.y_range;
  }
  const owner=dialogBlock;
  closeDialog();
  // Solver params are in the experiment block; no toolbar to sync
  draw();
  setStatus('ok', 'status.updated', {id});
}

// ---- block deletion --------------------------------------------------------
function deleteBlock(id) {
  const b = state.blocks.find(x => x.id === id);
  if (!b) return;
  if (['in1_terminal','out1_terminal','experiment_input','experiment_result'].includes(b.type)) {
    setStatus('error', 'status.boundary', {id});
    return;
  }
  // Prevent deleting a subsystem while inside it (should not happen, but guard)
  if (b.type === 'subsystem' && state.activeView === id) {
    exitSubsystem();
  }
  const idx = state.blocks.findIndex(x => x.id === id);
  if (idx === -1) return;
  state.blocks.splice(idx, 1);
  for (let i = state.connections.length - 1; i >= 0; i--) {
    if (state.connections[i].from === id || state.connections[i].to === id) state.connections.splice(i, 1);
  }
  if (state.selected && state.selected.kind === 'block' && state.selected.id === id) state.selected = null;
  const win = state.graphWindows[id];
  if (win && !win.closed) { try { win.close(); } catch (e) {} }
  delete state.graphWindows[id];
  updateBackButton();
  draw();
  setStatus('ok', 'status.removed', {id});
}
function deleteConnection(idx) {
  state.connections.splice(idx, 1);
  state.selected = null;
  draw();
  setStatus('ok', 'status.connection_removed');
}

// ---- canvas events --------------------------------------------------------
canvas.addEventListener('mousemove', ev => {
  const cp = canvasPos(ev);
  const p = worldPos(ev);
  state._mouse = p;
  updateCanvasTooltip(p.x, p.y);
  // Handle pan drag
  if (state.panDrag) {
    state.panX = state.panDrag.startPanX + (cp.x - state.panDrag.startX);
    state.panY = state.panDrag.startPanY + (cp.y - state.panDrag.startY);
    state._panMoved = true;
    draw();
    return;
  }
  const d = state.drag;
  if (d) {
    if (d.kind === 'block') {
      const nx = p.x - d.dx, ny = p.y - d.dy;
      const ddx = nx - d.block.x, ddy = ny - d.block.y;
      // Adjust routes first (old port positions), then move the block.
      for (const c of state.connections) {
        if (c.from === d.block.id || c.to === d.block.id) adjustRouteForBlockMove(c, d.block.id, ddx, ddy);
      }
      d.block.x = nx; d.block.y = ny;
    } else if (d.kind === 'bend') {
      const c = state.connections[d.connIdx];
      if (c) dragBend(c, d.bendIdx, p.x - d.lastX, p.y - d.lastY);
    } else if (d.kind === 'segment') {
      const c = state.connections[d.connIdx];
      if (c) dragSegment(c, d.segIdx, p.x - d.lastX, p.y - d.lastY);
    }
    d.lastX = p.x; d.lastY = p.y;
  }
  draw();
});
canvas.addEventListener('mouseleave', () => { portTooltipEl.classList.add('hidden'); });
canvas.addEventListener('mousedown', ev => {
  if (ev.button !== 0) return;
  const cp = canvasPos(ev);
  const p = worldPos(ev);
  if (state.bendEditMode === 'edit_bends') {
    for (let idx = 0; idx < state.connections.length; idx++) {
      const hit = hitRoute(state.connections[idx], p.x, p.y, 8);
      if (hit) {
        materializeRoute(state.connections[idx]);
        state.selected = {kind: 'conn', index: idx};
        if (hit.type === 'bend') {
          // Add Bend mode: clicking an existing bend does nothing (no deletion)
        } else {
          const dragIdx = insertDetour(state.connections[idx], hit.index, p.x, p.y);
          if (dragIdx >= 0) {
            state.drag = {kind: 'bend', connIdx: idx, bendIdx: dragIdx, segIdx: -1, lastX: p.x, lastY: p.y};
          }
        }
        draw();
        return;
      }
    }
    return;
  }
  if (state.bendEditMode === 'reset_route') {
    for (let idx = 0; idx < state.connections.length; idx++) {
      const hit = hitRoute(state.connections[idx], p.x, p.y, 8);
      if (hit) {
        state.selected = {kind: 'conn', index: idx};
        state.connections[idx].route = null;
        draw();
        return;
      }
    }
    return;
  }
  const port = portAt(p.x, p.y);
  if (port && port.kind === 'out') {
    state.pendingConn = {from: port.block.id, fromPort: port.index};
    return;
  }
  for (let idx = 0; idx < state.connections.length; idx++) {
    const hit = hitRoute(state.connections[idx], p.x, p.y, 8);
    if (hit) {
      materializeRoute(state.connections[idx]);
      state.selected = {kind: 'conn', index: idx};
      state.drag = {kind: hit.type, connIdx: idx,
                    bendIdx: hit.type === 'bend' ? hit.index : -1,
                    segIdx: hit.type === 'segment' ? hit.index : -1,
                    lastX: p.x, lastY: p.y};
      draw();
      return;
    }
  }
  const b = blockAt(p.x, p.y);
  if (b) {
    state.drag = {kind: 'block', block: b, dx: p.x - b.x, dy: p.y - b.y};
    return;
  }
  // Empty canvas: start pan
  state.panDrag = {startX: cp.x, startY: cp.y, startPanX: state.panX, startPanY: state.panY};
  state._panMoved = false;
});
canvas.addEventListener('mouseup', ev => {
  if (ev.button !== 0) return;
  const p = worldPos(ev);
  if (state.panDrag) {
    state.panDrag = null;
    return;
  }
  if (state.pendingConn) {
    const port = portAt(p.x, p.y);
    if (port && port.kind === 'in' && port.block.id !== state.pendingConn.from) {
      const occupied = state.connections.find(c => c.to === port.block.id && c.toPort === port.index);
      if (occupied) {
        const same = occupied.from === state.pendingConn.from && occupied.fromPort === state.pendingConn.fromPort;
        setStatus(same ? 'info' : 'error', same ? 'status.connected' : 'status.occupied', {id:port.block.id,port:port.index+1});
      } else {
        state.connections.push({
          from: state.pendingConn.from, fromPort: state.pendingConn.fromPort,
          to: port.block.id, toPort: port.index,
        });
        state.selected = {kind: 'conn', index: state.connections.length - 1};
      }
    }
    state.pendingConn = null;
    draw();
    return;
  }
  if (state.drag && (state.drag.kind === 'bend' || state.drag.kind === 'segment')) {
    const c = state.connections[state.drag.connIdx];
    if (c) normalizeRoute(c);
    state.drag = null;
    draw();
    return;
  }
  state.drag = null;
});
// Window-level mouseup to stop pan even if released outside canvas
window.addEventListener('mouseup', ev => {
  if (ev.button !== 0) return;
  if (state.panDrag) {
    state.panDrag = null;
    state._panMoved = false;
    draw();
  }
});
canvas.addEventListener('click', ev => {
  const p = worldPos(ev);
  if (state._panMoved) { state._panMoved = false; return; }
  if (state.bendEditMode) return;
  if (state.placingType) {
    // Prevent placing subsystem inside a subsystem (one-level restriction)
    if (state.activeView && state.placingType === 'subsystem' && containerForView(state.activeView).type !== 'typed_experiment') {
      setStatus('error', 'status.nested_subsystem');
      state.placingType = null;
      document.querySelectorAll('.tree-block.active').forEach(el => el.classList.remove('active'));
      return;
    }
    const bt = state.blockTypes[state.placingType];
    if (!bt) {
      setStatus('error', 'status.block_unavailable', {type:state.placingType});
      state.placingType = null;
      document.querySelectorAll('.tree-block.active').forEach(el => el.classList.remove('active'));
      return;
    }
    const id = 'b' + (state.nextId++);
    const {W, H} = blockDims(state.placingType);
    const block = {
      id: id, type: state.placingType,
      params: Object.assign({}, bt.parameters || {}),
      x: Math.round(p.x - W / 2), y: Math.round(p.y - H / 2),
    };
    state.blocks.push(block);
    state.selected = {kind: 'block', id: id};
    state.placingType = null;
    document.querySelectorAll('.tree-block.active').forEach(el => el.classList.remove('active'));
    updateBackButton();
    draw();
    setStatus('ok', 'status.placed', {blockType:block.type,id});
    return;
  }
  const port = portAt(p.x, p.y);
  if (port) { state.selected = {kind: 'block', id: port.block.id}; draw(); return; }
  const b = blockAt(p.x, p.y);
  if (b) { state.selected = {kind: 'block', id: b.id}; draw(); return; }
  const ci = connectionAt(p.x, p.y);
  if (ci !== null) { state.selected = {kind: 'conn', index: ci}; draw(); return; }
  state.selected = null;
  draw();
});
canvas.addEventListener('dblclick', ev => {
  const p = worldPos(ev);
  const b = blockAt(p.x, p.y);
  if (!b) return;
  if (['subsystem','typed_experiment'].includes(b.type)) {
    // Double-click a subsystem: open its internal canvas
    enterSubsystem(b.id);
  } else if (b.type.startsWith('graph_')) {
    openGraphWindow(b);
  } else if (b.type === 'optimizer') {
    openOptimizerOutput(b);
  } else if (['in1_terminal','out1_terminal','experiment_input','experiment_result'].includes(b.type)) {
    setStatus('info', 'status.boundary_edit');
  } else {
    openDialog(b);
  }
});
canvas.addEventListener('contextmenu', ev => {
  ev.preventDefault();
  const p = worldPos(ev);
  const b = blockAt(p.x, p.y);
  if (b) { deleteBlock(b.id); return; }
  const ci = connectionAt(p.x, p.y);
  if (ci !== null) { deleteConnection(ci); return; }
  if (state.selected) {
    if (state.selected.kind === 'block') deleteBlock(state.selected.id);
    else if (state.selected.kind === 'conn') deleteConnection(state.selected.index);
  }
});

window.addEventListener('keydown', ev => {
  const tag = (document.activeElement && document.activeElement.tagName) || '';
  const typing = tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA';
  if (ev.key === 'F2' && !typing) { ev.preventDefault(); editSelectedBlock(); return; }
  if (ev.key === 'Escape') {
    if (!document.getElementById('dialog_overlay').classList.contains('hidden')) { closeDialog(); return; }
    if (state.bendEditMode) {
      state.bendEditMode = null;
      updateModeButtons();
      setStatus('info', 'status.bend_off');
      draw();
      return;
    }
    if (state.placingType) {
      state.placingType = null;
      document.querySelectorAll('.tree-block.active').forEach(el => el.classList.remove('active'));
      draw();
      return;
    }
    state.pendingConn = null;
    draw();
  }
  if ((ev.key === 'Delete' || ev.key === 'Backspace') && state.selected && !typing) {
    if (state.selected.kind === 'block') deleteBlock(state.selected.id);
    else if (state.selected.kind === 'conn') deleteConnection(state.selected.index);
  }
});

function editSelectedBlock() {
  const block=state.selected && state.selected.kind==='block' ? blockById(state.selected.id) : null;
  if(!block){setStatus('info','status.select_block');return;}
  if(['in1_terminal','out1_terminal','experiment_input','experiment_result'].includes(block.type)){setStatus('info','status.boundary_edit');return;}
  openDialog(block);
}
// ---- toolbar wiring -------------------------------------------------------
document.getElementById('back_to_parent').addEventListener('click', exitSubsystem);
document.getElementById('edit_bends').addEventListener('click', toggleBendEditMode);
document.getElementById('reset_route').addEventListener('click', toggleResetRouteMode);
document.getElementById('block_params').addEventListener('click',editSelectedBlock);
document.getElementById('run').addEventListener('click', runSim);
document.getElementById('stop_session').addEventListener('click', async () => {
  if (!heapSessionPromise) return;
  state.stopRequested = true;
  stopFlowAnimation();
  try {
    const id = await heapSessionPromise;
    const result = await api('/api/session/stop', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:id})});
    heapSessionPromise = null;
    sessionStorage.removeItem('pavsim.heapSession');
    setStatus(result.status==='cleanup_failed'?'error':'info', result.status==='cleanup_failed'?'status.session_cleanup_failed':'status.session_stopped');
  } catch (error) {
    state.stopRequested = false;
    setStatus('error', 'status.sim_failed', {error:error.message});
  }
});
document.getElementById('save').addEventListener('click', saveModel);
document.getElementById('load').addEventListener('click', loadModel);
document.getElementById('clear').addEventListener('click', () => {
  if (state.blocks.length === 0) { setStatus('info', 'status.already_empty'); return; }
  if (!confirm(t('status.clear_confirm'))) return;
  state.blocks = state.rootBlocks = [];
  state.connections = state.rootConnections = [];
  state.activeView = null; state.selected = null; state.lastResults = null; state.panX = 0; state.panY = 0; state.panDrag = null;
  updateBackButton();
  for (const bid of Object.keys(state.graphWindows)) {
    const win = state.graphWindows[bid];
    if (win && !win.closed) { try { win.close(); } catch (e) {} }
    delete state.graphWindows[bid];
  }
  draw();
  setStatus('ok', 'status.cleared');
});
document.getElementById('library_refresh').addEventListener('click', async () => {
  setStatus('info', 'status.refreshing');
  try {
    const seq = ++state._libSeq;
    const data = await api('/api/library/refresh', {method: 'POST'});
    if (seq !== state._libSeq) return;
    state.libraryTree = data.tree || [];
    state.blockContexts = data.block_contexts || {};
    await loadBlockTypes();
    if (seq !== state._libSeq) return;
    renderLibraryTree();
    if (data.load_errors && data.load_errors.length) {
      setStatus('error', 'status.library_errors', {loadErrors:data.load_errors});
    } else {
      setStatus('ok', 'status.refreshed');
    }
  } catch (err) {
    setStatus('error', 'status.refresh_failed', {error:err.message});
  }
});
document.getElementById('dialog_ok').addEventListener('click', applyDialog);
document.getElementById('dialog_cancel').addEventListener('click', closeDialog);
document.getElementById('dialog_overlay').addEventListener('click', ev => {
  if (ev.target === ev.currentTarget) closeDialog();
});

// ---- init -----------------------------------------------------------------
(async function init() {
  resizeCanvas();
  try {
    await loadLibrary();
  } catch (err) {
    setStatus('error', 'status.library_failed', {error:err.message});
  }
  await refreshModels();
  draw();
})();

// ---- display-only language switching -------------------------------------
function choiceText(value, fallback) {
  const key=(['rk4','euler'].includes(value)?'literal.':'choice.')+value;
  return PAVSIM_CATALOG.en[key] ? t(key) : fallback;
}
function localizedText(key, fallback) {
  const span=document.createElement('span');if(PAVSIM_CATALOG.en[key])span.dataset.i18n=key;
  span.textContent=PAVSIM_CATALOG.en[key] ? t(key) : fallback;return span;
}
function renderRunSummary(data) {
  const tuning=data.optimization || [];
  const experiments=data.experiments || [];
  const nGraph=state.blocks.filter(b=>b.type.startsWith('graph_')).length;
  let text=experiments.length ? experiments.map(e=>e.block_id+': J='+e.result.toPrecision(5)+'; t_end='+e.t_end+', h='+e.h+', '+e.method.toUpperCase()).join('\n') :
    t('status.finished',{steps:data.n_steps,signals:Object.keys(state.lastResults).length});
  text+=(nGraph ? t('status.plot_hint') : '')+tuning.map(r=>'\n'+r.block_id+': '+Object.entries(r.values).map(([k,v])=>k+'='+v.toPrecision(5)).join(', ')+
    t('status.evaluations',{n:r.evaluations})+(r.numerical_id ? ' J: '+r.baseline_score.toPrecision(6)+' → '+r.score.toPrecision(6) : '')+(r.experiment_id ? t('status.score',{score:r.score.toPrecision(5)}) : (r.converged===true?t('status.converged'):r.converged===false?t('status.not_converged'):t('status.unknown')))).join('');
  setStatus('ok',text);
  statusPresentation={run:data};
  const links=document.createElement('div');
  state.blocks.filter(b=>b.type.startsWith('graph_')).forEach(b=>{
    const a=document.createElement('a');a.textContent=t('status.open_plot',{name:I18n.plotLabel(b.params.label || b.id)});
    a.href='/plot.html?run='+encodeURIComponent(state.lastRunId)+'&block='+encodeURIComponent(resultKeyForBlock(b));a.target='_blank';links.appendChild(a);
  });
  document.getElementById('statusbar').appendChild(links);
}
function refreshLanguage() {
  I18n.apply();
  document.querySelectorAll('[data-block-type]').forEach(el=>{
    const bt=state.blockTypes[el.dataset.blockType] || {name:el.dataset.blockType};
    el.textContent=I18n.blockName(bt);el.title=I18n.blockDescription(bt);
  });
  document.querySelectorAll('[data-choice]').forEach(el=>{
    el.textContent=choiceText(el.dataset.choice,el.dataset.choiceFallback || el.dataset.choice);
  });
  if(dialogBlock) {
    const bt=state.blockTypes[dialogBlock.type] || {name:dialogBlock.type};
    document.getElementById('dialog_title').textContent=dialogBlock.id+' — '+I18n.blockName(bt);
    Object.keys(bt.parameters || {}).forEach(k=>{
      const input=document.getElementById('dlg_'+k);
      if(input && input.parentElement)input.parentElement.title=PAVSIM_CATALOG.en['hint.param.'+k]?t('hint.param.'+k):k;
      if(k==='label' && input && input.value===input.dataset.displayLabel) {
        input.dataset.displayLabel=I18n.plotLabel(input.dataset.rawLabel);input.value=input.dataset.displayLabel;
      }
    });
  }
  if(statusPresentation) {
    if(statusPresentation.run)renderRunSummary(statusPresentation.run);
    else setStatus(statusPresentation.kind,statusPresentation.key,statusPresentation.values);
  }
  portTooltipEl.classList.add('hidden');
  resizeCanvas(); // Toolbar wrapping can change the canvas height in either language.
}
document.getElementById('language').addEventListener('change',ev=>I18n.setLanguage(ev.target.value));
I18n.onChange(refreshLanguage);
refreshLanguage();
