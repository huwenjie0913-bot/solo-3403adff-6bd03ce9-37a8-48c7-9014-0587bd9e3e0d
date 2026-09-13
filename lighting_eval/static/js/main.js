/* 文物摄影布光评估 —— 前端（原生 JS）
 * 画布：世界坐标 y 向上（米），屏幕坐标 y 向下（像素）。
 */
'use strict';

const $ = s => document.querySelector(s);
const canvas = $('#plan');
const ctx = canvas.getContext('2d');

const SENS = {
  paper: { lux_limit: 50, dose_limit: 120000 },
  medium: { lux_limit: 150, dose_limit: 360000 },
  insensitive: { lux_limit: 300, dose_limit: 1e12 },
};

const state = {
  config: defaultConfig(),
  view: { scale: 70, ox: 80, oy: 60 },
  selected: null,        // 设备对象或 'camera'
  result: null,
  trace: null,           // {surface, index}
  schemes: [],
  overlayConfig: null,   // 方案 B 叠加
  showHeat: true,
  idSeq: 1,
};

function defaultConfig() {
  return {
    room: { w: 10, h: 7 },
    settings: {
      target_min: 50, target_max: 50, uniformity_min: 0.6,
      hours_per_day: 8, grid: 0.25, sensitivity: 'paper',
      lux_limit: 50, dose_limit: 120000, glare_limit: 25,
    },
    camera: { x: 5, y: 1.2, z: 1.6 },
    devices: [
      { id: 'case1', type: 'case', name: '展柜A', x: 5, y: 4, w: 2.4, d: 1.2, h: 2.2,
        rot: 0, opaque: false, transmission: 0.9 },
      { id: 'bg1', type: 'background', name: '背景板', x: 5, y: 5.4, w: 3, d: 0.12,
        h: 2.6, rot: 0, opaque: true },
      { id: 'lamp1', type: 'lamp', name: '灯1', x: 3.6, y: 2.6, z: 3, power: 35,
        cct: 3000, beam: 36, efficacy: 90, aim: { x: 4.6, y: 4, z: 0.4 }, locked: false },
      { id: 'lamp2', type: 'lamp', name: '灯2', x: 6.4, y: 2.6, z: 3, power: 35,
        cct: 3000, beam: 36, efficacy: 90, aim: { x: 5.4, y: 4, z: 0.4 }, locked: false },
    ],
  };
}

/* ---------- 坐标变换 ---------- */
function w2s(x, y) {
  const v = state.view, H = state.config.room.h;
  return [v.ox + x * v.scale, v.oy + (H - y) * v.scale];
}
function s2w(sx, sy) {
  const v = state.view, H = state.config.room.h;
  return [(sx - v.ox) / v.scale, H - (sy - v.oy) / v.scale];
}
function evtWorld(e) {
  const r = canvas.getBoundingClientRect();
  return s2w(e.clientX - r.left, e.clientY - r.top);
}

/* ---------- 画布尺寸 ---------- */
function resize() {
  const wrap = $('#canvasWrap');
  const dpr = window.devicePixelRatio || 1;
  canvas.width = wrap.clientWidth * dpr;
  canvas.height = wrap.clientHeight * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}
window.addEventListener('resize', resize);

/* ---------- 绘制 ---------- */
function draw() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  ctx.clearRect(0, 0, w, h);
  const room = state.config.room;

  // 房间
  const [rx0, ry0] = w2s(0, room.h);
  const [rx1, ry1] = w2s(room.w, 0);
  ctx.fillStyle = '#fff';
  ctx.fillRect(rx0, ry0, rx1 - rx0, ry1 - ry0);
  // 1m 网格
  ctx.strokeStyle = '#f0f0f0';
  ctx.lineWidth = 1;
  for (let i = 1; i < room.w; i++) line(w2s(i, 0), w2s(i, room.h));
  for (let j = 1; j < room.h; j++) line(w2s(0, j), w2s(room.w, j));
  ctx.strokeStyle = '#333';
  ctx.lineWidth = 2;
  ctx.strokeRect(rx0, ry0, rx1 - rx0, ry1 - ry0);

  // 叠加方案 B（虚线灰影）
  if (state.overlayConfig) {
    ctx.save();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = '#9ca3af';
    ctx.fillStyle = 'rgba(156,163,175,0.12)';
    for (const d of state.overlayConfig.devices || []) drawDevice(d, true);
    ctx.restore();
  }

  // 设备
  for (const d of state.config.devices) drawDevice(d, false);

  // 相机
  const cam = state.config.camera;
  if (cam) {
    const [cx, cy] = w2s(cam.x, cam.y);
    ctx.fillStyle = state.selected === 'camera' ? '#059669' : '#10b981';
    ctx.beginPath();
    ctx.moveTo(cx, cy - 9); ctx.lineTo(cx + 8, cy + 6); ctx.lineTo(cx - 8, cy + 6);
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#065f46';
    ctx.font = '10px sans-serif';
    ctx.fillText('相机', cx + 10, cy + 4);
  }

  // 热区
  if (state.showHeat && state.result) drawHeat();

  // 追溯点高亮
  if (state.trace && state.result) {
    const s = state.result.surfaces.find(x => x.id === state.trace.surface);
    if (s && s.points[state.trace.index]) {
      const p = heatPointPos(s, s.points[state.trace.index]);
      ctx.strokeStyle = '#7c3aed';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(p[0], p[1], 9, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
}

function line(a, b) {
  ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
}

function drawDevice(d, ghost) {
  const sel = !ghost && state.selected === d;
  const [cx, cy] = w2s(d.x, d.y);
  const sc = state.view.scale;
  ctx.save();
  if (d.type === 'case' || d.type === 'background') {
    ctx.translate(cx, cy);
    ctx.rotate(-(d.rot || 0) * Math.PI / 180);
    const w = d.w * sc, dd = Math.max(d.d || 0.1, 0.06) * sc;
    if (!ghost) {
      ctx.fillStyle = d.type === 'case' ? 'rgba(37,99,235,0.15)' : 'rgba(75,85,99,0.35)';
      ctx.strokeStyle = sel ? '#dc2626' : (d.type === 'case' ? '#2563eb' : '#4b5563');
    }
    ctx.lineWidth = sel ? 2.5 : 1.5;
    ctx.fillRect(-w / 2, -dd / 2, w, dd);
    ctx.strokeRect(-w / 2, -dd / 2, w, dd);
    ctx.rotate((d.rot || 0) * Math.PI / 180); // 文字保持水平
    if (!ghost) {
      ctx.fillStyle = '#1e3a8a';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(d.name || d.id, 0, 3);
      ctx.textAlign = 'left';
    }
  } else if (d.type === 'lamp') {
    // 瞄准线
    const a = d.aim || { x: d.x, y: d.y };
    const [ax, ay] = w2s(a.x, a.y);
    if (!ghost) {
      ctx.strokeStyle = '#f59e0b';
      ctx.setLineDash([4, 3]);
      line([cx, cy], [ax, ay]);
      ctx.setLineDash([]);
      ctx.strokeStyle = '#b45309';
      ctx.beginPath(); ctx.arc(ax, ay, 3, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.fillStyle = ghost ? ctx.fillStyle : '#fbbf24';
    ctx.strokeStyle = sel ? '#dc2626' : '#b45309';
    ctx.lineWidth = sel ? 2.5 : 1.5;
    ctx.beginPath(); ctx.arc(cx, cy, 7, 0, Math.PI * 2);
    ctx.fill(); ctx.stroke();
    if (!ghost) {
      ctx.fillStyle = '#92400e';
      ctx.font = '10px sans-serif';
      ctx.fillText(`${d.name || d.id} ${d.power}W/${d.cct}K${d.locked ? ' 🔒' : ''}`, cx + 10, cy - 8);
    }
  }
  ctx.restore();
}

function heatPointPos(surface, p) {
  // 背板点沿法线外移一点，避免与展柜边线重叠
  const off = surface.plane === 'back' ? 0.12 : 0;
  const n = surface.normal || [0, 0, 0];
  return w2s(p.x + n[0] * off, p.y + n[1] * off);
}

function drawHeat() {
  const sc = state.view.scale;
  const size = Math.max(4, Math.min(14, (state.config.settings.grid || 0.25) * sc * 0.8));
  for (const s of state.result.surfaces) {
    for (const p of s.points) {
      const [sx, sy] = heatPointPos(s, p);
      if (p.flag === 'over') ctx.fillStyle = 'rgba(220,38,38,0.75)';
      else if (p.flag === 'under') ctx.fillStyle = 'rgba(245,158,11,0.7)';
      else ctx.fillStyle = 'rgba(16,185,129,0.35)';
      ctx.fillRect(sx - size / 2, sy - size / 2, size, size);
    }
  }
}

/* ---------- 拾取 ---------- */
// 点状可拖放设备（灯具、相机）：小半径命中
function pickPointDevice(wx, wy) {
  const cam = state.config.camera;
  if (cam && Math.hypot(wx - cam.x, wy - cam.y) < 0.3) return 'camera';
  const devs = state.config.devices;
  for (let i = devs.length - 1; i >= 0; i--) {
    const d = devs[i];
    if (d.type === 'lamp' && Math.hypot(wx - d.x, wy - d.y) < 0.3) return d;
  }
  return null;
}

// 面状容器（展柜、背景）：局部坐标矩形命中
function pickRectDevice(wx, wy) {
  const devs = state.config.devices;
  for (let i = devs.length - 1; i >= 0; i--) {
    const d = devs[i];
    if (d.type === 'lamp') continue;
    const r = -(d.rot || 0) * Math.PI / 180;
    const lx = (wx - d.x) * Math.cos(r) - (wy - d.y) * Math.sin(r);
    const ly = (wx - d.x) * Math.sin(r) + (wy - d.y) * Math.cos(r);
    if (Math.abs(lx) <= d.w / 2 + 0.1 && Math.abs(ly) <= Math.max(d.d || 0.1, 0.15) / 2 + 0.1) return d;
  }
  return null;
}

function pickHeat(wx, wy) {
  if (!state.result || !state.showHeat) return null;
  let best = null, bestD = 0.2;
  for (const s of state.result.surfaces) {
    s.points.forEach((p, idx) => {
      const off = s.plane === 'back' ? 0.12 : 0;
      const n = s.normal || [0, 0, 0];
      const dd = Math.hypot(wx - (p.x + n[0] * off), wy - (p.y + n[1] * off));
      if (dd < bestD) { bestD = dd; best = { surface: s.id, index: idx }; }
    });
  }
  return best;
}

/* ---------- 交互 ---------- */
let drag = null;

canvas.addEventListener('pointerdown', e => {
  canvas.setPointerCapture(e.pointerId);
  const [wx, wy] = evtWorld(e);
  if (e.button === 1 || e.button === 2) {
    drag = { type: 'pan', sx: e.clientX, sy: e.clientY, ox: state.view.ox, oy: state.view.oy };
    return;
  }
  // 命中优先级：灯具/相机（可拖放） > 网格热区（追溯） > 展柜/背景容器 > 平移
  const pd = pickPointDevice(wx, wy);
  if (pd) {
    select(pd);
    const locked = pd !== 'camera' && pd.type === 'lamp' && pd.locked;
    if (!locked) {
      const src = pd === 'camera' ? state.config.camera : pd;
      drag = { type: 'move', dev: pd, dx: wx - src.x, dy: wy - src.y, moved: false };
    }
    return;
  }
  const hp = pickHeat(wx, wy);
  if (hp) { doTrace(hp.surface, hp.index); return; }
  const rd = pickRectDevice(wx, wy);
  if (rd) {
    select(rd);
    drag = { type: 'move', dev: rd, dx: wx - rd.x, dy: wy - rd.y, moved: false };
    return;
  }
  select(null);
  drag = { type: 'pan', sx: e.clientX, sy: e.clientY, ox: state.view.ox, oy: state.view.oy };
});

canvas.addEventListener('pointermove', e => {
  if (!drag) return;
  if (drag.type === 'pan') {
    state.view.ox = drag.ox + (e.clientX - drag.sx);
    state.view.oy = drag.oy + (e.clientY - drag.sy);
    draw();
  } else if (drag.type === 'move') {
    const [wx, wy] = evtWorld(e);
    const nx = Math.round((wx - drag.dx) * 20) / 20;  // 5cm 吸附
    const ny = Math.round((wy - drag.dy) * 20) / 20;
    const d = drag.dev;
    if (d === 'camera') {
      state.config.camera.x = clamp(nx, 0, state.config.room.w);
      state.config.camera.y = clamp(ny, 0, state.config.room.h);
    } else {
      const mdx = nx - d.x, mdy = ny - d.y;
      d.x = nx; d.y = ny;
      if (d.type === 'lamp' && d.aim) { d.aim.x += mdx; d.aim.y += mdy; } // 瞄准点随灯移动
    }
    drag.moved = true;
    draw();
  }
});

canvas.addEventListener('pointerup', () => {
  if (drag && drag.type === 'move' && drag.moved) {
    renderProps();
    scheduleEvaluate();
  }
  drag = null;
});

canvas.addEventListener('contextmenu', e => e.preventDefault());

canvas.addEventListener('wheel', e => {
  e.preventDefault();
  const r = canvas.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  const [wx, wy] = s2w(mx, my);
  const f = e.deltaY < 0 ? 1.15 : 1 / 1.15;
  state.view.scale = clamp(state.view.scale * f, 15, 400);
  const [nx, ny] = w2s(wx, wy);
  state.view.ox += mx - nx;
  state.view.oy += my - ny;
  draw();
}, { passive: false });

window.addEventListener('keydown', e => {
  if (e.key === 'Delete' && state.selected && state.selected !== 'camera'
      && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) {
    deleteSelected();
  }
});

function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }

function select(d) {
  state.selected = d;
  renderProps();
  draw();
}

/* ---------- 属性面板 ---------- */
const FIELDS = {
  common: [['name', '名称', 'text'], ['x', 'X (m)', 0.1], ['y', 'Y (m)', 0.1]],
  case: [['w', '宽 (m)', 0.1], ['d', '深 (m)', 0.1], ['h', '高 (m)', 0.1],
         ['rot', '旋转 (°)', 5], ['transmission', '玻璃透过率', 0.05]],
  background: [['w', '宽 (m)', 0.1], ['d', '厚 (m)', 0.02], ['h', '高 (m)', 0.1],
               ['rot', '旋转 (°)', 5]],
  lamp: [['z', '安装高度 (m)', 0.1], ['power', '功率 (W)', 1], ['cct', '色温 (K)', 100],
         ['beam', '光束角 (°)', 1], ['efficacy', '光效 (lm/W)', 5],
         ['aim.x', '瞄准点 X', 0.1], ['aim.y', '瞄准点 Y', 0.1], ['aim.z', '瞄准点 Z', 0.1]],
  camera: [['z', '眼位高度 (m)', 0.1]],
};

function renderProps() {
  const body = $('#propsBody');
  const d = state.selected;
  if (!d) { body.innerHTML = '<span class="muted">未选中设备（点击画布中的设备）</span>'; return; }
  if (d === 'camera') {
    const cam = state.config.camera;
    body.innerHTML = `<div class="props"><h3>相机</h3>${fieldHtml('x', 'X (m)', cam.x, 0.1)}
      ${fieldHtml('y', 'Y (m)', cam.y, 0.1)}${fieldHtml('z', '眼位高度 (m)', cam.z, 0.1)}</div>`;
    bindProps(cam);
    return;
  }
  let html = `<div class="props"><h3>${typeName(d.type)}${d.locked ? ' 🔒' : ''}</h3>`;
  for (const [f, label, step] of FIELDS.common) html += fieldHtml(f, label, d[f], step);
  for (const [f, label, step] of (FIELDS[d.type] || [])) {
    html += fieldHtml(f, label, getPath(d, f), step);
  }
  if (d.type === 'lamp') {
    html += `<label class="full chk"><input type="checkbox" data-field="locked" ${d.locked ? 'checked' : ''}> 锁定灯位（试排其余设备时不移动）</label>`;
  }
  if (d.type === 'case' || d.type === 'background') {
    html += `<label class="full chk"><input type="checkbox" data-field="opaque" ${d.opaque ? 'checked' : ''}> 不透明（完全遮挡光线）</label>`;
  }
  html += '</div>';
  body.innerHTML = html;
  bindProps(d);
}

function typeName(t) {
  return { case: '展柜', background: '背景', lamp: '灯具' }[t] || t;
}

function fieldHtml(f, label, val, step) {
  const type = typeof val === 'string' ? 'text' : 'number';
  return `<label>${label}<input data-field="${f}" type="${type}" step="${step}" value="${val}"></label>`;
}

function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o ? o[k] : undefined), obj);
}
function setPath(obj, path, v) {
  const ks = path.split('.');
  const last = ks.pop();
  const o = ks.reduce((o, k) => o[k], obj);
  o[last] = v;
}

function bindProps(d) {
  $('#propsBody').querySelectorAll('input').forEach(inp => {
    inp.addEventListener('input', () => {
      const f = inp.dataset.field;
      const v = inp.type === 'checkbox' ? inp.checked
        : inp.type === 'number' ? parseFloat(inp.value) || 0 : inp.value;
      setPath(d, f, v);
      draw();
      scheduleEvaluate();
    });
  });
}

/* ---------- 全局设置 ---------- */
function loadSettingsToForm() {
  const s = state.config.settings, r = state.config.room;
  $('#s_roomW').value = r.w; $('#s_roomH').value = r.h;
  $('#s_tmin').value = s.target_min; $('#s_tmax').value = s.target_max;
  $('#s_umin').value = s.uniformity_min; $('#s_hours').value = s.hours_per_day;
  $('#s_grid').value = s.grid; $('#s_glare').value = s.glare_limit;
  $('#s_sens').value = s.sensitivity;
  $('#s_luxlimit').value = s.lux_limit; $('#s_doselimit').value = s.dose_limit;
}

function bindSettings() {
  const s = state.config.settings;
  const bind = (id, fn) => $(id).addEventListener('input', () => { fn(); draw(); scheduleEvaluate(); });
  bind('#s_roomW', () => state.config.room.w = parseFloat($('#s_roomW').value) || 10);
  bind('#s_roomH', () => state.config.room.h = parseFloat($('#s_roomH').value) || 7);
  bind('#s_tmin', () => s.target_min = parseFloat($('#s_tmin').value) || 0);
  bind('#s_tmax', () => s.target_max = parseFloat($('#s_tmax').value) || 0);
  bind('#s_umin', () => s.uniformity_min = parseFloat($('#s_umin').value) || 0);
  bind('#s_hours', () => s.hours_per_day = parseFloat($('#s_hours').value) || 0);
  bind('#s_grid', () => s.grid = parseFloat($('#s_grid').value) || 0.25);
  bind('#s_glare', () => s.glare_limit = parseFloat($('#s_glare').value) || 0);
  bind('#s_luxlimit', () => s.lux_limit = parseFloat($('#s_luxlimit').value) || 0);
  bind('#s_doselimit', () => s.dose_limit = parseFloat($('#s_doselimit').value) || 0);
  $('#s_sens').addEventListener('change', () => {
    s.sensitivity = $('#s_sens').value;
    const p = SENS[s.sensitivity];
    if (p) { s.lux_limit = p.lux_limit; s.dose_limit = p.dose_limit; }
    loadSettingsToForm();
    scheduleEvaluate();
  });
}

/* ---------- 评估 ---------- */
let evalTimer = null;
function scheduleEvaluate() {
  clearTimeout(evalTimer);
  evalTimer = setTimeout(doEvaluate, 350);
}

async function doEvaluate() {
  const res = await fetch('/api/evaluate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(state.config),
  });
  state.result = await res.json();
  state.trace = null;
  renderResults();
  draw();
}

function renderResults() {
  const r = state.result;
  if (!r) return;
  let html = `<div>告警 <b class="${r.summary.warnings ? 'warn' : 'ok'}">${r.summary.warnings}</b> 条 ·
    加权色温 ${r.summary.avg_cct} K · 蓝光损伤系数 ×${r.summary.damage_factor}</div>`;
  for (const s of r.surfaces) {
    const bad = s.warnings.length > 0;
    html += `<h4 class="sub">${esc(s.name)}${bad ? ' <span class="warn">⚠</span>' : ''}</h4>
      <table><tr><th class="l">指标</th><th>值</th><th class="l">要求</th></tr>
      <tr><td class="l">平均照度</td><td>${s.E_avg} lx</td><td class="l">≥ ${r.summary.limits.tmin} lx</td></tr>
      <tr><td class="l">最小/最大</td><td>${s.E_min} / ${s.E_max} lx</td><td class="l">≤ ${r.summary.limits.over_lim} lx</td></tr>
      <tr class="${s.uniformity < r.summary.limits.umin ? 'bad' : ''}"><td class="l">均匀度 U0</td><td>${s.uniformity}</td><td class="l">≥ ${r.summary.limits.umin}</td></tr>
      <tr><td class="l">阴影率</td><td>${(s.shadow_rate * 100).toFixed(0)}%</td><td class="l">—</td></tr>
      <tr class="${s.dose_eff > r.summary.limits.annual_limit ? 'bad' : ''}"><td class="l">年剂量</td><td>${s.dose_year} lx·h</td><td class="l">≤ ${r.summary.limits.annual_limit}</td></tr>
      <tr><td class="l">等效损伤剂量</td><td>${s.dose_eff} lx·h</td><td class="l">（色温修正）</td></tr>
      </table>`;
    if (s.warnings.length) {
      html += '<ul class="warns">' + s.warnings.map(w => `<li>${esc(w)}</li>`).join('') + '</ul>';
    }
  }
  const g = r.glare;
  html += `<h4 class="sub">眩光（摄像机眼位）</h4>
    <div class="${g.warning ? 'warn' : 'ok'}">垂直照度合计 ${g.total} lx（限值 ${g.limit} lx）${g.warning ? ' ⚠ 超限' : ''}</div>`;
  if (g.lamps.length) {
    html += '<div class="muted">可见灯具：' + g.lamps.map(l => `${esc(l.name)} ${l.ev} lx`).join('，') + '</div>';
  }
  $('#resultBody').innerHTML = html;
}

/* ---------- 热区追溯 ---------- */
async function doTrace(surface, index) {
  state.trace = { surface, index };
  const res = await fetch('/api/trace', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config: state.config, surface, index }),
  });
  const t = await res.json();
  if (t.error) { $('#traceBody').textContent = t.error; return; }
  const flagTxt = { ok: '✅ 达标', under: '⚠ 低于目标下限', over: '⚠ 超过上限/光敏阈值' }[t.flag];
  let html = `<div><b>${esc(t.name)}</b> 采样点 (${t.point.x}, ${t.point.y}, z=${t.point.z})</div>
    <div>合计照度 <b>${t.total} lx</b> · ${flagTxt}</div>
    <h4 class="sub">贡献灯具（按贡献排序）</h4>`;
  for (const l of t.lamps) {
    html += `<div class="trace-lamp">
      <div><b>${esc(l.name)}</b>${l.locked ? ' 🔒' : ''} — ${l.E} lx（${l.share}%）${l.T < 1 ? ` · 透过率 ${l.T}` : ''}</div>
      <div class="muted">${l.power}W · ${l.cct}K · 光束角 ${l.beam}° · 光效 ${l.efficacy} lm/W · 高度 ${l.z}m</div>
      <div class="bar"><i style="width:${l.share}%"></i></div>
    </div>`;
  }
  $('#traceBody').innerHTML = html;
  draw();
}

/* ---------- 方案管理 ---------- */
async function loadSchemes() {
  const res = await fetch('/api/schemes');
  state.schemes = await res.json();
  renderSchemes();
}

function renderSchemes() {
  const list = $('#schemeList');
  list.innerHTML = state.schemes.map(s => `
    <div class="scheme-item">
      <span class="nm">#${s.id} ${esc(s.name)}</span>
      <time>${s.created_at || ''}</time>
      <button data-act="load" data-id="${s.id}">载入</button>
      <button data-act="del" data-id="${s.id}" class="danger">删</button>
    </div>`).join('') || '<div class="muted">暂无保存的方案</div>';
  const opts = state.schemes.map(s => `<option value="${s.id}">#${s.id} ${esc(s.name)}</option>`).join('');
  $('#cmpA').innerHTML = opts;
  $('#cmpB').innerHTML = opts;
  if (state.schemes.length > 1) $('#cmpB').value = state.schemes[1].id;
}

$('#schemeList').addEventListener('click', async e => {
  const btn = e.target.closest('button');
  if (!btn) return;
  const id = btn.dataset.id;
  if (btn.dataset.act === 'load') {
    const s = await (await fetch(`/api/schemes/${id}`)).json();
    state.config = s.config;
    state.selected = null;
    state.trace = null;
    loadSettingsToForm();
    renderProps();
    scheduleEvaluate();
  } else if (btn.dataset.act === 'del') {
    await fetch(`/api/schemes/${id}`, { method: 'DELETE' });
    loadSchemes();
  }
});

$('#saveScheme').addEventListener('click', async () => {
  const name = $('#schemeName').value.trim() || `方案 ${new Date().toLocaleString()}`;
  await fetch('/api/schemes', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, config: state.config }),
  });
  $('#schemeName').value = '';
  loadSchemes();
});

$('#doCompare').addEventListener('click', async () => {
  const a = $('#cmpA').value, b = $('#cmpB').value;
  if (!a || !b) return;
  const res = await fetch('/api/compare', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ a: +a, b: +b }),
  });
  const data = await res.json();
  if (data.error) { $('#compareBody').textContent = data.error; return; }
  renderCompare(data);
  // 叠加显示方案 B 的平面布置
  const sb = await (await fetch(`/api/schemes/${b}`)).json();
  state.overlayConfig = sb.config;
  $('#overlayToggle').checked = true;
  draw();
});

$('#overlayToggle').addEventListener('change', async e => {
  if (e.target.checked) {
    const b = $('#cmpB').value;
    if (b) {
      const sb = await (await fetch(`/api/schemes/${b}`)).json();
      state.overlayConfig = sb.config;
    }
  } else {
    state.overlayConfig = null;
  }
  draw();
});

function fmtD(d, key) {
  const cls = d > 0 ? 'bad-d' : d < 0 ? 'good-d' : '';
  // 对“越低越好”的指标反转颜色
  const lowerBetter = ['E_max', 'shadow_rate', 'dose_year', 'dose_eff'];
  const good = lowerBetter.includes(key) ? d < 0 : d > 0;
  return `<td class="${d === 0 ? '' : good ? 'good-d' : 'bad-d'}">${d > 0 ? '+' : ''}${d}</td>`;
}

function renderCompare(data) {
  let html = `<h4 class="sub">方案差异：B「${esc(data.b.name)}」相对 A「${esc(data.a.name)}」</h4>`;
  for (const s of data.diff.surfaces) {
    if (s.missing) { html += `<div class="muted">${esc(s.surface)}：方案 B 中不存在</div>`; continue; }
    html += `<h4 class="sub">${esc(s.surface)}</h4>
      <table><tr><th class="l">指标</th><th>A</th><th>B</th><th>Δ</th></tr>
      ${s.metrics.map(m => `<tr><td class="l">${m.label}</td><td>${m.a}</td><td>${m.b}</td>${fmtD(m.d, m.key)}</tr>`).join('')}
      </table>`;
  }
  const g = data.diff.glare;
  html += `<h4 class="sub">眩光</h4><div>A ${g.a} lx → B ${g.b} lx（Δ ${g.d > 0 ? '+' : ''}${g.d}）</div>`;
  $('#compareBody').innerHTML = html;
}

/* ---------- 设备增删 ---------- */
function nextId(prefix) {
  let n;
  do { n = prefix + (++state.idSeq); } while (state.config.devices.some(d => d.id === n));
  return n;
}

$('#addCase').addEventListener('click', () => {
  const r = state.config.room;
  const d = { id: nextId('case'), type: 'case', name: '展柜' + state.idSeq,
    x: r.w / 2, y: r.h / 2, w: 2, d: 1, h: 2.2, rot: 0, opaque: false, transmission: 0.9 };
  state.config.devices.push(d);
  select(d); scheduleEvaluate();
});
$('#addBg').addEventListener('click', () => {
  const r = state.config.room;
  const d = { id: nextId('bg'), type: 'background', name: '背景' + state.idSeq,
    x: r.w / 2, y: r.h - 1, w: 2.4, d: 0.12, h: 2.5, rot: 0, opaque: true };
  state.config.devices.push(d);
  select(d); scheduleEvaluate();
});
$('#addLamp').addEventListener('click', () => {
  const r = state.config.room;
  const d = { id: nextId('lamp'), type: 'lamp', name: '灯' + state.idSeq,
    x: r.w / 2, y: r.h / 2 - 1, z: 3, power: 35, cct: 3000, beam: 36, efficacy: 90,
    aim: { x: r.w / 2, y: r.h / 2, z: 0.4 }, locked: false };
  state.config.devices.push(d);
  select(d); scheduleEvaluate();
});

$('#lockLamps').addEventListener('click', () => {
  const lamps = state.config.devices.filter(d => d.type === 'lamp');
  const allLocked = lamps.every(l => l.locked);
  lamps.forEach(l => l.locked = !allLocked);
  renderProps(); draw();
});

function deleteSelected() {
  const d = state.selected;
  if (!d || d === 'camera') return;
  state.config.devices = state.config.devices.filter(x => x !== d);
  select(null);
  scheduleEvaluate();
}
$('#delSel').addEventListener('click', deleteSelected);

/* ---------- 导出 ---------- */
$('#exportSvg').addEventListener('click', async () => {
  const res = await fetch('/api/export.svg', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(state.config),
  });
  const blob = await res.blob();
  downloadBlob(blob, 'lighting.svg');
});

$('#exportJson').addEventListener('click', () => {
  const payload = { config: state.config, metrics: state.result };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  downloadBlob(blob, 'lighting.json');
});

function downloadBlob(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------- 其它绑定 ---------- */
$('#showHeat').addEventListener('change', e => { state.showHeat = e.target.checked; draw(); });
$('#evalNow').addEventListener('click', doEvaluate);

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/* ---------- 启动 ---------- */
loadSettingsToForm();
bindSettings();
resize();
loadSchemes();
doEvaluate();
