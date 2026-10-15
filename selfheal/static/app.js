'use strict';
/* ===== helpers ===== */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const PAGE = document.body.dataset.page;
const api = u => fetch(u).then(r => r.json());
const post = (u, b) => fetch(u, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(b || {})}).then(r => r.json()).catch(() => ({}));
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || '#888';
const f1 = v => v == null ? '-' : (+v).toFixed(1);
const sec = v => v == null ? '-' : (+v).toFixed(0) + ' s';
const nice = s => String(s || '').replace(/_/g, ' ');
const chip = (c, t) => `<span class="chip ${esc(c)}">${esc(t ?? nice(c))}</span>`;
const COL = ['#1f6feb', '#d29922', '#2da44e', '#a371f7', '#db61a2'];
const FAULTS = {cpu_overload:'CPU overload', memory_exhaustion:'Memory leak', container_crash:'Container crash', bad_deployment:'Bad deployment', database_failure:'Database failure (database only)'};
let S = null, R = {}, I = {};
try { const t = localStorage.getItem('theme'); if (t && t !== 'auto') document.documentElement.dataset.theme = t; } catch (e) {}
const approve = () => post('/api/approve'), reject = () => post('/api/reject'), ack = () => post('/api/ack');

/* ===== charts (no external libraries -> works offline) ===== */
const fmtN = v => { const a = Math.abs(v); return a >= 1000 ? (v / 1000).toFixed(1) + 'k' : a < 10 && v % 1 ? v.toFixed(2) : Math.round(v); };
function lineChart(cv, series, o = {}) {
  if (!cv) return;
  cv._a = [series, o];
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth || 600, H = o.h || cv.clientHeight || 200;
  cv.width = W * dpr; cv.height = H * dpr;
  const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, H);
  const mini = !!o.mini, L = mini ? 2 : 48, Rr = mini ? 2 : 10, T = mini ? 3 : 10, B = mini ? 3 : 22, iw = W - L - Rr, ih = H - T - B;
  const n = Math.max(0, ...series.map(s => s.data.length)); if (!n) return;
  const tf = o.log ? v => Math.log10(Math.max(v, 0) + 1) : v => v;
  const all = []; series.forEach(s => s.data.forEach(v => { if (v != null) all.push(tf(v)); })); if (o.thr != null) all.push(tf(o.thr));
  if (!all.length) return;
  let mn = o.min != null ? tf(o.min) : Math.min(...all), mx = o.max != null ? tf(o.max) : Math.max(...all);
  if (mx - mn < 1e-9) mx = mn + 1; const pad = (mx - mn) * .08; if (o.min == null) mn -= pad; if (o.max == null) mx += pad;
  const X = i => L + (n <= 1 ? 0 : i / (n - 1) * iw), Y = v => T + ih - (tf(v) - mn) / (mx - mn) * ih;
  c.font = '11px system-ui'; c.lineWidth = 1;
  if (!mini) {
    c.fillStyle = css('--mut'); c.strokeStyle = css('--line');
    for (let k = 0; k <= 4; k++) { const yy = T + ih * k / 4, val = mx - (mx - mn) * k / 4, real = o.log ? Math.pow(10, val) - 1 : val;
      c.beginPath(); c.moveTo(L, yy); c.lineTo(W - Rr, yy); c.stroke(); c.textAlign = 'right'; c.fillText((o.fmt || fmtN)(real), L - 6, yy + 4); }
    if (o.ticks) { c.textAlign = 'center'; [0, Math.floor(n / 2), n - 1].forEach(i => { if (o.ticks[i] != null) c.fillText('t=' + o.ticks[i], Math.min(Math.max(X(i), L + 18), W - Rr - 18), H - 6); }); }
  }
  if (o.thr != null && !mini) { c.strokeStyle = css('--bad'); c.setLineDash([5, 4]); c.beginPath(); c.moveTo(L, Y(o.thr)); c.lineTo(W - Rr, Y(o.thr)); c.stroke(); c.setLineDash([]); }
  (o.marks || []).forEach(m => { const i = o.ticks ? o.ticks.indexOf(m.tick) : -1; if (i < 0) return;
    c.strokeStyle = m.color || css('--warn'); c.setLineDash([3, 3]); c.beginPath(); c.moveTo(X(i), T); c.lineTo(X(i), T + ih); c.stroke(); c.setLineDash([]);
    c.fillStyle = m.color || css('--warn'); c.textAlign = 'left'; c.fillText(m.label, X(i) + 4, T + 11); });
  series.forEach(s => {
    const off = n - s.data.length; c.strokeStyle = s.color; c.lineWidth = mini ? 2 : 2; c.beginPath(); let st = false;
    s.data.forEach((v, i) => { if (v == null) return; const x = X(i + off), y = Y(v); st ? c.lineTo(x, y) : c.moveTo(x, y); st = true; }); c.stroke();
    if (s.flags && !mini) { c.fillStyle = css('--bad'); s.flags.forEach((f, i) => { if (f && s.data[i] != null) { c.beginPath(); c.arc(X(i + off), Y(s.data[i]), 3, 0, 7); c.fill(); } }); }
  });
  if (mini && series[0]) { const s = series[0]; c.fillStyle = css('--bad'); (s.flags || []).forEach((f, i) => { if (f) c.fillRect(X(i + n - s.data.length) - 1.5, H - 4, 3, 3); }); }
  if (!mini && cv._h != null && cv._h < n) {   // hover crosshair + tooltip
    const i = cv._h; c.strokeStyle = css('--mut'); c.beginPath(); c.moveTo(X(i), T); c.lineTo(X(i), T + ih); c.stroke();
    const lines = series.map(s => { const v = s.data[i - (n - s.data.length)]; return v == null ? null : [s.color, s.name + ': ' + (o.fmt || fmtN)(v)]; }).filter(Boolean);
    const head = o.ticks ? 't=' + o.ticks[i] : '#' + i, bw = 150, bh = 18 + lines.length * 15, bx = X(i) > W / 2 ? X(i) - bw - 8 : X(i) + 8;
    c.fillStyle = css('--card'); c.strokeStyle = css('--line'); c.fillRect(bx, T + 14, bw, bh); c.strokeRect(bx, T + 14, bw, bh);
    c.fillStyle = css('--ink'); c.textAlign = 'left'; c.fillText(head, bx + 6, T + 28);
    lines.forEach((l, k) => { c.fillStyle = l[0]; c.fillText('\u25CF ' + l[1], bx + 6, T + 43 + k * 15); });
  }
  if (!cv._hooked && !mini) {
    cv._hooked = true;
    cv.addEventListener('mousemove', e => { const r = cv.getBoundingClientRect(), nn = Math.max(0, ...cv._a[0].map(s => s.data.length));
      cv._h = Math.max(0, Math.min(nn - 1, Math.round((e.clientX - r.left - 48) / (r.width - 58) * (nn - 1)))); lineChart(cv, ...cv._a); });
    cv.addEventListener('mouseleave', () => { cv._h = null; lineChart(cv, ...cv._a); });
  }
}
function barChart(cv, labels, values, o = {}) {
  if (!cv) return; const dpr = window.devicePixelRatio || 1, W = cv.clientWidth || 500, H = o.h || cv.clientHeight || 220;
  cv.width = W * dpr; cv.height = H * dpr; const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, H);
  if (!values.length) { c.fillStyle = css('--mut'); c.font = '13px system-ui'; c.fillText('No data yet', 12, 24); return; }
  const L = 40, B = 36, T = 16, mx = Math.max(...values, 1) * 1.15, bw = Math.min(46, (W - L - 10) / values.length - 6);
  c.font = '11px system-ui'; c.strokeStyle = css('--line'); c.fillStyle = css('--mut');
  for (let k = 0; k <= 4; k++) { const y = T + (H - T - B) * k / 4; c.beginPath(); c.moveTo(L, y); c.lineTo(W - 6, y); c.stroke(); c.textAlign = 'right'; c.fillText(fmtN(mx * (1 - k / 4)), L - 5, y + 4); }
  values.forEach((v, i) => { const x = L + 8 + i * ((W - L - 10) / values.length), h = (H - T - B) * (v || 0) / mx;
    c.fillStyle = (o.colors && o.colors[i]) || css('--acc'); c.fillRect(x, H - B - h, bw, h);
    c.fillStyle = css('--ink'); c.textAlign = 'center'; c.fillText(v == null ? '-' : fmtN(v), x + bw / 2, H - B - h - 4);
    c.fillStyle = css('--mut'); c.fillText(String(labels[i]).replace('EVT-', '#'), x + bw / 2, H - B + 14); });
}
const barRows = (items, fmt) => { const mx = Math.max(1, ...items.map(i => i.v)); return items.map(i => `<div class="barrow"><span>${esc(i.k)}</span><div class="bar"><i style="width:${100 * i.v / mx}%;background:${i.c || 'var(--acc)'}"></i></div><b>${fmt ? fmt(i.v) : i.v}</b></div>`).join('') || '<span class="k">no data yet</span>'; };

/* ===== top bar, toasts, incident drawer ===== */
function topbar() {
  const i = S.incident, p = $('tPill'), t = $('tPillT');
  $('tMeta').textContent = `${S.mode} mode \u00B7 tick ${S.tick} \u00B7 run #${S.run}`;
  let cls = 'pill', txt = 'All systems healthy';
  if (S.settings.paused) { cls = 'pill paused'; txt = 'Paused'; }
  else if (i) { const w = i.status === 'pending_approval'; cls = 'pill ' + (w ? 'wait' : 'inc'); txt = `${i.id} \u00B7 ${nice(i.status)}`; }
  p.className = cls; t.textContent = txt; $('tPause').textContent = S.settings.paused ? 'Resume' : 'Pause';
  const nb = $('nb'); if (nb) { const w = i && i.status === 'pending_approval'; nb.hidden = !w; nb.textContent = w ? '1' : '0'; }
}
function toast(msg) { const d = document.createElement('div'); d.className = 'toast'; d.innerHTML = msg; $('toasts').appendChild(d); setTimeout(() => d.remove(), 6000); }
function toasts() {
  const i = S.incident, key = i ? i.id + ':' + i.status : '', last = sessionStorage.getItem('lastInc') || '';
  if (key && key !== last) {
    const m = { diagnosed: `Anomaly on <b>${esc(i.root)}</b> \u2192 ${esc(nice(i.failure_type))}`, pending_approval: `Approval needed: <b>${esc(i.action)}</b> on ${esc(i.root)}`,
      verifying: `Executing <b>${esc(i.action)}</b> on ${esc(i.root)}\u2026 verifying`, escalated: `Escalated to a human: ${esc(i.id)}` }[i.status];
    if (m) toast(m);
  } else if (!key && last.includes(':') && last.split(':')[1] === 'verifying') toast('Incident resolved \u2713');
  sessionStorage.setItem('lastInc', key || (last.split(':')[1] === 'verifying' ? 'done' : last));
}
let drawerId = null;
function closeDrawer() { drawerId = null; $('drawer').classList.remove('on'); }
async function openIncident(id) { drawerId = id; $('drawer').classList.add('on'); $('drawer').innerHTML = '<p class="k">Loading\u2026</p>'; await refreshDrawer(); }
async function refreshDrawer() {
  if (!drawerId) return; let inc; try { inc = await api('/api/incidents/' + drawerId); } catch (e) { return; }
  $('drawer').innerHTML = incHTML(inc, S && S.incident && S.incident.id === inc.id);
}
function incHTML(i, live) {
  const pol = i.policy || {}, kb = (i.kb_matches || []), steps = i.plan_steps || [], st = i.status;
  const btn = !live ? '' : st === 'pending_approval' ? `<div class="row"><button class="g" onclick="approve()">Approve ${esc(i.action)}</button><button class="r" onclick="reject()">Reject</button></div>`
    : st === 'escalated' ? `<div class="row"><button class="p" onclick="ack()">Engineer fixed it \u2014 close ticket</button></div>` : '';
  const li = a => (a && a.length) ? '<ul>' + a.map(x => `<li><code>${esc(x)}</code></li>`).join('') + '</ul>' : '<span class="k">none captured</span>';
  const mad = i.metrics_at_detection ? Object.entries(i.metrics_at_detection).map(([k, v]) => `${k}: <b>${v}</b>`).join(' &nbsp; ') : '';
  return `<div class="row"><h1 style="margin:0">${esc(i.id)}</h1>${chip(st)}<span class="sp"></span><button class="s" onclick="closeDrawer()">Close</button></div>${btn}
  <table><tbody>
  <tr><td class="k">Root cause</td><td><b>${esc(i.root)}</b> (affected: ${esc((i.affected || []).join(', ') || 'none')})</td></tr>
  <tr><td class="k">Failure type</td><td>${esc(nice(i.failure_type))} \u00B7 confidence ${Math.round((i.confidence || 0) * 100)}%</td></tr>
  <tr><td class="k">Action</td><td><b>${esc(i.action)}</b> \u2014 ${esc(i.action_why || '')}</td></tr>
  <tr><td class="k">Policy</td><td>${chip(pol.risk || 'low', pol.decision)} ${esc((pol.reasons || []).join(' \u00B7 '))}</td></tr>
  <tr><td class="k">Attempts</td><td>${i.attempts}</td></tr><tr><td class="k">MTTD / MTTR</td><td>${sec(i.mttd)} / ${sec(i.mttr)}</td></tr>
  <tr><td class="k">Detected at tick</td><td>${i.t_detect}</td></tr><tr><td class="k">Metrics at detection</td><td>${mad}</td></tr></tbody></table>
  <h3 style="margin-top:14px">Explanation (${esc(i.explainer || '')})</h3><p>${esc(i.explanation || '')}</p>
  <h3>Evidence \u2014 logs</h3>${li(i.logs)}<h3>Evidence \u2014 Kubernetes events</h3>${li(i.events)}
  <h3>Latency correlation with affected services</h3><p>${Object.entries(i.correlation || {}).map(([k, v]) => `${esc(k)}: <b>${v}</b>`).join(' &nbsp; ') || '<span class="k">n/a</span>'}</p>
  <h3>Similar past incidents (cosine similarity)</h3><table><tbody>${kb.map(k => `<tr><td>${esc(k.id)}</td><td>${esc(nice(k.failure_type))} on ${esc(k.service)}</td><td>${esc(k.root_cause)}</td><td>\u2192 ${esc(k.action)}</td><td><b>${k.similarity}</b></td></tr>`).join('') || '<tr><td class="k">none</td></tr>'}</tbody></table>
  <h3>Remediation plan</h3>${steps.map(s => `<div style="margin:4px 0"><b>${esc(s.tool)}</b> ${s.exists ? '' : '(artifact missing)'}<br><code>${esc(s.command)}</code></div>`).join('') || '<span class="k">n/a</span>'}
  <h3>Timeline</h3><ul class="tl">${(i.timeline || []).map(e => `<li><i>t=${e.tick}</i>${esc(e.msg)}</li>`).join('')}</ul>`;
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

/* ===== main loop ===== */
async function loop() {
  try {
    const n = (PAGE === 'monitor' || PAGE === 'ai') ? 300 : 60;
    S = await api('/api/state?n=' + n); topbar(); toasts();
    if (drawerId) refreshDrawer();
    if (R[PAGE]) R[PAGE]();
  } catch (e) { console.error(e); const t = $('tPillT'); if (t) t.textContent = 'server unreachable'; }
  setTimeout(loop, 1000);
}
$('tPause').onclick = () => post('/api/settings', {paused: !(S && S.settings.paused)});

/* ===== HOME ===== */
R.home = () => {
  const i = S.incident, st = S.stats;
  $('home_live').innerHTML = `<span><b>Live:</b> ${i ? '<span style="color:var(--bad)">incident ' + esc(i.id) + ' \u2014 ' + esc(nice(i.status)) + '</span>' : '<span style="color:var(--ok)">all services healthy</span>'}</span>
   <span>\u00B7 ${st.resolved}/${st.total} incidents auto-resolved</span><span>\u00B7 avg MTTR ${st.avg_mttr == null ? '-' : st.avg_mttr + ' s'}</span><span>\u00B7 ${S.router.total} events routed</span><span>\u00B7 ${st.kb_size} knowledge-base entries</span>`;
};

/* ===== OVERVIEW ===== */
function banner(i) {
  if (!i) return `<div class="banner"><b style="color:var(--ok)">All systems healthy.</b> <span class="k">Open the <a href="/chaos">Chaos Lab</a> to inject a failure and watch the AI heal it.</span></div>`;
  const st = i.status, cls = st === 'pending_approval' ? 'wait' : 'bad';
  const btn = st === 'pending_approval' ? `<button class="g" onclick="approve()">Approve ${esc(i.action)}</button> <button class="r" onclick="reject()">Reject</button>`
    : st === 'escalated' ? `<button class="p" onclick="ack()">Engineer fixed it \u2014 close ticket</button>` : '';
  return `<div class="banner ${cls}"><div class="row" style="margin:0"><b>${esc(i.id)}</b>${chip(st)}<span>Root cause <b>${esc(i.root)}</b> \u2192 ${esc(nice(i.failure_type))} (${Math.round(i.confidence * 100)}%) \u2192 action <b>${esc(i.action)}</b></span><span class="sp"></span>${btn}<button class="s" onclick="openIncident('${esc(i.id)}')">Full investigation</button></div></div>`;
}
R.overview = () => {
  if (!R._rt || Date.now() - R._rt > 4000) { R._rt = Date.now(); api('/api/report').then(r => { R._rep = r; kpis(); }); }
  kpis(); $('ov_banner').innerHTML = banner(S.incident);
  const names = Object.keys(S.services), i = S.incident;
  $('ov_svcs').innerHTML = names.map(n => {
    const l = S.services[n].latest; if (!l) return ''; const root = i && i.root === n, bad = l.anomalous;
    return `<div class="svc ${bad ? 'bad' : ''} ${root ? 'root' : ''}" onclick="location.href='/monitor?svc=${n}'"><h4>${esc(n)}${chip(bad ? 'escalated' : 'resolved', bad ? 'anomalous' : 'healthy')}</h4>
    <div class="k" style="font-size:11px">${esc(S.infra.nodes[n])} \u00B7 ${l.replicas} pod(s) \u00B7 ${esc(l.version)}${S.truth[n] ? ' \u00B7 <span style="color:var(--bad)">injected: ' + esc(nice(S.truth[n])) + '</span>' : ''}</div>
    <div class="m"><span>CPU</span><b>${l.cpu}%</b><span>Mem</span><b>${l.mem}%</b><span>Latency</span><b>${l.latency}ms</b><span>Errors</span><b>${l.error_rate}%</b></div><canvas id="g_${n}" style="height:44px"></canvas></div>`;
  }).join('');
  names.forEach(n => { const sr = S.services[n].series; lineChart($('g_' + n), [{name: n, color: sr.length && sr[sr.length - 1].anomalous ? css('--bad') : css('--acc'), data: sr.map(h => h.latency), flags: sr.map(h => h.anomalous)}], {mini: true, log: true, h: 44}); });
  if (i) $('ov_tl').innerHTML = `<div class="pipe">${['Detect', 'Diagnose', 'Decide', 'Heal', 'Verify', 'Learn'].map((p, k) => `<span class="${k <= ({diagnosed: 2, pending_approval: 2, verifying: 4, escalated: 4}[i.status] ?? 5) ? 'on' : ''}">${p}</span>`).join('')}</div><ul class="tl">${i.timeline.slice().reverse().map(e => `<li><i>t=${e.tick}</i>${esc(e.msg)}</li>`).join('')}</ul>`;
  else $('ov_tl').innerHTML = '<span class="k">No active incident.</span>';
  $('ov_recent').innerHTML = S.closed.map(c => `<tr class="click" onclick="openIncident('${esc(c.id)}')"><td>${esc(c.id)}</td><td>${esc(c.root)}</td><td>${esc(nice(c.failure_type))}</td><td>${chip(c.status)}</td><td>${sec(c.mttr)}</td></tr>`).join('') || '<tr><td colspan=5 class="k">none yet</td></tr>';
};
function kpis() {
  const r = R._rep || {}, st = S.stats;
  const k = [[`${st.resolved}/${st.total}`, 'incidents auto-resolved', ''], [r.avg_mttr == null ? '-' : r.avg_mttr + ' s', 'avg MTTR (AI)', r.faster_pct != null ? r.faster_pct + '% faster than assumed 15 min manual' : ''],
    [r.avg_mttd == null ? '-' : r.avg_mttd + ' s', 'avg time to detect (MTTD)', ''], [r.availability == null ? '-' : r.availability + '%', 'availability (health-check SLO)', (r.ticks || 0) + ' checks stored'],
    [st.kb_size, 'knowledge-base entries', 'grows after every incident'], [S.router.total, 'events routed', S.router.backend]];
  $('kpis').innerHTML = k.map(x => `<div class="card kpi" style="margin:0"><b>${esc(x[0])}</b><span>${x[1]}</span><small>${esc(x[2])}</small></div>`).join('');
}

/* ===== LIVE MONITOR ===== */
const METRIC = {latency: {u: 'ms', log: true}, error_rate: {u: '%'}, cpu: {u: '%', max: 100}, mem: {u: '%', max: 100}, rps: {u: ''}, score: {u: ''}};
let mmSel = null, frozen = false;
R.monitor = () => {
  const names = Object.keys(S.services);
  if (!mmSel) { const q = new URLSearchParams(location.search).get('svc'); mmSel = new Set(q && names.includes(q) ? [q] : names);
    $('mm_svcs').innerHTML = names.map((n, k) => `<label><input type="checkbox" data-s="${n}" ${mmSel.has(n) ? 'checked' : ''}> <span style="color:${COL[k % 5]}">\u25CF</span> ${esc(n)}</label>`).join(' ');
    $('mm_svcs').onchange = e => { e.target.checked ? mmSel.add(e.target.dataset.s) : mmSel.delete(e.target.dataset.s); R.monitor(); };
    $('mm_metric').onchange = $('mm_win').onchange = () => R.monitor();
    $('mm_freeze').onclick = () => { frozen = !frozen; $('mm_freeze').textContent = frozen ? 'Resume chart' : 'Freeze chart'; }; }
  $('mm_tbl').innerHTML = names.map(n => { const l = S.services[n].latest; if (!l) return ''; const b = l.anomalous ? 'style="color:var(--bad)"' : '';
    return `<tr ${b}><td><b>${esc(n)}</b></td><td>${l.cpu}</td><td>${l.mem}</td><td>${l.latency}</td><td>${l.error_rate}</td><td>${l.rps}</td><td>${l.score}</td><td>${l.replicas} / ${esc(l.version)}</td></tr>`; }).join('');
  if (frozen) return;
  const m = $('mm_metric').value, win = +$('mm_win').value, cfg = METRIC[m], ser = [];
  names.forEach((n, k) => { if (!mmSel.has(n)) return; const sr = S.services[n].series.slice(-win);
    ser.push({name: n, color: COL[k % 5], data: sr.map(h => h[m]), flags: sr.map(h => h.anomalous)}); });
  const ref = S.services[names[0]].series.slice(-win), marks = S.incident ? [{tick: S.incident.t_detect, label: 'detected ' + S.incident.id}] : [];
  lineChart($('mm_chart'), ser, {log: cfg.log, min: m === 'score' ? undefined : 0, max: cfg.max, thr: m === 'score' ? 0 : null, ticks: ref.map(h => h.tick), marks, h: 300, fmt: v => fmtN(v) + (cfg.u && m !== 'latency' ? cfg.u : '')});
  $('mm_legend').innerHTML = ser.map(s => `<span style="color:${s.color}">\u25CF ${esc(s.name)}</span>`).join(' &nbsp; ') + ' &nbsp; <span class="k">red dots = anomalous samples</span>';
};

/* ===== ARCHITECTURE ===== */
R.architecture = () => {
  const i = S.incident, Rt = S.router, cn = Rt.counts || {}, names = Object.keys(S.services);
  const anom = names.filter(n => S.services[n].latest && S.services[n].latest.anomalous), st = i ? i.status : '';
  const lg = S.signals.logs.slice(0, 5).map(l => `<div class="${esc(l.level)}">${esc(l.service)}: ${esc(l.msg)}</div>`).join('') || '<span class="k">no logs</span>';
  const ev = S.signals.events.slice(0, 3).map(e => `<div class="${esc(e.type)}">${esc(e.type)}: ${esc(e.msg)}</div>`).join('');
  const pods = names.map(n => `<div class="kv"><span>${esc(n)}</span><span class="k">${esc(S.infra.nodes[n])} \u00B7 ${(S.services[n].latest || {}).replicas || 1} pod(s)</span></div>`).join('');
  const steps = i && i.plan_steps ? i.plan_steps.map(x => `<div><b>${esc(x.tool)}</b><br><code>${esc(x.command)}</code></div>`).join('') : '<span class="k">idle</span>';
  const ver = i && i.verify_streak !== undefined ? `health check streak ${i.verify_streak}/3` : (st === 'resolved' ? 'recovered' : 'idle');
  $('arch').innerHTML = `
  <div class="box"><h5>Target infrastructure<br><span class="k">${esc(S.infra.cluster)}</span></h5>${pods}<div class="k" style="margin-top:6px">MERN-style application</div></div>
  <div class="box ${anom.length ? 'alert' : ''}"><h5>A. Observability layer</h5><div class="kv"><span>Metrics</span><b>${cn['telemetry.metrics'] || 0}</b></div><div class="kv"><span>Logs</span><b>${cn['telemetry.logs'] || 0}</b></div><div class="kv"><span>Traces</span><b>${cn['telemetry.traces'] || 0}</b></div><div class="kv"><span>Events</span><b>${cn['telemetry.events'] || 0}</b></div><div class="lg" style="max-height:110px">${lg}${ev}</div></div>
  <div class="box ${i ? 'act' : ''}"><h5>B. AI/ML core analytics</h5><div class="k">Router: ${esc(Rt.backend)} (${Rt.total} msgs)</div><div>Isolation Forest: ${anom.length ? '<b style="color:var(--bad)">' + esc(anom.join(', ')) + '</b>' : 'all normal'}</div>${i ? `<div>RCA root: <b>${esc(i.root)}</b></div><div>Random Forest: ${esc(nice(i.failure_type))} ${Math.round(i.confidence * 100)}%</div><div>KB match: ${esc((i.kb_matches[0] || {}).id || '-')}</div>` : ''}</div>
  <div class="box ${st === 'pending_approval' ? 'alert' : (st === 'verifying' ? 'act' : '')}"><h5>C. Decision &amp; automation</h5>${i ? `<div>Policy: <b>${esc(i.policy ? i.policy.decision : '-')}</b> (${esc(i.policy ? i.policy.risk : '')})</div>` : ''}${steps}<div class="k" style="margin-top:4px">plans ${cn['automation.plan'] || 0} \u00B7 actions ${cn['automation.actions'] || 0} \u00B7 policy updates ${cn['policy.updates'] || 0}</div></div>
  <div class="box ${st === 'escalated' ? 'alert' : ''}"><h5>D. Verification layer</h5><div>${ver}</div><div class="k">checks: ${cn['verification.results'] || 0}</div><div style="margin-top:6px">${st === 'escalated' ? '<b style="color:var(--bad)">Not recovered \u2192 escalate to DevOps engineer</b>' : (st === 'resolved' || !i ? 'Recovered \u2192 incident resolved' : 'Recovered? checking\u2026')}</div><div class="k" style="margin-top:6px">Feedback loop: KB ${S.stats.kb_size} entries</div></div>`;
  depGraph(names, i, anom);
  const rows = Object.entries(cn).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({k, v}));
  $('router_tbl').innerHTML = `<div class="k" style="margin-bottom:6px">${Rt.total} messages \u00B7 backend: ${esc(Rt.backend)}</div>` + barRows(rows);
};
function depGraph(names, inc, anom) {
  const deps = S.deps, depth = {}; const d = n => depth[n] ?? (depth[n] = deps[n].length ? 1 + Math.max(...deps[n].map(d)) : 0);
  names.forEach(d); const levels = {}; names.forEach(n => (levels[depth[n]] = levels[depth[n]] || []).push(n));
  const maxD = Math.max(...Object.keys(levels).map(Number)), pos = {};
  Object.entries(levels).forEach(([lv, arr]) => arr.forEach((n, k) => pos[n] = {x: 260 + (k - (arr.length - 1) / 2) * 170, y: 40 + (maxD - lv) * (maxD ? 220 / maxD : 0)}));
  let svg = '<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#888"/></marker></defs>';
  names.forEach(n => deps[n].forEach(t => { if (pos[n] && pos[t]) svg += `<line x1="${pos[n].x}" y1="${pos[n].y + 22}" x2="${pos[t].x}" y2="${pos[t].y - 24}" stroke="#888" stroke-width="2" marker-end="url(#ar)"/>`; }));
  names.forEach(n => { const bad = anom.includes(n), root = inc && inc.root === n, aff = inc && (inc.affected || []).includes(n);
    const fill = root ? '#c9302c' : aff ? '#d98a00' : bad ? '#c9302c' : '#1a8f4c';
    svg += `<g><rect x="${pos[n].x - 62}" y="${pos[n].y - 22}" width="124" height="44" rx="10" fill="${fill}" ${root ? 'stroke="#000" stroke-width="4"' : ''}/><text x="${pos[n].x}" y="${pos[n].y + 5}" text-anchor="middle" fill="#fff" font-size="14" font-weight="700">${esc(n)}</text></g>`; });
  $('dep').innerHTML = svg;
}

/* ===== INCIDENTS ===== */
async function loadInc() {
  const p = new URLSearchParams({q: $('inc_q').value, status: $('inc_status').value, type: $('inc_type').value, limit: 300});
  const rows = await api('/api/incidents?' + p);
  $('inc_tbl').innerHTML = rows.map(r => `<tr class="click" onclick="openIncident('${esc(r.id)}')"><td><b>${esc(r.id)}</b></td><td class="k">${esc(r.ts)}</td><td>${esc(r.root)}</td><td>${esc(nice(r.failure_type))}</td><td>${Math.round((r.confidence || 0) * 100)}%</td><td>${esc(r.action)}</td><td>${chip(r.status)}</td><td>${r.attempts}</td><td>${sec(r.mttd)}</td><td>${sec(r.mttr)}</td></tr>`).join('') || '<tr><td colspan=10 class="k">No incidents yet \u2014 inject one from the Chaos Lab.</td></tr>';
  $('inc_n').textContent = rows.length + ' incident(s) shown';
}
R.incidents = () => {
  if (!I.inc) { I.inc = 1; ['inc_q', 'inc_status', 'inc_type'].forEach(id => $(id).oninput = loadInc); loadInc(); }
  if (!R._it || Date.now() - R._it > 3000) { R._it = Date.now(); loadInc(); }
};

/* ===== CHAOS LAB ===== */
R.chaos = () => {
  const names = Object.keys(S.services);
  if (!I.chaos) { I.chaos = 1;
    $('cl_service').innerHTML = names.map(n => `<option>${esc(n)}</option>`).join('');
    $('cl_fault').innerHTML = Object.entries(FAULTS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
    $('cl_go').onclick = async () => { const r = await post('/api/inject', {service: $('cl_service').value, fault: $('cl_fault').value, stubborn: $('cl_stub').checked}); $('cl_msg').textContent = r.msg || ''; };
    $('cl_reset').onclick = async () => { await post('/api/clear'); $('cl_msg').textContent = 'All injected failures cleared.'; };
    api('/api/scenarios').then(sc => { $('cl_scen').innerHTML = sc.map(s => `<div class="scen" data-id="${esc(s.id)}"><b>${esc(s.title)}</b><span class="k">${esc(s.desc)}</span></div>`).join('');
      $('cl_scen').onclick = async e => { const d = e.target.closest('.scen'); if (!d) return; const r = await post('/api/scenario', {id: d.dataset.id}); toast(esc(r.msg || 'failed')); }; }); }
  const t = Object.entries(S.truth || {}); $('cl_truth').innerHTML = t.length ? t.map(([k, v]) => `<b style="color:var(--bad)">${esc(k)}: ${esc(nice(v))}</b>`).join(', ') : 'none';
};

/* ===== AI LAB ===== */
const SLIDERS = [['cpu', 'CPU %', 0, 100, 1], ['mem', 'Memory %', 0, 100, 1], ['latency', 'Latency ms', 0, 3000, 10], ['error_rate', 'Errors %', 0, 100, 0.5], ['rps', 'Throughput', 0, 250, 1]];
function probaHTML(p) { return barRows(Object.entries(p).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({k: nice(k), v: +(v * 100).toFixed(1), c: k === 'normal' ? 'var(--ok)' : 'var(--bad)'})), v => v + '%'); }
function whatifHTML(w) {
  return `<div>${w.anomalous ? '<b style="color:var(--bad)">Isolation Forest: ANOMALOUS</b>' : '<b style="color:var(--ok)">Isolation Forest: normal</b>'} <span class="k">(score ${w.anomaly_score})</span></div>
  <div style="margin:6px 0"><b>Random Forest says: ${esc(nice(w.label))}</b> (${Math.round(w.confidence * 100)}%)</div>${probaHTML(w.proba)}
  <div style="margin-top:8px">${w.action ? `Remediation: <b>${esc(w.action)}</b> \u2014 ${esc(w.why || '')}<br>Policy: ${chip(w.policy.risk, w.policy.decision)} <span class="k">${esc(w.policy.reasons.join(' \u00B7 '))}</span>` : '<span class="k">No remediation needed.</span>'}</div>
  <div class="k" style="margin-top:6px">Symptom text: <code>${esc(w.symptoms)}</code></div>
  <div style="margin-top:6px"><b>Most similar past incidents:</b> ${w.kb.map(k => `${esc(k.id)} (${k.similarity}) \u2192 ${esc(k.action)}`).join('; ') || 'none'}</div>`;
}
async function runWhatIf() {
  const b = {service: $('wi_svc').value}; SLIDERS.forEach(s => { b[s[0]] = +$('wi_' + s[0]).value; $('wv_' + s[0]).textContent = $('wi_' + s[0]).value; });
  $('wi_out').innerHTML = whatifHTML(await post('/api/whatif', b));
}
function loadCurrent() { const l = (S.services[$('wi_svc').value] || {}).latest; if (!l) return; SLIDERS.forEach(s => { $('wi_' + s[0]).value = Math.min(l[s[0]], s[3]); }); runWhatIf(); }
async function kbSearch() {
  const q = $('kb_q').value.trim(), rows = await api('/api/kb?q=' + encodeURIComponent(q));
  $('kb_out').innerHTML = `<table><thead><tr><th>ID</th><th>Failure</th><th>Service</th><th>Action</th>${q ? '<th>Sim.</th>' : ''}</tr></thead><tbody>` + rows.map(r => `<tr title="${esc(r.symptoms)}"><td>${esc(r.id)}</td><td>${esc(nice(r.failure_type))}</td><td>${esc(r.service)}</td><td>${esc(r.action)}</td>${q ? `<td><b>${r.similarity}</b></td>` : ''}</tr>`).join('') + '</tbody></table><div class="k">Hover a row to see its symptom text. Try: cpu_saturated latency_high</div>';
}
R.ai = () => {
  const names = Object.keys(S.services);
  if (!I.ai) { I.ai = 1;
    $('ai_svc').innerHTML = $('wi_svc').innerHTML = names.map(n => `<option>${esc(n)}</option>`).join('');
    $('wi_sliders').innerHTML = SLIDERS.map(s => `<div class="sl"><span>${s[1]}</span><input type="range" id="wi_${s[0]}" min="${s[2]}" max="${s[3]}" step="${s[4]}" value="${s[2]}"><b id="wv_${s[0]}">${s[2]}</b></div>`).join('');
    let t; SLIDERS.forEach(s => $('wi_' + s[0]).oninput = () => { clearTimeout(t); t = setTimeout(runWhatIf, 120); });
    $('wi_svc').onchange = loadCurrent; $('wi_load').onclick = loadCurrent; $('kb_q').oninput = kbSearch; kbSearch(); setTimeout(loadCurrent, 100);
    api('/api/models').then(m => { I.models = m; $('ai_imp').innerHTML = barRows(Object.entries(m.random_forest.importances).map(([k, v]) => ({k: nice(k), v: +(v * 100).toFixed(1)})), v => v + '%'); }); }
  const svc = $('ai_svc').value, sr = S.services[svc].series.slice(-120);
  lineChart($('ai_chart'), [{name: svc, color: css('--acc'), data: sr.map(h => h.score), flags: sr.map(h => h.anomalous)}], {thr: 0, ticks: sr.map(h => h.tick), h: 220, fmt: v => v.toFixed(2)});
  if (I.models) { const b = I.models.isolation_forest.baselines[svc]; $('ai_base').innerHTML = b ? `Learned healthy baseline for <b>${esc(svc)}</b>: ` + Object.entries(b).map(([k, v]) => `${k} ${(+v).toFixed(1)}`).join(' \u00B7 ') + `<br>Model: ${I.models.isolation_forest.n_estimators} trees, contamination ${I.models.isolation_forest.contamination}, z-score guard |z|&gt;${I.models.isolation_forest.z_guard}, acts after ${I.models.isolation_forest.consecutive} consecutive anomalous ticks.` : ''; }
  if (!R._cl || Date.now() - R._cl > 1500) { R._cl = Date.now(); const l = S.services[svc].latest;
    if (l) post('/api/whatif', {service: svc, cpu: l.cpu, mem: l.mem, latency: l.latency, error_rate: l.error_rate, rps: l.rps}).then(w => { if ($('ai_cls')) $('ai_cls').innerHTML = `<div class="k">Live metrics of <b>${esc(svc)}</b> \u2192 <b>${esc(nice(w.label))}</b> (${Math.round(w.confidence * 100)}%)</div>` + probaHTML(w.proba); }); }
};

/* ===== POLICY ===== */
R.policy = () => {
  const i = S.incident;
  $('pol_pending').innerHTML = i && i.status === 'pending_approval' ? `<div class="banner wait"><h3 style="color:var(--warn)">Approval required</h3><p><b>${esc(i.action)}</b> on <b>${esc(i.root)}</b> for ${esc(nice(i.failure_type))}. ${esc((i.policy.reasons || []).join(' \u00B7 '))}</p><div class="row"><button class="g" onclick="approve()">Approve</button><button class="r" onclick="reject()">Reject</button><button class="s" onclick="openIncident('${esc(i.id)}')">Full investigation</button></div></div>`
    : `<div class="banner"><b>No actions waiting for approval.</b> <span class="k">High-risk actions (e.g. restarting the database) and actions with a poor past success rate will pause here.</span></div>`;
  if (!R._pt || Date.now() - R._pt > 2000) { R._pt = Date.now(); api('/api/policy').then(p => {
    $('pol_rules').innerHTML = p.rules.map(r => `<tr><td>${esc(nice(r.failure))}</td><td><b>${esc(r.action)}</b><div class="k">${esc(r.why)}</div></td><td>${chip(r.risk.split(' ')[0], r.risk)}</td></tr>`).join('');
    $('pol_stats').innerHTML = p.stats.length ? barRows(p.stats.map(s => ({k: s.rule + (s.restricted ? ' (needs approval)' : ''), v: s.n ? Math.round(100 * s.ok / s.n) : 0, c: s.restricted ? 'var(--bad)' : 'var(--ok)'})), v => v + '%') + '<div class="k">A rule at \u226450% success after \u22652 outcomes now requires human approval (learned policy update).</div>' : 'No outcomes recorded yet.';
    $('pol_limits').innerHTML = `<table><tbody><tr><td>Allowed actions</td><td>${p.allowlist.map(a => `<code>${a}</code>`).join(' ')}</td></tr><tr><td>Anomalous ticks before acting</td><td>${p.limits.consecutive_anomalies}</td></tr><tr><td>Healthy checks to verify recovery</td><td>${p.limits.verify_streak}</td></tr><tr><td>Verification timeout</td><td>${p.limits.verify_timeout} ticks</td></tr><tr><td>Max remediation attempts</td><td>${p.limits.max_attempts}</td></tr><tr><td>Max replicas</td><td>${p.limits.max_replicas}</td></tr><tr><td>Auto-approve high risk</td><td>${p.auto_approve ? 'ON' : 'off'}</td></tr></tbody></table>`; }); }
};

/* ===== LOGS ===== */
let lgKind = 'log';
async function loadLogs() {
  if (lgKind === 'trace') { $('lg_out').innerHTML = S.signals.traces.map(t => `<div class="${t.status === 'ERROR' ? 'ERROR' : ''}">${esc(t.span)} \u00B7 ${t.ms} ms \u00B7 ${esc(t.status)} <span class="k">t=${t.tick}</span></div>`).join('') || '<span class="k">no traces</span>'; return; }
  const p = new URLSearchParams({kind: lgKind, service: $('lg_svc').value, level: $('lg_lvl').value, q: $('lg_q').value, limit: 300}), rows = await api('/api/logs?' + p);
  $('lg_out').innerHTML = rows.map(r => `<div><span class="k">${esc(r.ts)} t=${r.tick}</span> <b>${esc(r.service)}</b> <span class="${esc(r.level)}">${esc(r.level)}</span> ${esc(r.msg)}</div>`).join('') || '<span class="k">nothing stored yet \u2014 inject a failure to generate logs.</span>';
}
R.logs = () => {
  if (!I.logs) { I.logs = 1; $('lg_svc').innerHTML = '<option value="">all services</option>' + Object.keys(S.services).map(n => `<option>${esc(n)}</option>`).join('');
    document.querySelectorAll('.tab').forEach(t => t.onclick = () => { document.querySelectorAll('.tab').forEach(x => x.classList.remove('on')); t.classList.add('on'); lgKind = t.dataset.k; loadLogs(); });
    ['lg_svc', 'lg_lvl', 'lg_q'].forEach(id => $(id).oninput = loadLogs); loadLogs(); }
  if ($('lg_auto').checked && (!R._lt || Date.now() - R._lt > 2000)) { R._lt = Date.now(); loadLogs(); }
};

/* ===== AUDIT ===== */
async function loadAudit() {
  const p = new URLSearchParams({q: $('au_q').value, event: $('au_ev').value, limit: 300}), rows = await api('/api/audit?' + p);
  $('au_tbl').innerHTML = rows.map(a => `<tr><td class="k" style="white-space:nowrap">${esc(a.ts)}</td><td><b>${esc(a.event)}</b></td><td>${Object.entries(a).filter(([k]) => k !== 'ts' && k !== 'event').map(([k, v]) => `<code>${esc(k)}=${esc(Array.isArray(v) ? v.join('|') : (typeof v === 'object' ? JSON.stringify(v) : v))}</code>`).join(' ')}</td></tr>`).join('') || '<tr><td colspan=3 class="k">empty</td></tr>';
}
R.audit = () => { if (!I.au) { I.au = 1; $('au_q').oninput = $('au_ev').oninput = loadAudit; loadAudit(); } if (!R._at || Date.now() - R._at > 3000) { R._at = Date.now(); loadAudit(); } };

/* ===== REPORTS ===== */
R.reports = () => {
  if (R._rp && Date.now() - R._rp < 5000) return; R._rp = Date.now();
  Promise.all([api('/api/report'), api('/api/incidents?limit=500')]).then(([r, rows]) => {
    const k = [[r.total, 'incidents total'], [r.resolved, 'auto-resolved'], [r.escalated, 'needed a human'], [r.avg_mttr == null ? '-' : r.avg_mttr + ' s', 'avg MTTR'],
      [r.avg_mttd == null ? '-' : r.avg_mttd + ' s', 'avg MTTD'], [r.availability == null ? '-' : r.availability + '%', 'availability'], [r.faster_pct == null ? '-' : r.faster_pct + '%', 'faster than manual (assumed 15 min)'], [r.ticks, 'health checks stored']];
    $('rp_kpis').innerHTML = k.map(x => `<div class="card kpi" style="margin:0"><b>${x[0]}</b><span>${x[1]}</span></div>`).join('');
    const tl = r.timeline.filter(t => t.mttr != null); barChart($('rp_mttr'), tl.map(t => t.id), tl.map(t => t.mttr), {h: 230});
    $('rp_types').innerHTML = barRows(Object.entries(r.by_type).map(([k, v]) => ({k: nice(k), v})));
    $('rp_actions').innerHTML = barRows(Object.entries(r.by_action).map(([k, v]) => ({k, v})));
    $('rp_tbl').innerHTML = rows.map(x => `<tr class="click" onclick="openIncident('${esc(x.id)}')"><td>${esc(x.id)}</td><td>${esc(nice(x.failure_type))}</td><td>${esc(x.action)}</td><td>${chip(x.status)}</td><td>${x.attempts}</td><td>${sec(x.mttd)}</td><td>${sec(x.mttr)}</td></tr>`).join('') || '<tr><td colspan=7 class="k">no incidents yet</td></tr>';
  });
};

/* ===== SETTINGS ===== */
R.settings = () => {
  if (!I.set) { I.set = 1; const s = S.settings;
    $('st_auto').checked = s.auto_approve; $('st_pause').checked = s.paused; $('st_speed').value = s.tick_seconds; $('st_speed_v').textContent = s.tick_seconds;
    $('st_auto').onchange = e => post('/api/settings', {auto_approve: e.target.checked}); $('st_pause').onchange = e => post('/api/settings', {paused: e.target.checked});
    $('st_speed').oninput = e => { $('st_speed_v').textContent = e.target.value; post('/api/settings', {tick_seconds: +e.target.value}); };
    let th = 'auto'; try { th = localStorage.getItem('theme') || 'auto'; } catch (e) {} $('st_theme').value = th;
    $('st_theme').onchange = e => { try { localStorage.setItem('theme', e.target.value); } catch (x) {} if (e.target.value === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = e.target.value; };
    $('st_clear').onclick = async () => { if (confirm('Delete all stored incidents, metrics and logs?')) { await post('/api/history/clear'); toast('History cleared'); } }; }
  $('st_pause').checked = S.settings.paused;
  $('st_info').innerHTML = `Mode: <b>${esc(S.mode)}</b> \u00B7 run #${S.run} \u00B7 tick ${S.tick} \u00B7 event router: ${esc(S.router.backend)} \u00B7 history database: <code>data/history.db</code> \u00B7 audit log: <code>data/audit_log.jsonl</code> \u00B7 knowledge base: <code>data/incident_kb.json</code>`;
};

/* ===== static page helpers ===== */
if (PAGE === 'literature') $('lit_q').oninput = e => { const q = e.target.value.toLowerCase(); document.querySelectorAll('#lit_tbl tbody tr').forEach(r => r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none'); };
loop();
