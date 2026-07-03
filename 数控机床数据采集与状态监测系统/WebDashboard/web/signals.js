// 采集信号清单：现场采集工作台维护 OPC UA 采集地址与启用集合。
// 数据来源：/api/opcua/catalog（列↔节点↔类型↔最新值）+ /api/config（振动通道）+ /api/vib/features（最新特征）。

const $ = (id) => document.getElementById(id);
let latestCatalog = null;
let formDirty = false;
const MACHINE_ID = new URLSearchParams(location.search).get('machine_id') || '';
const apiUrl = (path) => MACHINE_ID ? `${path}${path.includes('?') ? '&' : '?'}machine_id=${encodeURIComponent(MACHINE_ID)}` : path;

async function getJSON(url) {
  const res = await fetch(apiUrl(url));
  if (!res.ok) throw new Error(`${res.status} ${(await res.json().catch(() => ({}))).error || res.statusText}`);
  return res.json();
}
async function putJSON(url, body) {
  const res = await fetch(apiUrl(url), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...(body || {}), machine_id: MACHINE_ID }) });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || json.ok === false) throw new Error(json.error || `${res.status} ${res.statusText}`);
  return json;
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
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m])); }
function setConn(ok, msg) {
  const el = $('conn');
  el.className = 'conn ' + (ok ? 'conn-ok' : 'conn-bad');
  el.textContent = '● ' + msg;
}

function renderOpcuaStatus(cat) {
  const s = cat.status || {};
  let state, cls;
  if (s.running && s.connected) { state = '采集中'; cls = 'badge-on'; }
  else if (s.lastError) { state = '错误'; cls = 'badge-off'; }
  else { state = '已停止'; cls = 'badge-off'; }
  const enabledCount = (cat.groups || []).flatMap((g) => g.signals || []).filter((x) => x.enabled !== false).length;
  const totalCount = (cat.groups || []).flatMap((g) => g.signals || []).length;
  const bar = $('opcuaStatus');
  bar.innerHTML = `
    <span class="kv">状态 <span class="badge ${cls}">${state}</span></span>
    <span class="kv">地址配置 <b>${esc(cat.profile || '')}</b></span>
    <span class="kv">OPC UA 地址 <b>${esc(cat.endpoint || '')}</b></span>
    <span class="kv">轮询间隔 <b>${cat.pollIntervalMs ?? '?'} ms</b></span>
    <span class="kv">启用信号 <b>${enabledCount}/${totalCount}</b></span>
    <span class="kv">最近成功采样 <b>${fmtTime(s.lastOkAt)}</b></span>
    <button class="btn secondary" id="saveSelection">保存采集选择</button>
    ${s.lastError ? `<span class="kv err">错误：${esc(s.lastError)}</span>` : ''}`;
  const save = $('saveSelection');
  if (save) save.onclick = saveSelection;
}

function renderOpcuaGroups(cat) {
  const box = $('opcuaGroups');
  box.innerHTML = (cat.groups || []).map((g) => {
    const rows = (g.signals || []).map((sg, i) => {
      const v = fmtVal(sg.value, sg.type);
      return `<tr class="${sg.enabled === false ? 'disabled' : ''}" data-sid="${esc(sg.id)}">
        <td class="muted">${i + 1}</td>
        <td><input type="checkbox" class="sig-enable" ${sg.enabled === false ? '' : 'checked'} ${sg.derived ? 'disabled' : ''}></td>
        <td>${esc(sg.label)}${sg.derived ? '<span class="pill pill-derived">派生</span>' : ''}</td>
        <td class="col">${esc(sg.col)}</td>
        <td><input class="node-edit" value="${esc(sg.node)}" ${sg.derived ? 'disabled' : ''}></td>
        <td><span class="pill pill-type">${esc(sg.type || '')}</span></td>
        <td class="val ${v.na ? 'na' : ''}">${esc(v.text)}</td>
        <td><button class="btn mini save-node" ${sg.derived ? 'disabled' : ''}>保存地址</button></td>
      </tr>`;
    }).join('');
    return `<div class="panel">
      <h2>${esc(g.title)} <span class="meta">${g.table} · ${g.signals.length} 个 OPC UA 信号 · 最新采样 ${fmtTime(g.latestTime)}</span></h2>
      <table class="sig">
        <thead><tr>
          <th style="width:40px">#</th><th style="width:70px">采集</th><th style="width:220px">信号名</th>
          <th style="width:170px">编码</th><th>OPC UA 节点地址</th>
          <th style="width:90px">类型</th><th style="width:110px">最新实测值</th><th style="width:90px"></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }).join('');
  box.querySelectorAll('.node-edit, .sig-enable').forEach((el) => {
    el.addEventListener('input', () => { formDirty = true; });
    el.addEventListener('change', () => { formDirty = true; });
  });
  box.querySelectorAll('.save-node').forEach((btn) => {
    btn.onclick = async () => {
      const tr = btn.closest('tr');
      const id = tr?.dataset.sid;
      const source_addr = tr?.querySelector('.node-edit')?.value?.trim() || '';
      if (!id) return;
      btn.disabled = true;
      try {
        await putJSON(`/api/signals/${encodeURIComponent(id)}`, { source_addr });
        formDirty = false;
        setConn(true, '地址已保存');
        await loadOpcua({ force: true });
      } catch (e) {
        setConn(false, '保存失败：' + e.message);
      } finally {
        btn.disabled = false;
      }
    };
  });
}

async function saveSelection() {
  const ids = [...document.querySelectorAll('#opcuaGroups tr[data-sid]')]
    .filter((tr) => tr.querySelector('.sig-enable')?.checked)
    .map((tr) => Number(tr.dataset.sid))
    .filter((x) => Number.isInteger(x));
  try {
    await putJSON('/api/opcua/selection', { enabledSignalIds: ids });
    formDirty = false;
    setConn(true, `采集选择已保存：${ids.length} 个信号`);
    await loadOpcua({ force: true });
  } catch (e) {
    setConn(false, '保存失败：' + e.message);
  }
}

function shouldHoldOpcuaRefresh() {
  const box = $('opcuaGroups');
  const active = document.activeElement;
  return formDirty || (box && active && box.contains(active));
}

async function loadOpcua(opts = {}) {
  if (!opts.force && shouldHoldOpcuaRefresh()) return { skipped: true };
  const cat = await getJSON('/api/opcua/catalog');
  latestCatalog = cat;
  renderOpcuaStatus(cat);
  renderOpcuaGroups(cat);
  return { skipped: false };
}

async function loadVibration() {
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

  const feat = await getJSON('/api/vib/features?maxPoints=1');
  const byCh = new Map();
  for (const r of feat.rows || []) byCh.set(r.channel, r);
  const rows = [...byCh.values()].sort((x, y) => x.channel - y.channel);
  const cell = (v) => { const f = fmtVal(v, 'num'); return `<td class="val ${f.na ? 'na' : ''}">${esc(f.text)}</td>`; };
  $('vibLatest').querySelector('tbody').innerHTML = rows.length
    ? rows.map((r) => `<tr>
        <td class="muted">通道 ${r.channel}</td><td>${fmtTime(r.time)}</td>
        ${cell(r.rms)}${cell(r.peak)}${cell(r.p2p)}${cell(r.std)}${cell(r.kurtosis)}${cell(r.crest)}
      </tr>`).join('')
    : '<tr><td colspan="8" class="muted">暂无特征数据（NI 采集尚未产生 vib_features）</td></tr>';
}

async function refreshAll() {
  const holdOpcua = shouldHoldOpcuaRefresh();
  const results = await Promise.allSettled([holdOpcua ? Promise.resolve({ skipped: true }) : loadOpcua(), loadVibration()]);
  const failed = results.filter((r) => r.status === 'rejected');
  if (holdOpcua) setConn(true, '有未保存编辑，已暂停 OPC UA 清单刷新');
  else if (failed.length === results.length) { setConn(false, '加载失败：' + (failed[0].reason?.message || '')); }
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
  if (MACHINE_ID) {
    const brandTag = document.querySelector('.brand .tag');
    if (brandTag) brandTag.textContent = MACHINE_ID;
    document.querySelectorAll('a.navlink').forEach((a) => {
      const href = a.getAttribute('href') || '';
      if (href.startsWith('/')) a.setAttribute('href', `${href}${href.includes('?') ? '&' : '?'}machine_id=${encodeURIComponent(MACHINE_ID)}`);
    });
  }
  const ctl = document.createElement('span');
  ctl.className = 'refreshctl';
  ctl.innerHTML = `刷新 <select id="refreshSel">
    <option value="0" selected>关闭</option>
    <option value="3000">3 秒</option>
    <option value="10000">10 秒</option>
  </select>`;
  document.querySelector('.topbar .controls').prepend(ctl);
  $('refreshSel').addEventListener('change', applyInterval);

  refreshAll().catch((e) => setConn(false, '加载失败: ' + e.message));
  applyInterval();
}
boot();



