// 采集信号清单：把"到底采了哪些变量、地址是什么、现在读到值没有"一屏列清。
// 数据来源：/api/opcua/catalog（列↔节点↔类型↔最新值）+ /api/config（振动通道）+ /api/vib/features（最新特征）。
// 纯只读展示，不触发任何采集动作。

const $ = (id) => document.getElementById(id);

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${(await res.json().catch(() => ({}))).error || res.statusText}`);
  return res.json();
}

function fmtVal(v, type) {
  if (v === null || v === undefined) return { text: '—', na: true };
  if (type === 'bool' || typeof v === 'boolean') return { text: v ? '是' : '否', na: false };
  if (typeof v === 'number') return { text: Number.isInteger(v) ? String(v) : v.toFixed(3), na: false };
  return { text: String(v), na: false };
}
function fmtTime(t) {
  if (!t) return '—';
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? String(t) : d.toLocaleString('zh-CN', { hour12: false });
}
function esc(s) { return String(s).replace(/[&<>"]/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m])); }

function renderOpcuaStatus(cat) {
  const s = cat.status || {};
  let state, cls;
  if (s.running && s.connected) { state = '采集中'; cls = 'badge-on'; }
  else if (s.lastError) { state = '错误'; cls = 'badge-off'; }
  else { state = '已停止'; cls = 'badge-off'; }
  const bar = $('opcuaStatus');
  bar.innerHTML = `
    <span class="kv">状态 <span class="badge ${cls}">${state}</span></span>
    <span class="kv">地址 profile <b>${esc(cat.profile || '')}</b></span>
    <span class="kv">Endpoint <b>${esc(cat.endpoint || '')}</b></span>
    <span class="kv">轮询间隔 <b>${cat.pollIntervalMs ?? '?'} ms</b></span>
    <span class="kv">去重节点数 <b>${cat.nodeCount ?? '?'}</b></span>
    <span class="kv">最近成功采样 <b>${fmtTime(s.lastOkAt)}</b></span>
    ${s.lastError ? `<span class="kv err">错误：${esc(s.lastError)}</span>` : ''}`;
}

function renderOpcuaGroups(cat) {
  const box = $('opcuaGroups');
  box.innerHTML = (cat.groups || []).map((g) => {
    const rows = g.signals.map((sg, i) => {
      const v = fmtVal(sg.value, sg.type);
      return `<tr class="${sg.derived ? 'derived' : ''}">
        <td class="muted">${i + 1}</td>
        <td>${esc(sg.label)}${sg.derived ? '<span class="pill pill-derived">派生</span>' : ''}</td>
        <td class="col">${esc(sg.col)}</td>
        <td class="node">${esc(sg.node)}</td>
        <td><span class="pill pill-type">${esc(sg.type || '')}</span></td>
        <td class="val ${v.na ? 'na' : ''}">${esc(v.text)}</td>
      </tr>`;
    }).join('');
    return `<div class="panel">
      <h2>${esc(g.title)} <span class="meta">${g.table} · ${g.signals.length} 个信号 · 最新采样 ${fmtTime(g.latestTime)}</span></h2>
      <table class="sig">
        <thead><tr>
          <th style="width:40px">#</th><th style="width:220px">信号名</th>
          <th style="width:200px">数据库列</th><th>OPC UA 节点地址</th>
          <th style="width:90px">类型</th><th style="width:110px">最新实测值</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }).join('');
}

async function loadOpcua() {
  const cat = await getJSON('/api/opcua/catalog');
  renderOpcuaStatus(cat);
  renderOpcuaGroups(cat);
}

async function loadVibration() {
  // 采集参数 + 通道配置
  const cfg = await getJSON('/api/config');
  const a = cfg.acquisition || {};
  $('vibParams').textContent =
    `采集源=${a.source} · 采样率=${a.rate} Hz · 每通道样本=${a.samplesPerChannel} · `
    + `特征窗=${a.featureWindowSamples ? a.featureWindowSamples + ' 样本' : '采样率(1秒/窗)'} · `
    + `事件原始=${a.eventEnabled ? '开(阈值 ' + a.eventRmsThresholdG + ' g)' : '关'}`;
  const chs = a.channels || [];
  $('vibChannels').querySelector('tbody').innerHTML = chs.length
    ? chs.map((c, i) => `<tr><td class="muted">${i + 1}</td><td class="col">${esc(c.physicalChannel)}</td><td>${c.sensitivityMvPerG}</td></tr>`).join('')
    : '<tr><td colspan="3" class="muted">未配置通道（在采集配置页添加）</td></tr>';

  // 各通道最新特征值（每通道最近一窗）。接口按 time 升序返回每通道多行，
  // 这里取每通道最后（=最新）一行。
  const feat = await getJSON('/api/vib/features?maxPoints=1');
  const byCh = new Map();
  for (const r of feat.rows || []) byCh.set(r.channel, r); // 升序遍历，最后覆盖即最新
  const rows = [...byCh.values()].sort((x, y) => x.channel - y.channel);
  const cell = (v) => { const f = fmtVal(v, 'num'); return `<td class="val ${f.na ? 'na' : ''}">${esc(f.text)}</td>`; };
  $('vibLatest').querySelector('tbody').innerHTML = rows.length
    ? rows.map((r) => `<tr>
        <td class="muted">通道 ${r.channel}</td><td>${fmtTime(r.time)}</td>
        ${cell(r.rms)}${cell(r.peak)}${cell(r.p2p)}${cell(r.std)}${cell(r.kurtosis)}${cell(r.crest)}
      </tr>`).join('')
    : '<tr><td colspan="8" class="muted">暂无特征数据（NI 采集尚未产生 vib_features）</td></tr>';
}

function setConn(ok, msg) {
  const el = $('conn');
  el.className = 'conn ' + (ok ? 'conn-ok' : 'conn-bad');
  el.textContent = '● ' + msg;
}

async function refreshAll() {
  const results = await Promise.allSettled([loadOpcua(), loadVibration()]);
  const failed = results.filter((r) => r.status === 'rejected');
  if (failed.length === results.length) { setConn(false, '加载失败：' + (failed[0].reason?.message || '')); }
  else setConn(true, '已连接');
  failed.forEach((r) => console.warn('信号清单刷新失败:', r.reason?.message));
}

let timer = null;
function applyInterval() {
  if (timer) { clearInterval(timer); timer = null; }
  const ms = Number($('refreshSel').value);
  if (ms > 0) timer = setInterval(refreshAll, ms);
}

function boot() {
  // 顶栏挂一个刷新间隔选择器
  const ctl = document.createElement('span');
  ctl.className = 'refreshctl';
  ctl.innerHTML = `刷新 <select id="refreshSel">
    <option value="0">关闭</option>
    <option value="3000" selected>3 秒</option>
    <option value="10000">10 秒</option>
  </select>`;
  document.querySelector('.topbar .controls').prepend(ctl);
  $('refreshSel').addEventListener('change', applyInterval);

  refreshAll().catch((e) => setConn(false, '加载失败: ' + e.message));
  applyInterval();
}
boot();
