'use strict';
const state = {
  blocks: [], connections: [], blockTypes: {}, libraryTree: null,
  selected: null, placingType: null, pendingConn: null, drag: null,
  bendEditMode: null,
  nextId: 1, lastResults: null, graphWindows: {},
  // Subsystem view system
  rootBlocks: null,       // parent diagram blocks (source of truth)
  rootConnections: null,  // parent diagram connections (source of truth)
  activeView: null,       // null = parent view, string = subsystem block ID (internal view)
};
const COLORS = ['#e6194b','#3cb44b','#4363d8','#f58231','#911eb4','#008080'];
const BLOCK_W = 132, PORT_SPACING = 22, TOP_PAD = 18, BOTTOM_PAD = 12;
function blockDims(type) {
  const bt = state.blockTypes[type] || {n_inputs:1, n_outputs:1};
  const n = Math.max(bt.n_inputs||0, bt.n_outputs||0, 1);
  return {W: BLOCK_W, H: TOP_PAD + n * PORT_SPACING + BOTTOM_PAD};
}
function inputPort(b, i) { const {H} = blockDims(b.type); return {x: b.x, y: b.y + TOP_PAD + (i+0.5)*PORT_SPACING}; }
function outputPort(b, j) { return {x: b.x + BLOCK_W, y: b.y + TOP_PAD + (j+0.5)*PORT_SPACING}; }
function blockById(id) { return state.blocks.find(b => b.id === id); }
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
function resizeCanvas() {
  const wrap = canvas.parentElement;
  canvas.width = wrap.clientWidth; canvas.height = wrap.clientHeight; draw();
}
window.addEventListener('resize', resizeCanvas);
function canvasPos(ev) { const r = canvas.getBoundingClientRect(); return {x: ev.clientX - r.left, y: ev.clientY - r.top}; }
function setStatus(kind, text) {
  const el = document.getElementById('statusbar');
  el.textContent = text; el.className = (kind === 'error') ? 'error' : '';
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
    setStatus('info', 'Add Bend mode: click a segment to add a detour. Esc to exit.');
  } else if (state.bendEditMode === null) {
    setStatus('info', 'Bend mode off.');
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
    setStatus('info', 'Reset Route mode: click a connection to reset its route. Esc to exit.');
  } else if (state.bendEditMode === null) {
    setStatus('info', 'Bend mode off.');
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
  ctx.fillText((b.id+' · '+(bt.display_name || b.type)).slice(0,22), b.x+W/2, b.y+12);
  if (isGraph) { ctx.font='10px system-ui,sans-serif'; ctx.fillStyle='#c2185b'; ctx.fillText('plot', b.x+W/2, b.y+H-8); }
  else if (stateful) { ctx.font='10px system-ui,sans-serif'; ctx.fillStyle='#2f6fb3'; ctx.fillText(bt.state_kind, b.x+W/2, b.y+H-8); }
  const nIn=bt.n_inputs||0, nOut=bt.n_outputs||0;
  for (let i=0;i<nIn;i++){const p=inputPort(b,i);ctx.beginPath();ctx.arc(p.x,p.y,5,0,Math.PI*2);ctx.fillStyle='#3cb44b';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();}
  for (let j=0;j<nOut;j++){const p=outputPort(b,j);ctx.beginPath();ctx.arc(p.x,p.y,5,0,Math.PI*2);ctx.fillStyle='#e6194b';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();}
  if (bt.input_labels) {
    ctx.font='11px system-ui,sans-serif'; ctx.fillStyle='#1c2733'; ctx.textAlign='left';
    bt.input_labels.forEach((label,i)=>{const p=inputPort(b,i);ctx.fillText(label,p.x+9,p.y);});
    ctx.textAlign='center';
  }
  if (bt.output_labels) {
    ctx.font='11px system-ui,sans-serif'; ctx.fillStyle='#1c2733'; ctx.textAlign='right';
    bt.output_labels.forEach((label,i)=>{const p=outputPort(b,i);ctx.fillText(label,p.x-9,p.y);});
    ctx.textAlign='center';
  }
}
function draw() {
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle='#eef2f6'; ctx.lineWidth=1;
  for(let x=0;x<canvas.width;x+=24){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,canvas.height);ctx.stroke();}
  for(let y=0;y<canvas.height;y+=24){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(canvas.width,y);ctx.stroke();}
  state.connections.forEach((c,idx)=>{
    const pts=routePoints(c); if(!pts)return;
    const sel=state.selected&&state.selected.kind==='conn'&&state.selected.index===idx;
    drawConnection(pts,sel);
  });
  if(state.pendingConn&&state._mouse){const from=blockById(state.pendingConn.from);if(from){const p1=outputPort(from,state.pendingConn.fromPort);drawConnection([p1].concat(defaultRoute(p1,state._mouse)).concat([state._mouse]),false,true);}}
  state.blocks.forEach(b=>drawBlock(b));
  if(state.placingType&&state._mouse){const{W,H}=blockDims(state.placingType);ctx.globalAlpha=0.5;ctx.fillStyle='#cfe3f7';ctx.strokeStyle='#2f6fb3';ctx.lineWidth=1.5;roundRect(ctx,state._mouse.x-W/2,state._mouse.y-H/2,W,H,8);ctx.fill();ctx.stroke();ctx.globalAlpha=1;}
}

// ---- hit testing ---------------------------------------------------------
function portAt(x, y) {
  for (const b of state.blocks) {
    const bt = state.blockTypes[b.type] || {};
    const nIn = bt.n_inputs || 0, nOut = bt.n_outputs || 0;
    for (let i = 0; i < nIn; i++) { const p = inputPort(b, i); if (Math.hypot(p.x - x, p.y - y) < 9) return {block: b, kind: 'in', index: i}; }
    for (let j = 0; j < nOut; j++) { const p = outputPort(b, j); if (Math.hypot(p.x - x, p.y - y) < 9) return {block: b, kind: 'out', index: j}; }
  }
  return null;
}
// ---- connector tooltips (HTML tooltip div) --------------------------------
const portTooltipEl = document.getElementById('port_tooltip');
function portTooltip(port) {
  const dir = port.kind === 'in' ? 'Input' : 'Output';
  const bt = state.blockTypes[port.block && port.block.type] || {};
  const labels = port.kind === 'in' ? bt.input_labels : bt.output_labels;
  if (labels && labels[port.index]) return labels[port.index];
  return dir + ' ' + (port.index + 1);
}
function updateCanvasTooltip(x, y) {
  const port = portAt(x, y);
  if (port) {
    portTooltipEl.textContent = portTooltip(port);
    portTooltipEl.style.left = (x + 12) + 'px';
    portTooltipEl.style.top = (y - 28) + 'px';
    portTooltipEl.classList.remove('hidden');
  } else {
    portTooltipEl.classList.add('hidden');
  }
}
function blockAt(x, y) {
  for (let i = state.blocks.length - 1; i >= 0; i--) {
    const b = state.blocks[i]; const {W, H} = blockDims(b.type);
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
    if (['subsystem','experiment'].includes(b.type) && b.internal) {
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
function deserializeBlocks(arr) {
  return (arr || []).map(b => {
    const o = {
      id: String(b.id), type: b.type, params: Object.assign({}, b.params || {}),
      x: Number(b.x) || 0, y: Number(b.y) || 0,
    };
    if (['subsystem','experiment'].includes(b.type) && b.internal) {
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
  state.bendEditMode = null; state.drag = null;
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
  const sub = state.blocks.find(b => b.id === subId && ['subsystem','experiment'].includes(b.type));
  const parentView=state.activeView;
  if (!sub) { setStatus('error', 'Subsystem not found: ' + subId); return; }
  if (!sub.internal) {
    sub.internal = {blocks: [], connections: []};
    if (sub.type==='experiment') {
      [0,1,2].forEach(port=>sub.internal.blocks.push({id:'P'+(port+1),type:'experiment_input',params:{port},x:40,y:70+port*90}));
      sub.internal.blocks.push({id:'J',type:'experiment_result',params:{},x:430,y:70});
      sub.internal.blocks.push({id:'Goal',type:'objective',params:{objective:'iae',target:1,tolerance:.02},x:230,y:70});
      sub.internal.connections.push({from:'P1',fromPort:0,to:'Goal',toPort:0},{from:'Goal',fromPort:0,to:'J',toPort:0});
    } else {
    // Create default In1 -> Out1 identity path
    sub.internal.blocks.push({id: 'In1', type: 'in1_terminal', params: {}, x: 40, y: 120});
    sub.internal.blocks.push({id: 'Out1', type: 'out1_terminal', params: {}, x: 300, y: 120});
    sub.internal.connections.push({from: 'In1', fromPort: 0, to: 'Out1', toPort: 0});
    }
  }
  if (sub.type==='experiment') {
    state.outerControls=['t_end','h','method'].map(id=>document.getElementById(id).value);
    ['t_end','h','method'].forEach(id=>document.getElementById(id).value=sub.params[id] ?? (id==='t_end'?10:id==='h'?.02:'rk4'));
  }
  state.blocks = sub.internal.blocks;
  state.connections = sub.internal.connections;
  state.activeView = subId;
  if(parentView)state.activeView=parentView+'/'+subId;
  // Clear stale interaction state
  state.selected = null; state.placingType = null; state.pendingConn = null;
  state.bendEditMode = null; state.drag = null;
  updateModeButtons();
  updateBackButton();
  // Set nextId for this view
  let mx = 0;
  state.blocks.forEach(b => { const m = /^b(\d+)$/.exec(b.id); if (m) mx = Math.max(mx, parseInt(m[1], 10)); });
  state.nextId = mx + 1;
  draw();
  setStatus('ok', sub.type==='experiment' ? 'Внутри эксперимента '+subId+'. Run запускает только этот прогон.' : "Inside subsystem '"+subId+"'. Press Back to return to parent.");
}
function exitSubsystem() {
  if(state.activeView && state.activeView.includes('/')) {
    state.activeView=state.activeView.split('/').slice(0,-1).join('/');
    const parent=containerForView(state.activeView);state.blocks=parent.internal.blocks;state.connections=parent.internal.connections;
    state.selected=null;state.drag=null;state.pendingConn=null;state.placingType=null;state.bendEditMode=null;
    state.nextId=1+state.blocks.reduce((n,b)=>{const match=/^b(\d+)$/.exec(b.id);return Math.max(n,match?Number(match[1]):0);},0);
    updateModeButtons();updateBackButton();draw();return;
  }
  if (state.outerControls) {['t_end','h','method'].forEach((id,i)=>document.getElementById(id).value=state.outerControls[i]);state.outerControls=null;}
  state.blocks = state.rootBlocks;
  state.connections = state.rootConnections;
  state.activeView = null;
  state.selected = null; state.placingType = null; state.pendingConn = null;
  state.bendEditMode = null; state.drag = null;
  updateModeButtons();
  updateBackButton();
  let mx = 0;
  state.blocks.forEach(b => { const m = /^b(\d+)$/.exec(b.id); if (m) mx = Math.max(mx, parseInt(m[1], 10)); });
  state.nextId = mx + 1;
  draw();
  setStatus('ok', 'Back to parent diagram.');
}
function updateBackButton() {
  const btn = document.getElementById('back_to_parent');
  if (btn) btn.classList.toggle('hidden', !state.activeView);
  const current=containerForView(state.activeView);
  const batch=!state.activeView && (state.rootBlocks || state.blocks).some(b=>b.type==='experiment');
  ['t_end','h','method'].forEach(id=>{const el=document.getElementById(id);if(el.closest)el.closest('label').style.display=batch?'none':'';});
  const settings=document.getElementById('experiment_settings');
  if(settings)settings.classList.toggle('hidden',!current || current.type!=='experiment');
}
function resultKeyForBlock(block) {
  if (state.activeView) return state.activeView + '/' + block.id;
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

// ---- library (file-system tree) -------------------------------------------
async function loadBlockTypes() {
  const data = await api('/api/blocks');
  state.blockTypes = {};
  (data.blocks || []).forEach(bt => { state.blockTypes[bt.name] = bt; });
  // Boundary terminals (not in library, hardcoded dimensions for rendering)
  state.blockTypes['experiment_input']={name:'experiment_input',display_name:'Параметр эксперимента',n_inputs:0,n_outputs:1,parameters:{port:0},output_labels:['p']};
  state.blockTypes['experiment_result']={name:'experiment_result',display_name:'Итоговая оценка',n_inputs:1,n_outputs:0,parameters:{},input_labels:['J']};
  state.blockTypes['in1_terminal'] = {name:'in1_terminal', display_name:'Вход подсистемы', input_labels:[], output_labels:['In1'], n_inputs:0, n_outputs:1, state_kind:'none', parameters:{}};
  state.blockTypes['out1_terminal'] = {name:'out1_terminal', display_name:'Выход подсистемы', input_labels:['Out1'], output_labels:[], n_inputs:1, n_outputs:0, state_kind:'none', parameters:{}};
}
async function loadLibrary() {
  const data = await api('/api/library');
  state.libraryTree = data.tree || [];
  await loadBlockTypes();
  renderLibraryTree();
  if (data.load_errors && data.load_errors.length) {
    const msg = data.load_errors.map(e => e[0] + ': ' + e[1]).join('; ');
    setStatus('error', 'Some block files failed to load: ' + msg);
  }
}
function renderLibraryTree() {
  const root = document.getElementById('library_tree');
  root.innerHTML = '';
  const ul = document.createElement('ul'); ul.className = 'tree';
  (state.libraryTree || []).forEach(node => ul.appendChild(renderNode(node)));
  root.appendChild(ul);
}
function renderNode(node) {
  const li = document.createElement('li');
  if (node.type === 'category') {
    const row = document.createElement('div'); row.className = 'tree-category';
    const arrow = document.createElement('span'); arrow.className = 'arrow'; arrow.textContent = '\u25be';
    row.appendChild(arrow); row.appendChild(document.createTextNode(node.name));
    const ul = document.createElement('ul'); ul.className = 'tree-blocks';
    (node.blocks || []).forEach(name => {
      const b = document.createElement('li'); b.className = 'tree-block'; b.textContent = (state.blockTypes[name] || {}).display_name || name;
      b.title = (state.blockTypes[name] || {}).description || name;
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
  state.placingType = name;
  document.querySelectorAll('.tree-block.active').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tree-block').forEach(el => { if (el.textContent === name) el.classList.add('active'); });
  setStatus('info', "Placing '" + name + "' \u2014 click the canvas to drop it (Esc to cancel).");
}

// ---- simulation -----------------------------------------------------------
async function runSim() {
  if (state.blocks.length === 0) {
    setStatus('error', 'Nothing to simulate: the diagram is empty.');
    return;
  }
  setStatus('info', 'Running simulation\u2026');
  try {
    const body = {
      model: toModelDict(),
      t_end: parseFloat(document.getElementById('t_end').value),
      h: parseFloat(document.getElementById('h').value),
      method: document.getElementById('method').value,
    };
    const active=(state.rootBlocks || []).find(b=>b.id===(state.activeView || '').split('/')[0] && b.type==='experiment');
    if(active)body.experiment=active.id;
    const fingerprint = JSON.stringify(body.model);
    if (body.model.blocks.some(b=>b.type==='experiment')) setStatus('info','Выполняю независимые эксперименты и подбор…');
    const data = await api('/api/simulate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const tuning = data.optimization || [];
    if ((tuning.length || (data.experiments || []).length) && JSON.stringify(toModelDict()) !== fingerprint) {
      setStatus('error', 'Схема изменилась во время подбора. Повторите Run.'); return;
    }
    tuning.forEach(report=>{
      let nodes=state.rootBlocks || state.blocks;
      const parts=report.block_id.split('/');
      parts.forEach((part,i)=>{
        const block=nodes.find(b=>String(b.id)===part);
        if (!block) return;
        if (i===parts.length-1) Object.assign(block.params,report.values);
        else nodes=(block.internal || {}).blocks || [];
      });
    });
    draw();
    state.lastRunId=data.run_id;
    state.lastResults = data.results || {};
    updateGraphWindows();
    const nGraph = state.blocks.filter(b => b.type.startsWith('graph_')).length;
    setStatus('ok', (data.experiments && data.experiments.length ? data.experiments.map(e=>e.block_id+': J='+e.result.toPrecision(5)+'; t_end='+e.t_end+', h='+e.h+', '+e.method.toUpperCase()).join('\n') : 'Simulation finished: '+data.n_steps+' steps, '+Object.keys(state.lastResults).length+' signals recorded.') +
      (nGraph ? ' Double-click a graph block to view its plot in a separate window.' : '') +
      tuning.map(r=>'\n'+r.block_id+': '+Object.entries(r.values).map(([k,v])=>k+'='+v.toPrecision(5)).join(', ')+
        '; расчётов '+r.evaluations+(r.experiment_id ? '; итоговая J='+r.score.toPrecision(5)+'.' : r.converged ? '; уставка достигнута.' : '; удержание уставки не достигнуто.')).join(''));
    const links=document.createElement('div');
    state.blocks.filter(b=>b.type.startsWith('graph_')).forEach(b=>{
      const a=document.createElement('a');a.textContent='Открыть '+(b.params.label || b.id)+' · ';
      a.href='/plot.html?run='+encodeURIComponent(state.lastRunId)+'&block='+encodeURIComponent(resultKeyForBlock(b));a.target='_blank';links.appendChild(a);
    });
    document.getElementById('statusbar').appendChild(links);

  } catch (err) {
    setStatus('error', 'Simulation failed: ' + err.message);
  }
}

// ---- save / load ----------------------------------------------------------
async function saveModel() {
  const name = document.getElementById('model_name').value.trim();
  if (!name) { setStatus('error', 'Enter a model name before saving.'); return; }
  try {
    await api('/api/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, model: toModelDict()}),
    });
    await refreshModels(name);
    setStatus('ok', "Model '" + name + "' saved.");
  } catch (err) {
    setStatus('error', 'Save failed: ' + err.message);
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
  if (!name) { setStatus('error', 'Choose a model to load.'); return; }
  try {
    const data = await api('/api/load?name=' + encodeURIComponent(name));
    const missing = [];
    (data.model.blocks || []).forEach(b => {
      if (!state.blockTypes[b.type]) missing.push(b.type);
      if (b.internal && b.internal.blocks) {
        b.internal.blocks.forEach(ib => { if (!state.blockTypes[ib.type]) missing.push(ib.type); });
      }
    });
    if (missing.length) {
      const uniq = Array.from(new Set(missing));
      setStatus('error', "Cannot load '" + name + "': missing block implementation(s): " + uniq.join(', ') +
        '. Add the block file(s) to the library and press Refresh, or remove those blocks.');
      return;
    }
    fromModelDict(data.model);
    draw();
    document.getElementById('model_name').value = name;
    setStatus('ok', "Model '" + name + "' loaded (" + state.blocks.length + ' blocks, ' + state.connections.length + ' connections).');
  } catch (err) {
    setStatus('error', 'Load failed: ' + err.message);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ---- graph windows (separate browser windows) -----------------------------
function openGraphWindow(block) {
  const key=resultKeyForBlock(block);
  const url='/plot.html?run='+encodeURIComponent(state.lastRunId || '')+'&block='+encodeURIComponent(key);
  const existing=state.graphWindows[key];
  if(existing&&!existing.closed){existing.location.href=url;try{existing.focus();}catch(e){}return existing;}
  const win=window.open(url,'_blank','width=860,height=600');
  if(!win){setStatus('error','Разрешите открытие окна графика.');return null;}
  state.graphWindows[key]=win;return win;
}

function updateGraphWindows() {
  Object.entries(state.graphWindows).forEach(([key,win])=>{
    if(win.closed){delete state.graphWindows[key];return;}
    if (!state.lastResults[key]) return;
    win.location.href='/plot.html?run='+encodeURIComponent(state.lastRunId || '')+'&block='+encodeURIComponent(key);
  });
}

// ---- parameters dialog ----------------------------------------------------
let dialogBlock = null;
function openDialog(block) {
  dialogBlock = block;
  const bt = state.blockTypes[block.type] || {parameters: {}};
  document.getElementById('dialog_title').textContent = block.id + ' \u2014 ' + (bt.display_name || block.type);
  const body = document.getElementById('dialog_body');
  body.innerHTML = '';
  const params = bt.parameters || {};
  const keys = Object.keys(params);
  if (keys.length === 0) {
    const p = document.createElement('p');
    p.textContent = 'This block has no parameters.';
    body.appendChild(p);
  }
  keys.forEach(k => {
    const def = params[k];
    const label = document.createElement('label');
    label.appendChild(document.createTextNode((bt.parameter_labels && bt.parameter_labels[k] || k) + ' '));
    let input;
    if (typeof def === 'boolean') {
      input = document.createElement('input'); input.type = 'checkbox';
    } else if (bt.parameter_choices && bt.parameter_choices[k]) {
      input = document.createElement('select');
      bt.parameter_choices[k].forEach(choice=>{const o=document.createElement('option');o.value=choice.value;o.textContent=choice.label;input.appendChild(o);});
    } else if (typeof def === 'string') {
      if (k === 'type' && block.type === 'signal_generator') {
        input = document.createElement('select');
        ['sine', 'square', 'ramp', 'step'].forEach(v => {
          const o = document.createElement('option'); o.value = v; o.textContent = v;
          input.appendChild(o);
        });
      } else {
        input = document.createElement('input'); input.type = 'text';
      }
    } else {
      input = document.createElement('input'); input.type = 'number'; input.step = 'any';
    }
    input.value = (block.params && k in block.params) ? block.params[k] : def;
    if (typeof def === 'boolean') input.checked = (block.params && k in block.params) ? Boolean(block.params[k]) : def;
    input.id = 'dlg_' + k;
    if(k==='x_range' || k==='y_range'){input.placeholder='авто или 0:5';input.title='Пустая строка — автомасштаб. Формат: минимум:максимум.';}
    if(k==='algorithm_options'){input.placeholder='initial_step=0.1; tolerance=0.0005';input.title='Поиск в нормированных координатах. У тяжёлого шарика initial_step умножает градиент, momentum задаёт инерцию. Пустая строка: настройки по умолчанию.';}
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
      dialogBlock.params[k] = el.value;
    }
  });
  const owner=dialogBlock;
  closeDialog();
  if(owner.type==='experiment' && state.activeView===owner.id) ['t_end','h','method'].forEach(id=>document.getElementById(id).value=owner.params[id]);
  draw();
  setStatus('ok', "Parameters updated for '" + id + "'.");
}

// ---- block deletion --------------------------------------------------------
function deleteBlock(id) {
  const b = state.blocks.find(x => x.id === id);
  if (!b) return;
  // Protect boundary terminals from deletion
  if (['in1_terminal','out1_terminal','experiment_input','experiment_result'].includes(b.type)) {
    setStatus('error', 'Boundary terminal ' + id + ' cannot be deleted. It is mandatory for the subsystem.');
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
  setStatus('ok', "Removed block '" + id + "'.");
}
function deleteConnection(idx) {
  state.connections.splice(idx, 1);
  state.selected = null;
  draw();
  setStatus('ok', 'Connection removed.');
}

// ---- canvas events --------------------------------------------------------
canvas.addEventListener('mousemove', ev => {
  const p = canvasPos(ev);
  state._mouse = p;
  updateCanvasTooltip(p.x, p.y);
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
  const p = canvasPos(ev);
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
  }
});
canvas.addEventListener('mouseup', ev => {
  if (ev.button !== 0) return;
  const p = canvasPos(ev);
  if (state.pendingConn) {
    const port = portAt(p.x, p.y);
    if (port && port.kind === 'in' && port.block.id !== state.pendingConn.from) {
      const occupied = state.connections.find(c => c.to === port.block.id && c.toPort === port.index);
      if (occupied) {
        const same = occupied.from === state.pendingConn.from && occupied.fromPort === state.pendingConn.fromPort;
        setStatus(same ? 'info' : 'error', same ? 'Этот провод уже подключён.' :
          'Вход '+port.block.id+' ('+(port.index+1)+') занят. Удалите прежний провод или используйте сумматор.');
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
canvas.addEventListener('click', ev => {
  const p = canvasPos(ev);
  if (state.bendEditMode) return;
  if (state.placingType) {
    // Prevent placing subsystem inside a subsystem (one-level restriction)
    if (state.activeView && (state.placingType==='experiment' || (state.placingType==='subsystem' && containerForView(state.activeView).type!=='experiment'))) {
      setStatus('error', 'Cannot place a Subsystem inside another Subsystem (one-level hierarchy only).');
      state.placingType = null;
      document.querySelectorAll('.tree-block.active').forEach(el => el.classList.remove('active'));
      return;
    }
    const bt = state.blockTypes[state.placingType];
    if (!bt) {
      setStatus('error', "Block '" + state.placingType + "' is not available (implementation missing). Press Refresh in the library.");
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
    setStatus('ok', "Placed '" + block.type + "' as " + id + '.');
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
  const p = canvasPos(ev);
  const b = blockAt(p.x, p.y);
  if (!b) return;
  if (['subsystem','experiment'].includes(b.type)) {
    // Double-click a subsystem: open its internal canvas
    enterSubsystem(b.id);
  } else if (b.type.startsWith('graph_')) {
    openGraphWindow(b);
  } else if (['in1_terminal','out1_terminal','experiment_input','experiment_result'].includes(b.type)) {
    setStatus('info', 'Boundary terminal ' + b.id + ' cannot be edited.');
  } else {
    openDialog(b);
  }
});
canvas.addEventListener('contextmenu', ev => {
  ev.preventDefault();
  const p = canvasPos(ev);
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
      setStatus('info', 'Bend mode off.');
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
  if(!block){setStatus('info','Выберите блок для настройки.');return;}
  if(['in1_terminal','out1_terminal','experiment_input','experiment_result'].includes(block.type)){setStatus('info','Граничный терминал не редактируется.');return;}
  openDialog(block);
}
// ---- toolbar wiring -------------------------------------------------------
document.getElementById('back_to_parent').addEventListener('click', exitSubsystem);
document.getElementById('edit_bends').addEventListener('click', toggleBendEditMode);
document.getElementById('reset_route').addEventListener('click', toggleResetRouteMode);
document.getElementById('block_params').addEventListener('click',editSelectedBlock);
document.getElementById('run').addEventListener('click', runSim);
document.getElementById('save').addEventListener('click', saveModel);
document.getElementById('load').addEventListener('click', loadModel);
document.getElementById('clear').addEventListener('click', () => {
  if (state.blocks.length === 0) { setStatus('info', 'Diagram is already empty.'); return; }
  if (!confirm('Clear the whole diagram?')) return;
  state.blocks = state.rootBlocks = [];
  state.connections = state.rootConnections = [];
  state.activeView = null; state.selected = null; state.lastResults = null;
  updateBackButton();
  for (const bid of Object.keys(state.graphWindows)) {
    const win = state.graphWindows[bid];
    if (win && !win.closed) { try { win.close(); } catch (e) {} }
    delete state.graphWindows[bid];
  }
  draw();
  setStatus('ok', 'Diagram cleared.');
});
document.getElementById('library_refresh').addEventListener('click', async () => {
  setStatus('info', 'Refreshing library from disk\u2026');
  try {
    await loadLibrary();
    setStatus('ok', 'Library refreshed from the file system.');
  } catch (err) {
    setStatus('error', 'Library refresh failed: ' + err.message);
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
    setStatus('error', 'Could not load the block library: ' + err.message);
  }
  await refreshModels();
  draw();
})();

['t_end','h','method'].forEach(id=>document.getElementById(id).addEventListener('change',()=>{
 const owner=(state.rootBlocks || []).find(b=>b.id===(state.activeView || '').split('/')[0] && b.type==='experiment');
 if(owner)owner.params[id]=id==='method'?document.getElementById(id).value:Number(document.getElementById(id).value);
}));
document.getElementById('experiment_settings').addEventListener('click',()=>{
 const owner=(state.rootBlocks || []).find(b=>b.id===(state.activeView || '').split('/')[0] && b.type==='experiment');
 if(owner)openDialog(owner);
});
