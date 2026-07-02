// 实时采集看板前端：可配置折线图（用户自选信号、图表数量可增删，布局存 localStorage）。
// 振动特征与 OPC UA 状态量一视同仁可选；多源信号用 time 轴自动对齐。无报警逻辑。
const API = '';

// ============ 信号目录（catalog）：每个信号 = {key, group, label, unit} ============
// key 形如 `<sourceId>::<field>`；sourceId 决定从哪个接口取数（同接口的信号共用一次拉取）。
const AXES = ['x1', 'x2', 'y1', 'y2', 'z', 'w', 'v', 'b1', 'b2'];
const AXIS_LABEL = { x1: 'X1', x2: 'X2', y1: 'Y1', y2: 'Y2', z: 'Z', w: 'W', v: 'V', b1: 'B1', b2: 'B2' };

const SPINDLE_DEF = [
  ['spindle_current', '主轴电流', 'A'],
  ['spindle_motor_temperature', '主轴电机温度', '℃'],
  ['spindle_front_bearing_temperature', '前轴承温度', '℃'],
  ['spindle_rear_bearing_temperature', '后轴承温度', '℃'],
  ['spindle_tail_support_temperature', '尾部支撑温度', '℃'],
  ['motor_speed', '电机转速', 'rpm'],
  ['run_rate', '运行倍率', ''],
];
const AXIS_METRICS = [['current', '电流', 'A'], ['temperature', '温度', '℃'], ['speed', '速度', '']];
const COORD_DEF = [
  ['x_mc', 'X机械', 'mm', '坐标·机械'], ['y_mc', 'Y机械', 'mm', '坐标·机械'], ['z_mc', 'Z机械', 'mm', '坐标·机械'], ['w_mc', 'W机械', 'mm', '坐标·机械'],
  ['sp_mc', 'SP机械', 'mm', '坐标·机械'], ['v_mc', 'V机械', 'mm', '坐标·机械'], ['b_mc', 'B机械', 'mm', '坐标·机械'], ['u_mc', 'U机械', 'mm', '坐标·机械'],
  ['x_ac', 'X绝对', 'mm', '坐标·绝对'], ['y_ac', 'Y绝对', 'mm', '坐标·绝对'], ['z_ac', 'Z绝对', 'mm', '坐标·绝对'], ['w_ac', 'W绝对', 'mm', '坐标·绝对'],
  ['sp_ac', 'SP绝对', 'mm', '坐标·绝对'], ['v_ac', 'V绝对', 'mm', '坐标·绝对'], ['b_ac', 'B绝对', 'mm', '坐标·绝对'], ['u_ac', 'U绝对', 'mm', '坐标·绝对'],
];
// 振动特征暴露的统计量（其余 p2p/std/crest/mean 仍算入 POOL，可按需扩展进目录）
const VIB_SHOW = [['rms', 'RMS', 'g'], ['peak', '峰值', 'g'], ['kurtosis', '峭度', '']];
const VIB_ALL = ['mean', 'rms', 'peak', 'p2p', 'std', 'kurtosis', 'crest'];

let VIB_CHANNELS = [1, 2, 3, 4]; // 启动后按 vib_features 实测通道刷新
let CATALOG = [];
let CATALOG_BY_KEY = {};
function buildCatalog() {
  const c = [];
  SPINDLE_DEF.forEach(([col, label, unit]) => c.push({ key: `spindle::${col}`, group: '主轴', label, unit }));
  AXIS_METRICS.forEach(([m, mlabel, unit]) => AXES.forEach((a) =>
    c.push({ key: `axes:${m}::${a}_axis_${m}`, group: `进给·${mlabel}`, label: AXIS_LABEL[a], unit })));
  COORD_DEF.forEach(([col, label, unit, grp]) => c.push({ key: `coords::${col}`, group: grp, label, unit }));
  VIB_SHOW.forEach(([m, mlabel, unit]) => VIB_CHANNELS.forEach((ch) =>
    c.push({ key: `vibfeat:${m}::ch${ch}`, group: `振动·${mlabel}`, label: `通道${ch}`, unit })));
  CATALOG = c;
  CATALOG_BY_KEY = Object.fromEntries(c.map((e) => [e.key, e]));
}

// ============ 取数 + 数据池（POOL）：key -> [[t_ms, value], ...] ============
let POOL = {};
const tms = (t) => (t ? new Date(t).getTime() : null);
const num = (v) => (v == null ? null : Number(v));

function fromParam() {
  const minutes = Number(document.getElementById('rangeSelect').value);
  if (!minutes) return '';
  return new Date(Date.now() - minutes * 60_000).toISOString();
}
function fromQ() { const f = fromParam(); return f ? `&from=${encodeURIComponent(f)}` : ''; }

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${(await res.json().catch(() => ({}))).error || res.statusText}`);
  return res.json();
}

// 把某接口返回行转成 POOL 条目
function poolSpindle(rows) {
  SPINDLE_DEF.forEach(([col]) => { POOL[`spindle::${col}`] = rows.filter((r) => r.time).map((r) => [tms(r.time), num(r[col])]); });
}
function poolAxes(metric, rows) {
  AXES.forEach((a) => { const col = `${a}_axis_${metric}`; POOL[`axes:${metric}::${col}`] = rows.filter((r) => r.time).map((r) => [tms(r.time), num(r[col])]); });
}
function poolCoords(rows) {
  COORD_DEF.forEach(([col]) => { POOL[`coords::${col}`] = rows.filter((r) => r.time).map((r) => [tms(r.time), num(r[col])]); });
}
function poolVib(rows) {
  const byCh = new Map();
  for (const r of rows) { if (!byCh.has(r.channel)) byCh.set(r.channel, []); byCh.get(r.channel).push(r); }
  for (const [ch, rs] of byCh) {
    VIB_ALL.forEach((m) => { POOL[`vibfeat:${m}::ch${ch}`] = rs.filter((r) => r.time).map((r) => [tms(r.time), num(r[m])]); });
  }
  const chs = [...byCh.keys()].sort((a, b) => a - b);
  if (chs.length && chs.join(',') !== VIB_CHANNELS.join(',')) { VIB_CHANNELS = chs; buildCatalog(); }
}

// sourceId -> 拉取键（vibfeat:* 共用一次 vib/features；axes:<m> 各自一次）
function fetchKeyOf(sid) { return sid.startsWith('vibfeat') ? 'vibfeat' : sid; }

async function loadSource(fetchKey) {
  if (fetchKey === 'spindle') { poolSpindle((await getJSON(`${API}/api/spindle/trend?maxPoints=1000${fromQ()}`)).rows || []); return; }
  if (fetchKey === 'coords') { poolCoords((await getJSON(`${API}/api/coordinates?maxPoints=1000${fromQ()}`)).rows || []); return; }
  if (fetchKey === 'vibfeat') { poolVib((await getJSON(`${API}/api/vib/features?maxPoints=1000${fromQ()}`)).rows || []); return; }
  if (fetchKey.startsWith('axes:')) {
    const m = fetchKey.slice(5);
    poolAxes(m, (await getJSON(`${API}/api/axes/trend?metric=${m}&axes=${AXES.join(',')}&maxPoints=1000${fromQ()}`)).rows || []);
  }
}

// ============ 可配置图表管理 ============
const echartInstances = {}; // chartId -> echarts
let CHARTS = [];            // [{id, title, signals:[key...]}]
const LS_KEY = 'acqChartsV1';

function uid() { return 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
function saveLayout() { localStorage.setItem(LS_KEY, JSON.stringify(CHARTS.map((c) => ({ id: c.id, title: c.title, signals: c.signals })))); }
function loadLayout() {
  try { const s = JSON.parse(localStorage.getItem(LS_KEY)); if (Array.isArray(s) && s.length) return s.map((c) => ({ id: c.id || uid(), title: c.title || '未命名图表', signals: Array.isArray(c.signals) ? c.signals : [] })); } catch { /* ignore */ }
  return null;
}
function seedDefaults() {
  return [
    { id: uid(), title: '主轴 电流 / 温度', signals: ['spindle::spindle_current', 'spindle::spindle_motor_temperature', 'spindle::spindle_front_bearing_temperature'] },
    { id: uid(), title: '振动 RMS（各通道）', signals: VIB_CHANNELS.map((ch) => `vibfeat:rms::ch${ch}`) },
    { id: uid(), title: '进给 电流（X1/X2/Y1/Y2）', signals: ['axes:current::x1_axis_current', 'axes:current::x2_axis_current', 'axes:current::y1_axis_current', 'axes:current::y2_axis_current'] },
  ];
}

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m])); }

function timeLineOption(series) {
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', top: 0, textStyle: { color: '#94a3b8', fontSize: 11 } },
    grid: { left: 60, right: 18, top: 34, bottom: 36 },
    xAxis: { type: 'time', axisLabel: { color: '#64748b', fontSize: 10 }, axisLine: { lineStyle: { color: '#334155' } } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#64748b', fontSize: 10 }, splitLine: { lineStyle: { color: '#1f2b3e' } } },
    series,
  };
}
// 渲染并保留图例显隐选择（否则自动刷新 notMerge 会把用户隐藏的线重置回来）
function setTimeLine(chart, series) {
  const prev = chart.getOption();
  const kept = prev && prev.legend && prev.legend[0] ? prev.legend[0].selected : undefined;
  const opt = timeLineOption(series);
  if (kept) opt.legend.selected = { ...kept };
  chart.setOption(opt, true);
}

function seriesName(key) {
  const m = CATALOG_BY_KEY[key];
  if (!m) return key;
  return `${m.group}·${m.label}${m.unit ? ` (${m.unit})` : ''}`;
}
function renderChart(cfg) {
  const inst = echartInstances[cfg.id];
  if (!inst) return;
  const series = cfg.signals.map((key) => ({ name: seriesName(key), type: 'line', showSymbol: false, smooth: false, data: POOL[key] || [] }));
  setTimeLine(inst, series);
  const card = document.querySelector(`.chart-card[data-id="${cfg.id}"]`);
  if (card) card.querySelector('.pick-signals').textContent = `信号 (${cfg.signals.length})`;
}

function makeChartCard(cfg) {
  const card = document.createElement('section');
  card.className = 'card chart-card';
  card.dataset.id = cfg.id;
  card.innerHTML = `
    <div class="chart-head">
      <input class="chart-title" value="${escapeHtml(cfg.title || '未命名图表')}" />
      <div class="card-actions">
        <button class="btn mini pick-signals">信号 (${cfg.signals.length})</button>
        <button class="btn mini btn-stop remove-chart" title="删除此图表">✕</button>
      </div>
    </div>
    <div class="chart"></div>`;
  card.querySelector('.chart-title').addEventListener('change', (e) => { cfg.title = e.target.value.trim() || '未命名图表'; saveLayout(); });
  card.querySelector('.pick-signals').addEventListener('click', () => openSignalPicker(cfg.id));
  card.querySelector('.remove-chart').addEventListener('click', () => removeChart(cfg.id));
  document.getElementById('chartGrid').appendChild(card);
  echartInstances[cfg.id] = echarts.init(card.querySelector('.chart'), 'dark');
  renderChart(cfg);
}

function renderLayout() {
  document.getElementById('chartGrid').innerHTML = '';
  Object.keys(echartInstances).forEach((id) => { try { echartInstances[id].dispose(); } catch { /* ignore */ } delete echartInstances[id]; });
  CHARTS.forEach(makeChartCard);
}
function addChart() {
  const cfg = { id: uid(), title: `图表 ${CHARTS.length + 1}`, signals: [] };
  CHARTS.push(cfg);
  makeChartCard(cfg);
  saveLayout();
  openSignalPicker(cfg.id);
}
function removeChart(id) {
  const inst = echartInstances[id];
  if (inst) { try { inst.dispose(); } catch { /* ignore */ } delete echartInstances[id]; }
  CHARTS = CHARTS.filter((c) => c.id !== id);
  const card = document.querySelector(`.chart-card[data-id="${id}"]`);
  if (card) card.remove();
  saveLayout();
}
function resetLayout() {
  if (!confirm('重置为默认图表布局？当前自定义会被覆盖。')) return;
  CHARTS = seedDefaults();
  renderLayout();
  saveLayout();
  refreshCharts();
}

// 刷新所有图表：按需拉取相关数据源（一源一次），再各自渲染
async function refreshCharts() {
  const keys = new Set();
  CHARTS.forEach((c) => c.signals.forEach((k) => keys.add(k)));
  const fetchKeys = new Set();
  keys.forEach((k) => fetchKeys.add(fetchKeyOf(k.split('::')[0])));
  POOL = {};
  await Promise.all([...fetchKeys].map((fk) => loadSource(fk).catch((e) => console.warn('数据源刷新失败', fk, e.message))));
  CHARTS.forEach(renderChart);
}

// ============ 信号选择弹窗 ============
let pickerChartId = null;
function openSignalPicker(id) {
  const cfg = CHARTS.find((c) => c.id === id);
  if (!cfg) return;
  pickerChartId = id;
  const sel = new Set(cfg.signals);
  const groups = {};
  CATALOG.forEach((e) => { (groups[e.group] = groups[e.group] || []).push(e); });
  const body = document.getElementById('signalModalBody');
  body.innerHTML = Object.entries(groups).map(([g, items]) => `
    <div class="sig-group" data-group="${escapeHtml(g)}">
      <div class="sig-group-title">${escapeHtml(g)}
        <button class="linkbtn grp-all">全选</button><button class="linkbtn grp-none">清空</button>
      </div>
      <div class="sig-items">
        ${items.map((it) => `<label class="sig-item"><input type="checkbox" value="${it.key}" ${sel.has(it.key) ? 'checked' : ''}/>${escapeHtml(it.label)}${it.unit ? ` <span class="u">(${it.unit})</span>` : ''}</label>`).join('')}
      </div>
    </div>`).join('');
  body.querySelectorAll('.grp-all').forEach((b) => b.addEventListener('click', () => { b.closest('.sig-group').querySelectorAll('input').forEach((i) => { if (i.parentElement.style.display !== 'none') i.checked = true; }); updateSignalCount(); }));
  body.querySelectorAll('.grp-none').forEach((b) => b.addEventListener('click', () => { b.closest('.sig-group').querySelectorAll('input').forEach((i) => { i.checked = false; }); updateSignalCount(); }));
  body.querySelectorAll('input[type=checkbox]').forEach((i) => i.addEventListener('change', updateSignalCount));
  document.getElementById('signalSearch').value = '';
  filterSignals('');
  document.getElementById('signalModalTitle').textContent = `选择信号 — ${cfg.title || ''}`;
  updateSignalCount();
  showModal('signalModal');
}
function updateSignalCount() {
  const n = document.querySelectorAll('#signalModalBody input[type=checkbox]:checked').length;
  document.getElementById('signalCount').textContent = `已选 ${n} 个信号`;
}
function filterSignals(q) {
  const kw = q.trim().toLowerCase();
  document.querySelectorAll('#signalModalBody .sig-group').forEach((grp) => {
    let visible = 0;
    grp.querySelectorAll('.sig-item').forEach((item) => {
      const hit = !kw || item.textContent.toLowerCase().includes(kw) || grp.dataset.group.toLowerCase().includes(kw);
      item.style.display = hit ? '' : 'none';
      if (hit) visible++;
    });
    grp.style.display = visible ? '' : 'none';
  });
}
function applySignalPicker() {
  const cfg = CHARTS.find((c) => c.id === pickerChartId);
  if (!cfg) { hideModal('signalModal'); return; }
  cfg.signals = [...document.querySelectorAll('#signalModalBody input[type=checkbox]:checked')].map((i) => i.value);
  saveLayout();
  hideModal('signalModal');
  refreshCharts();
}

// ============ 振动波形（原始抓取块）查看 ============
let vibChart = null;
let vibEventsBound = false;
function waveOption(x, series) {
  const nameStyle = { color: '#94a3b8', fontSize: 11 };
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', top: 0, textStyle: { color: '#94a3b8', fontSize: 11 } },
    grid: { left: 62, right: 18, top: 34, bottom: 44 },
    xAxis: { type: 'category', data: x, name: '样本序号', nameLocation: 'middle', nameGap: 26, nameTextStyle: nameStyle, axisLabel: { color: '#64748b', fontSize: 10 } },
    yAxis: { type: 'value', scale: true, name: '振动加速度 (g)', nameLocation: 'middle', nameGap: 46, nameTextStyle: nameStyle, axisLabel: { color: '#64748b', fontSize: 10 }, splitLine: { lineStyle: { color: '#1f2b3e' } } },
    series,
  };
}
async function loadVibEvents() {
  const sel = document.getElementById('vibEvent');
  const evs = await getJSON(`${API}/api/vib/events?limit=50`);
  const cur = sel.value;
  sel.innerHTML = evs.length
    ? evs.map((e) => {
        const t = new Date(e.time).toLocaleString('zh-CN', { hour12: false });
        const tag = e.trigger === 'manual' ? '手动' : (e.trigger || '事件');
        return `<option value="${e.id}">#${e.id} ${tag} ${t}</option>`;
      }).join('')
    : '<option value="">（暂无原始块，点「抓取波形」）</option>';
  if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
  if (!vibEventsBound) { sel.addEventListener('change', () => refreshVibBlock()); vibEventsBound = true; }
}
async function refreshVibBlock() {
  const ev = document.getElementById('vibEvent').value;
  if (!ev) { vibChart.setOption(waveOption([], []), true); return; }
  const d = await getJSON(`${API}/api/vib/block?event=${encodeURIComponent(ev)}&maxPoints=2000`);
  const chans = d.channels || [];
  const maxLen = chans.reduce((m, c) => Math.max(m, c.data.length), 0);
  const x = Array.from({ length: maxLen }, (_, i) => String(i));
  const series = chans.map((c) => ({ name: `通道${c.channel}`, type: 'line', showSymbol: false, data: c.data }));
  vibChart.setOption(waveOption(x, series), true);
}

// ============ 采集控制（OPC UA 与 NI 两块独立）============
function badge(el, kind, text) { el.className = 'badge ' + kind; el.textContent = text; }
function setConn(ok, msg) {
  const el = document.getElementById('conn');
  el.className = 'conn ' + (ok ? 'conn-ok' : 'conn-bad');
  el.textContent = '● ' + msg;
}
async function refreshControls() {
  try {
    const o = await getJSON(`${API}/api/opcua/status`);
    const b = document.getElementById('opcuaBadge');
    if (o.running) badge(b, 'badge-on', '采集中'); else badge(b, 'badge-off', '已停止');
    document.getElementById('opcuaStart').disabled = !!o.running;
    document.getElementById('opcuaStop').disabled = !o.running;
    document.getElementById('opcuaInfo').textContent = o.lastError ? `错误: ${o.lastError}` : `${o.profile || ''} ${o.endpoint || ''}`;
  } catch (e) { /* ignore */ }
  try {
    const n = await getJSON(`${API}/api/ni/status`);
    const b = document.getElementById('niBadge');
    if (!n.daemonAlive) badge(b, 'badge-off', '采集器离线');
    else if (n.ni_state === 'error') badge(b, 'badge-warn', '错误');
    else if (n.ni_run) badge(b, 'badge-on', '采集中');
    else badge(b, 'badge-warn', '就绪');
    document.getElementById('niStart').disabled = !n.daemonAlive || n.ni_run;
    document.getElementById('niStop').disabled = !n.ni_run;
    document.getElementById('niCapture').disabled = !n.daemonAlive || !n.ni_run;
    let info = '';
    if (!n.daemonAlive) info = '请在硬件主机运行 Collector.exe';
    else if (n.ni_state === 'error') info = `错误: ${n.ni_message || ''}`;
    else if (n.ni_run) info = `${n.session || ''} · ${Math.round(n.ni_sps).toLocaleString()} 样本/秒`;
    else info = '采集器在线，等待开始';
    document.getElementById('niInfo').textContent = info;
  } catch (e) { /* ignore */ }
}
async function post(url) {
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
  return res.json();
}
function bindControls() {
  const guard = (fn) => async (e) => {
    const btn = e.currentTarget; btn.disabled = true;
    try { await fn(); } catch (err) { alert('操作失败: ' + err.message); }
    finally { await refreshControls(); }
  };
  document.getElementById('opcuaStart').addEventListener('click', guard(() => post(`${API}/api/opcua/start`)));
  document.getElementById('opcuaStop').addEventListener('click', guard(() => post(`${API}/api/opcua/stop`)));
  document.getElementById('niStart').addEventListener('click', guard(() => post(`${API}/api/ni/start`)));
  document.getElementById('niStop').addEventListener('click', guard(() => post(`${API}/api/ni/stop`)));
  document.getElementById('niCapture').addEventListener('click', guard(async () => {
    await post(`${API}/api/ni/capture`);
    setTimeout(() => loadVibEvents().catch(() => {}), 1500);
  }));
}

// ============ 数据导出弹窗 ============
function dl(url) { const a = document.createElement('a'); a.href = url; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); }
function rangeQ() { const f = fromParam(); return f ? `from=${encodeURIComponent(f)}` : ''; }
async function openExport() {
  const sel = document.getElementById('expEvent');
  try {
    const evs = await getJSON(`${API}/api/vib/events?limit=100`);
    sel.innerHTML = evs.length
      ? evs.map((e) => `<option value="${e.id}">#${e.id} ${e.trigger === 'manual' ? '手动' : (e.trigger || '事件')} ${new Date(e.time).toLocaleString('zh-CN', { hour12: false })}</option>`).join('')
      : '<option value="">（暂无抓取块）</option>';
  } catch { sel.innerHTML = '<option value="">（读取失败）</option>'; }
  showModal('exportModal');
}
function bindExport() {
  document.getElementById('expBlockGo').addEventListener('click', () => {
    const ev = document.getElementById('expEvent').value;
    if (!ev) { alert('无可导出的抓取块'); return; }
    dl(`${API}/api/export/vib/block?event=${encodeURIComponent(ev)}`);
  });
  document.getElementById('expFeatGo').addEventListener('click', () => {
    const ch = document.getElementById('expFeatCh').value.trim();
    const q = [rangeQ(), ch ? `channels=${encodeURIComponent(ch)}` : ''].filter(Boolean).join('&');
    dl(`${API}/api/export/vib/features${q ? '?' + q : ''}`);
  });
  document.getElementById('expOpcGo').addEventListener('click', () => {
    const t = document.getElementById('expOpcTable').value;
    const mx = document.getElementById('expOpcMax').value.trim();
    const q = [`table=${t}`, rangeQ(), mx ? `maxPoints=${encodeURIComponent(mx)}` : ''].filter(Boolean).join('&');
    dl(`${API}/api/export/opcua?${q}`);
  });
}

// ============ 弹窗通用 ============
function showModal(id) { document.getElementById(id).classList.remove('hidden'); }
function hideModal(id) { document.getElementById(id).classList.add('hidden'); }
function bindModals() {
  document.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => hideModal(b.dataset.close)));
  document.querySelectorAll('.modal').forEach((m) => m.addEventListener('click', (e) => { if (e.target === m) hideModal(m.id); }));
  document.getElementById('signalModalApply').addEventListener('click', applySignalPicker);
  document.getElementById('signalSearch').addEventListener('input', (e) => filterSignals(e.target.value));
}

// ============ 总刷新 / 启动 ============
async function refreshAll() {
  try { await getJSON(`${API}/api/health`); setConn(true, '已连接'); }
  catch (e) { setConn(false, '数据库未连接'); return; }
  const results = await Promise.allSettled([
    refreshCharts(),
    loadVibEvents().then(refreshVibBlock),
    refreshControls(),
  ]);
  results.forEach((r) => { if (r.status === 'rejected') console.warn('刷新失败:', r.reason?.message); });
}

let timer = null;
function applyRefreshInterval() {
  if (timer) { clearInterval(timer); timer = null; }
  const ms = Number(document.getElementById('refreshSelect').value);
  if (ms > 0) timer = setInterval(refreshAll, ms);
}

function boot() {
  buildCatalog();
  vibChart = echarts.init(document.getElementById('chartVib'), 'dark');
  bindControls();
  bindModals();
  bindExport();

  const saved = loadLayout();
  CHARTS = saved || seedDefaults();
  renderLayout();
  if (!saved) saveLayout();

  document.getElementById('addChartBtn').addEventListener('click', addChart);
  document.getElementById('resetLayoutBtn').addEventListener('click', resetLayout);
  document.getElementById('exportBtn').addEventListener('click', openExport);
  document.getElementById('exportBlockBtn').addEventListener('click', () => {
    const ev = document.getElementById('vibEvent').value;
    if (!ev) { alert('请先选择一个抓取块'); return; }
    dl(`${API}/api/export/vib/block?event=${encodeURIComponent(ev)}`);
  });
  document.getElementById('rangeSelect').addEventListener('change', refreshAll);
  document.getElementById('refreshSelect').addEventListener('change', applyRefreshInterval);
  window.addEventListener('resize', () => { Object.values(echartInstances).forEach((c) => c.resize()); if (vibChart) vibChart.resize(); });

  refreshAll().catch((e) => { setConn(false, '加载失败'); console.error(e); });
  applyRefreshInterval();
}
boot();
