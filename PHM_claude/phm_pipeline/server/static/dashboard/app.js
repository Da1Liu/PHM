/* 机床健康中心看板 — 纯原生 SPA, 无外部依赖. */
"use strict";
const S = { machines: [], machine: null, page: "overview" };
const $ = (s, r = document) => r.querySelector(s);
const api = (u) => fetch(u).then(r => r.json());
const esc = (s) => String(s == null ? "" : s).replace(/[<>&]/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));
const LIGHT_CN = { green: "正常", yellow: "关注", red: "告警", building: "建立中" };
const LIGHT_HEX = { green: "#26c281", yellow: "#f4b740", red: "#e5484d", building: "#6b86a3" };

/* 轻量提示 (替代 alert) */
function toast(msg, ms = 2200) {
  let t = $("#toast"); if (!t) { t = document.createElement("div"); t.id = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.className = "show";
  clearTimeout(toast._t); toast._t = setTimeout(() => t.className = "", ms);
}
/* 时间格式化 (epoch秒 -> 本地可读) */
function fmtTime(sec) {
  if (!sec) return "—";
  const d = new Date(sec * 1000), p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function fmtDate(sec) { const d = new Date(sec * 1000), p = n => String(n).padStart(2, "0"); return `${p(d.getMonth() + 1)}/${p(d.getDate())}`; }

/* 健康环形仪表 (SVG) */
function healthRing(val, light, size = 120) {
  const r = size / 2 - 9, cx = size / 2, c = 2 * Math.PI * r, off = c * (1 - (val ?? 0));
  const col = LIGHT_HEX[light] || "#3da9fc";
  const label = val == null ? "—" : Math.round(val * 100);
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" class="ring">
    <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="var(--panel2)" stroke-width="9"/>
    <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${col}" stroke-width="9"
      stroke-linecap="round" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"
      transform="rotate(-90 ${cx} ${cx})"/>
    <text x="${cx}" y="${cx - 2}" text-anchor="middle" font-size="${size * 0.28}" font-weight="800" fill="var(--txt)">${label}</text>
    <text x="${cx}" y="${cx + size * 0.16}" text-anchor="middle" font-size="${size * 0.1}" fill="var(--muted)">健康度</text>
  </svg>`;
}
/* 迷你 sparkline */
function sparkline(vals, w = 220, h = 40) {
  if (!vals || vals.length < 2) return "";
  const xs = i => i * w / (vals.length - 1), ys = v => h - 3 - v * (h - 6);
  return `<svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="spark">
    <polyline fill="none" stroke="var(--accent)" stroke-width="1.5"
      points="${vals.map((v, i) => `${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(" ")}"/></svg>`;
}

/* ---------- 初始化 ---------- */
async function init() {
  markBigScreen();
  window.addEventListener("resize", markBigScreen);
  const r = await api("/api/machines").catch(() => ({ machines: [] }));
  S.machines = r.machines || [];
  S.machine = S.machines[0] ? S.machines[0].id : null;
  const sel = $("#machineSel");
  sel.innerHTML = S.machines.map(m => `<option value="${esc(m.id)}">${esc(m.id)} · ${esc(m.cnc || "")}</option>`).join("");
  sel.onchange = () => { S.machine = sel.value; setMachineMeta(); render(); };
  $("#layerBtn").onclick = toggleLayer;
  $("#refreshBtn").onclick = () => { $("#refreshBtn").classList.add("spin"); render(); setTimeout(() => $("#refreshBtn").classList.remove("spin"), 600); };
  document.querySelectorAll(".nav-item").forEach(b =>
    b.onclick = () => { S.page = b.dataset.page; setActiveNav(); render(); });
  setMachineMeta();
  startClock();
  connectWS();
  render();
  // 自动刷新: 仅总览页, 走软更新 (set-if-changed, 数据不变则无视觉跳动)
  setInterval(() => { if (S.page === "overview") updateOverview(); }, 15000);
}
let engInitTab = null;
function setMachineMeta() {
  const m = S.machines.find(x => x.id === S.machine);
  $("#machineMeta").textContent = m ? `${m.cnc || ""} · epoch ${m.epoch ?? 1}` : "";
}
function startClock() {
  const tick = () => { const d = new Date(), p = n => String(n).padStart(2, "0");
    $("#clock").textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; };
  tick(); setInterval(tick, 1000);
}
function markBigScreen() { document.body.dataset.bigscreen = window.innerWidth >= 1600 ? "1" : "0"; }
function setActiveNav() {
  document.querySelectorAll(".nav-item").forEach(b =>
    b.classList.toggle("active", b.dataset.page === S.page));
}
function toggleLayer() {
  const eng = document.body.dataset.layer === "engineer";
  // 工程视图入口 (脚手架: 简单确认; 现场可接 PIN)
  if (!eng && !confirm("进入工程视图? (现场将由 PIN 控制)")) return;
  document.body.dataset.layer = eng ? "operator" : "engineer";
  $("#layerBtn").textContent = eng ? "工程视图" : "操作工视图";
  if (eng && (S.page === "diagnose" || S.page === "settings")) { S.page = "overview"; setActiveNav(); }
  render();
}
function connectWS() {
  try {
    const ws = new WebSocket((location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/ws");
    ws.onopen = () => setConn(true);
    ws.onclose = () => setConn(false);
    ws.onmessage = (e) => { try { const m = JSON.parse(e.data); if (m.type === "update") render(); } catch (_) {} };
  } catch (_) { setConn(false); }
}
function setConn(on) {
  const c = $("#conn"); c.textContent = on ? "在线" : "离线";
  c.className = "conn " + (on ? "online" : "offline");
}

/* ---------- 路由 ---------- */
function render() {
  const m = $("#main");
  ({ overview: pageOverview, diagnose: pageDiagnose, baseline: pageBaseline,
     trend: pageTrend, settings: pageSettings }[S.page] || pageOverview)(m);
}

/* ---------- 总览 (操作工默认; 大屏=领导展示) ---------- */
function pageOverview(m) {
  // 骨架只在导航时建一次; 自动刷新走 updateOverview 软更新 (不重建 DOM, 不闪)
  m.innerHTML = `<div class="title-row"><h2 class="page-title">总览 · 各系统健康状态</h2>
    <span class="updated" id="updated"></span></div>
    <div id="fleet" class="fleet"></div>
    <div id="alarmbar"></div>
    <div id="ov" class="grid soft">加载中…</div>
    <div class="legend"><span><i class="dot green"></i>正常 ≥60</span><span><i class="dot yellow"></i>关注 30–60</span>
      <span><i class="dot red"></i>告警 &lt;30</span><span><i class="dot building"></i>建立期</span></div>`;
  updateOverview();
}
/* 仅当 HTML 变化才替换 DOM -> 数据不变时刷新无任何视觉跳动 */
function setHTML(sel, html) { const el = $(sel); if (el && el.innerHTML !== html) el.innerHTML = html; }

async function updateOverview() {
  if (!$("#ov")) return;  // 已离开总览
  const upd = $("#updated"); if (upd) upd.textContent = "更新于 " + fmtTime(Date.now() / 1000);
  // 机群条 (多机床快览/大屏; 末尾常驻"接入机床")
  Promise.all(S.machines.map(mc => api(`/api/status/${mc.id}`).then(s => ({ mc, s })).catch(() => null)))
    .then(arr => {
      const items = arr.filter(Boolean).map(({ mc, s }) =>
        `<button class="fleet-item ${mc.id === S.machine ? "sel" : ""}" onclick="selMachine('${esc(mc.id)}')">
          <span class="dot ${s.light}"></span><b>${esc(mc.id)}</b><em>${esc(s.message)}</em></button>`).join("");
      setHTML("#fleet", items + `<button class="fleet-item add" onclick="gotoMachines()">＋ 接入机床</button>`);
    });
  api(`/api/machine/${S.machine}/alarms`).then(a => {
    const al = (a.alarms || []);
    setHTML("#alarmbar", al.length ? al.map(x =>
      `<div class="alarm-row lv${x.level}"><span>⚠ ${esc(x.message)} <em class="sub">${fmtTime(x.ts)}</em></span>
        <button class="btn ghost" onclick="toast('告警已确认 (占位)')">确认</button></div>`).join("")
      : `<div class="alarm-row ok"><span>✓ 无活动告警</span></div>`);
  });
  const r = await api("/api/overview");
  const items = (r.items || []).filter(it => it.machine === S.machine);
  const trends = {};
  await Promise.all(items.map(it => api(`/api/machine/${S.machine}/trend?system=${it.system}`)
    .then(t => { trends[it.system] = (t.points || []).map(p => p.health); }).catch(() => {})));
  const html = items.map(it => {
    const light = it.light, dotcn = LIGHT_CN[light] || light;
    let visual, body;
    if (it.mode === "building") {
      const pct = Math.round(100 * it.n / it.N);
      visual = healthRing(it.n / it.N, "building");
      body = `<div class="health-msg">${esc(it.message)}</div>
        <div class="progress"><i style="width:${pct}%"></i></div>
        <div class="sub">进度 ${pct}% · 事件性采集(交班/热机), 建立期约以月计</div>`;
    } else if (it.mode === "status_only") {
      visual = `<div class="dot ${light} big"></div>`;
      body = `<div class="health-msg">${esc(it.message)}</div><span class="badge">仅 L1 状态 · 无连续量基线</span>`;
    } else {
      visual = healthRing(it.health, light);
      body = `<div class="health-msg">${esc(it.message)} · T²/SPE 详见诊断</div>${sparkline(trends[it.system])}`;
    }
    return `<div class="card sys-card">
      <div class="sys-head"><span class="dot ${light}"></span><h3>${esc(it.system_cn)}</h3>
        <span class="badge">${dotcn}</span></div>
      <div class="sys-body"><div class="sys-visual">${visual}</div><div class="sys-info">${body}</div></div>
    </div>`;
  }).join("") || `<div class="note">该机床暂无系统数据 · 在「工程设置 → 机床管理」接入并配置</div>`;
  setHTML("#ov", html);
}
function selMachine(id) { S.machine = id; $("#machineSel").value = id; setMachineMeta(); render(); }
function gotoMachines() { S.page = "settings"; engInitTab = "machines"; setActiveNav(); render(); }

/* ---------- 系统诊断 (工程层: T²/SPE 贡献) ---------- */
async function pageDiagnose(m) {
  const sys = await pickSystem(m, "系统诊断 · T²/SPE 贡献分解");
  const r = await api(`/api/machine/${S.machine}/diagnose?system=${sys}`);
  const host = $("#sysbody");
  if (r.mode === "building") { host.innerHTML = `<div class="note">基线建立中, 暂不评分, 无贡献分解。</div>`; return; }
  if (r.mode === "status_only") { host.innerHTML = `<div class="note">该系统仅 bool 状态监测, 无 PCA 模型。</div>`; return; }
  const ct = r.contributions || [];
  if (!ct.length) { host.innerHTML = `<div class="note">暂无贡献分解数据。</div>`; return; }
  // T²/SPE 各按自身最大值归一 (量纲不同); T² 单特征贡献可为负 → 按 0 截断显示
  const pos = v => Math.max(0, +v || 0);
  const maxT2 = Math.max(...ct.map(c => pos(c.t2)), 1e-9);
  const maxSPE = Math.max(...ct.map(c => pos(c.spe)), 1e-9);
  host.innerHTML = `<div class="card"><h3>当前 T² = ${r.t2} (UCL ${r.ucl_t2}) · SPE = ${r.spe} (UCL ${r.ucl_spe})</h3>
    <p class="sub">关系型异常看 <b style="color:var(--yellow)">SPE</b>; 各通道边际正常但耦合关系变了 → SPE 升高。点某行查看该通道原始波形。</p>
    ${ct.map(c => `<div class="diag-row" onclick="showWave('${esc(c.name)}')">
      <span class="nm" title="${esc(c.name)}">${esc(c.name)}</span>
      <div class="bars">
        <div class="diag-line"><span class="lbl">T²</span><div class="bar" title="T² 贡献 ${c.t2}"><i style="width:${100 * pos(c.t2) / maxT2}%"></i></div></div>
        <div class="diag-line"><span class="lbl">SPE</span><div class="bar spe" title="SPE 贡献 ${c.spe}"><i style="width:${100 * pos(c.spe) / maxSPE}%"></i></div></div>
      </div></div>`).join("")}
    <div class="legend"><span><i class="dot" style="background:var(--accent)"></i> T² 贡献 (主成分内)</span>
      <span><i class="dot" style="background:var(--yellow)"></i> SPE 贡献 (残差空间·关系型, 重点看)</span></div></div>
    <div id="wavebox"></div>`;
}
async function showWave(name) {
  const box = $("#wavebox"); if (!box) return;
  box.innerHTML = `<div class="card"><h3>原始波形 · ${esc(name)}</h3><div class="sub">加载中…</div></div>`;
  const r = await api(`/api/machine/${S.machine}/waveform?signal=${encodeURIComponent(name)}`);
  box.innerHTML = `<div class="card"><h3>原始波形 · ${esc(name)} <span class="badge">${r.rate}Hz${r.mock ? " · mock" : ""}</span></h3>
    ${lineChartRaw(r.samples)}</div>`;
}

/* ---------- 维护·基线 (epoch / reset / 建立进度) ---------- */
async function pageBaseline(m) {
  const sys = await pickSystem(m, "维护 · 基线");
  const r = await api(`/api/machine/${S.machine}/trend?system=${sys}`);
  const mc = S.machines.find(x => x.id === S.machine) || {};
  const host = $("#sysbody");
  let prog = "";
  if (r.mode === "building") {
    const pct = Math.round(100 * r.n / r.N);
    prog = `<div class="progress"><i style="width:${pct}%"></i></div><p class="sub">建立期 ${r.n}/${r.N} (${pct}%)</p>`;
  }
  host.innerHTML = `<div class="card"><h3>基线 epoch ${mc.epoch ?? 1}</h3>
    <p class="sub">大修/拆装后 reset 基线 (跨 epoch 不可比)。维护好坏看绝对裸指标台阶 + 维护后稳定性, 不看综合分。</p>
    ${prog}
    <div style="margin-top:14px;display:flex;gap:10px">
      <button class="btn warn" onclick="alert('reset 基线: 脚手架占位, 接 epoch+1 流程')">大修后 reset 基线</button>
      <button class="btn" onclick="alert('标注维护事件: 脚手架占位')">标注维护事件</button>
    </div></div>`;
}

/* ---------- 趋势·历史 (SVG 折线) ---------- */
async function pageTrend(m) {
  const sys = await pickSystem(m, "趋势 · 历史");
  const r = await api(`/api/machine/${S.machine}/trend?system=${sys}`);
  const host = $("#sysbody");
  if (r.mode === "status_only" || !r.points || !r.points.length) {
    host.innerHTML = `<div class="note">该系统无健康曲线 (仅状态监测或暂无数据)。</div>`; return;
  }
  host.innerHTML = `<div class="card"><h3>健康度趋势 (近 ${r.points.length} 个采集点)</h3>
    <p class="sub">事件性数据: 每交班/热机一点; 仅同一 epoch 内可比。</p>
    ${lineChart(r.points.map(p => p.health), r.points.map(p => p.t))}</div>`;
}

/* ---------- 工程设置 (工程层, 多 tab: 整合线B 采集配置/控制) ---------- */
const ENG_TABS = [["machines", "机床管理"], ["mapping", "信号映射"], ["acq", "采集配置"], ["ctrl", "采集控制"], ["status", "同步·状态"]];
async function pageSettings(m) {
  if (!m.querySelector("#engtabs")) {
    m.innerHTML = `<h2 class="page-title">工程设置</h2>
      <div id="engmachbar" class="tabbar machbar"></div>
      <div id="engtabs" class="tabbar">${ENG_TABS.map(t => `<button class="tab" data-tab="${t[0]}">${t[1]}</button>`).join("")}</div>
      <div id="engbody">加载中…</div>`;
    m._tab = engInitTab || "machines"; engInitTab = null;
    m.querySelectorAll("#engtabs .tab").forEach(b => b.onclick = () => { m._tab = b.dataset.tab; markTabs(); renderEngTab(); });
  } else {
    m._tab = engInitTab || m._tab; engInitTab = null;
  }
  renderEngMachBar();
  markTabs();
  renderEngTab();
}
/* 工程设置顶部机床快捷切换条 (各 tab 共用, 切换即作用于当前 tab) */
function renderEngMachBar() {
  const bar = $("#engmachbar"); if (!bar) return;
  bar.innerHTML = `<span class="sub" style="margin:0 4px 0 2px">机床</span>` +
    S.machines.map(m => `<button class="tab ${m.id === S.machine ? "on" : ""}" onclick="setEngMachine('${esc(m.id)}')">${esc(m.id)}</button>`).join("")
    || `<span class="sub">无机床, 先在「机床管理」接入</span>`;
}
function setEngMachine(id) {
  if (id === S.machine) return;
  S.machine = id;
  const sel = $("#machineSel"); if (sel) sel.value = id;
  setMachineMeta();
  renderEngMachBar();
  renderEngTab();
}
function markTabs() {
  const m = $("#main");
  m.querySelectorAll("#engtabs .tab").forEach(b => b.classList.toggle("on", b.dataset.tab === m._tab));
}
function renderEngTab() {
  const m = $("#main"), tab = m._tab || "machines";
  ({ machines: engMachines, mapping: engMapping, acq: engAcq, ctrl: engCtrl, status: engStatus }[tab])($("#engbody"));
}

async function engMachines(host) {
  host.innerHTML = "加载中…";
  const r = await api("/api/machines");
  const ms = r.machines || [];
  const SYS_CN = { spindle: "主轴", feed: "进给", hydraulic: "液压" };
  host.innerHTML = `<div class="card"><table>
    <thead><tr><th>机床 SN</th><th>数控系统</th><th>epoch</th><th>系统</th><th></th></tr></thead>
    <tbody>${ms.map(m => `<tr>
      <td><b>${esc(m.id)}</b></td><td>${esc(m.cnc || "—")}</td><td>${m.epoch ?? 1}</td>
      <td>${(m.systems || []).map(s => `<span class="tag">${SYS_CN[s] || s}</span>`).join(" ") || "<span class='sub'>未配置信号</span>"}</td>
      <td style="white-space:nowrap"><button class="lk" onclick="selMachine('${esc(m.id)}')">查看</button>
        <button class="lk del" onclick="delMachine('${esc(m.id)}')">删除</button></td>
    </tr>`).join("")}</tbody></table>
    <p class="sub" style="margin-top:8px">共 ${ms.length} 台 · 每台独立 signal 维表 + acq_config + epoch, 协议/地址可各不相同。</p></div>
  <div class="card"><h3>接入新机床</h3>
    <label class="cfg-row"><span>机床 SN</span><input id="nm_id" placeholder="如 CNC_02"></label>
    <label class="cfg-row"><span>数控系统</span><input id="nm_cnc" placeholder="siemens_840d / huazhong / …"></label>
    <button class="btn" onclick="addMachine()">接入</button>
    <div class="note">接入后: ① 在「采集配置」设该机采样/连接 ② 在「信号映射」登记其通道(probe) ③ 部署边缘网关。新机床即出现在顶栏选择器与总览机群条。</div></div>`;
}
async function addMachine() {
  const id = $("#nm_id").value.trim(), cnc = $("#nm_cnc").value.trim();
  if (!id) return toast("请填机床 SN");
  const r = await fetch("/api/machines", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ machine_id: id, cnc_system: cnc }) }).then(x => x.json());
  if (!r.ok) return toast("失败: " + (r.error || ""));
  toast(r.msg || "已接入");
  await reloadMachines();
  renderEngTab();
}
async function reloadMachines() {
  const r = await api("/api/machines").catch(() => ({ machines: [] }));
  S.machines = r.machines || [];
  if (!S.machines.find(m => m.id === S.machine)) S.machine = S.machines[0] ? S.machines[0].id : null;
  const sel = $("#machineSel");
  sel.innerHTML = S.machines.map(m => `<option value="${esc(m.id)}">${esc(m.id)} · ${esc(m.cnc || "")}</option>`).join("");
  sel.value = S.machine;
  setMachineMeta();
}
async function delMachine(id) {
  if (!confirm(`删除机床 ${id}?\n将连带清空其 信号映射 / 采集配置 / 健康结果 / 遥测 / 波形 全部数据，不可恢复！`)) return;
  if (!confirm(`再次确认：彻底删除 ${id} 及其所有数据？`)) return;
  const r = await fetch(`/api/machines/${encodeURIComponent(id)}`, { method: "DELETE" }).then(x => x.json());
  if (!r.ok) return toast("删除失败: " + (r.error || ""));
  const d = r.deleted || {};
  toast(`已删除 ${id} (信号${d.signal || 0}/遥测${d.telemetry || 0}/健康${d.health_result || 0})`);
  await reloadMachines();
  renderEngMachBar();
  renderEngTab();
}

/* 信号映射在线编辑器 (写 phm_v2.signal; 各台地址各异, 故可逐条/克隆/导入编辑) */
const MAP = { rows: [], editing: null };                 // editing: signal_id | "new" | null
const PROTOS = ["opcua", "nclink", "ni_daq"];
const KINDS = ["vibration", "temperature", "pressure", "current", "speed", "position", "bool"];
const SYS_PAIRS = [["", "(无)"], ["spindle", "主轴 spindle"], ["feed", "进给 feed"], ["hydraulic", "液压 hydraulic"]];
const TEMP_PAIRS = [["", "(无)"], ["coupled", "耦合温(进特征)"], ["confound", "混淆温(回归剔除)"]];

async function engMapping(host) {
  host.innerHTML = "加载中…";
  const r = await api(`/api/machine/${S.machine}/signals`);
  MAP.rows = r.signals || [];
  MAP.editing = null;
  renderMapping(host);
}
function renderMapping(host) {
  const rows = MAP.rows;
  const body = rows.length ? rows.map(mapRowHtml).join("")
    : `<tr><td colspan="8" class="sub">该机床尚无信号映射。点「＋新增信号」逐条登记, 或「从机床克隆」复制一台已配好的信号集再逐条改地址。</td></tr>`;
  host.innerHTML = `<div class="card">
    <div class="map-toolbar">
      <button class="btn" onclick="mapEdit('new')">＋ 新增信号</button>
      <button class="btn ghost" onclick="mapClone()">从机床克隆</button>
      <button class="btn ghost" onclick="mapImport()">导入</button>
      <button class="btn ghost" onclick="mapExport()">导出</button>
      <span class="sub">${S.machine} · ${rows.length} 信号</span>
    </div>
    <div id="mapform"></div>
    <table><thead><tr><th>编码</th><th>名称</th><th>系统</th><th>类型</th><th>协议</th><th>角色</th><th>订阅地址</th><th></th></tr></thead>
      <tbody>${body}</tbody></table>
    <p class="sub" style="margin-top:10px">多协议可扩展: 新机型/新协议只加行不改表。
      <button class="btn ghost" style="padding:3px 10px;margin-left:6px"
        onclick="toast('probe 实测确认地址需 live 采集器, 占位')">probe 实测</button>
      到设备读值确认地址(如成对轴是否共址)，需采集器接入。</p></div>`;
  if (MAP.editing != null) renderMapForm();
}
function mapRowHtml(s) {
  let role = "";
  if (s.high_freq) role += `<span class="tag high">高频</span> `;
  if (s.temp_role === "coupled") role += `<span class="tag coupled">耦合温</span> `;
  if (s.temp_role === "confound") role += `<span class="tag confound">混淆温</span> `;
  if (s.regime) role += `<span class="tag">工况</span>`;
  return `<tr><td>${esc(s.code)}</td><td>${esc(s.name)}</td><td>${esc(s.system || "")}</td>
    <td>${esc(s.kind)}</td><td>${esc(s.protocol)}</td><td>${role}</td>
    <td style="color:var(--muted);font-size:12px;word-break:break-all">${esc(s.addr || "")}</td>
    <td style="white-space:nowrap"><button class="lk" onclick="mapEdit(${s.id})">编辑</button>
      <button class="lk del" onclick="mapDelete(${s.id})">删除</button></td></tr>`;
}
function mapEdit(id) { MAP.editing = id; renderMapForm(); }
function mapCancel() { MAP.editing = null; renderMapping($("#engbody")); }
function mapCurRow() { return MAP.editing === "new" ? {} : (MAP.rows.find(x => x.id === MAP.editing) || {}); }
function mfField(id, label, val, style) {
  return `<label class="cfg-row"><span>${label}</span><input id="${id}" value="${esc(val || "")}" style="${style || ""}"></label>`;
}
function mfSel(id, label, opts, val) {
  return `<label class="cfg-row"><span>${label}</span><select id="${id}">${
    opts.map(o => `<option ${o === val ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`;
}
function mfSelP(id, label, pairs, val) {
  return `<label class="cfg-row"><span>${label}</span><select id="${id}">${
    pairs.map(([v, t]) => `<option value="${esc(v)}" ${v === (val || "") ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
}
function renderMapForm() {
  const box = $("#mapform"); if (!box) return;
  const s = mapCurRow(), isNew = MAP.editing === "new";
  box.innerHTML = `<div class="map-form"><h3>${isNew ? "新增信号" : "编辑 · " + esc(s.code)}</h3>
    <div class="mf-grid">
      ${mfField("mf_code", "编码 code*", s.code)}
      ${mfField("mf_name", "名称", s.name)}
      ${mfField("mf_unit", "单位", s.unit)}
      ${mfSel("mf_proto", "协议", PROTOS, s.protocol || "opcua")}
      ${mfSel("mf_kind", "类型 kind*", KINDS, s.kind || "vibration")}
      ${mfSelP("mf_sys", "所属系统", SYS_PAIRS, s.system)}
      ${mfSelP("mf_temp", "温度角色", TEMP_PAIRS, s.temp_role)}
      <label class="cfg-row"><span>工况键</span><input type="checkbox" id="mf_regime" ${s.regime ? "checked" : ""}></label>
      <label class="cfg-row"><span>高频(振动)</span><input type="checkbox" id="mf_hf" ${s.high_freq ? "checked" : ""}></label>
    </div>
    ${mfField("mf_addr", "订阅地址 (OPC UA NodeId / NC-Link path / NI 通道)", s.addr, "max-width:none")}
    <div style="margin-top:8px"><button class="btn" onclick="mapSave()">${isNew ? "新增" : "保存"}</button>
      <button class="btn ghost" onclick="mapCancel()">取消</button></div></div>`;
}
async function mapSave() {
  const body = {
    code: $("#mf_code").value.trim(), display_name: $("#mf_name").value.trim(),
    unit: $("#mf_unit").value.trim(), protocol: $("#mf_proto").value,
    source_addr: $("#mf_addr").value.trim(), phm_system: $("#mf_sys").value,
    signal_kind: $("#mf_kind").value, temp_role: $("#mf_temp").value,
    regime_role: $("#mf_regime").checked, is_high_freq: $("#mf_hf").checked,
  };
  if (!body.code) return toast("编码 code 必填");
  const isNew = MAP.editing === "new";
  const url = isNew ? `/api/machine/${S.machine}/signals`
                    : `/api/machine/${S.machine}/signals/${MAP.editing}`;
  const r = await fetch(url, { method: isNew ? "POST" : "PUT",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(x => x.json());
  if (!r.ok) return toast("失败: " + (r.error || ""));
  toast(isNew ? "已新增" : "已保存");
  engMapping($("#engbody"));
}
async function mapDelete(id) {
  const s = MAP.rows.find(x => x.id === id);
  if (!confirm(`删除信号 ${s ? s.code : id}?`)) return;
  const r = await fetch(`/api/machine/${S.machine}/signals/${id}`, { method: "DELETE" }).then(x => x.json());
  if (!r.ok) return toast("删除失败: " + (r.error || ""));
  toast("已删除"); engMapping($("#engbody"));
}
async function mapClone() {
  const others = S.machines.filter(m => m.id !== S.machine).map(m => m.id);
  if (!others.length) return toast("无其他机床可克隆");
  const from = prompt("从哪台机床克隆信号集? 输入 SN:\n可选: " + others.join(", "));
  if (!from) return;
  const keep = confirm("保留源机床的订阅地址?\n确定=保留  取消=清空地址(推荐, 逐台再改)");
  const r = await fetch(`/api/machine/${S.machine}/signals/clone`, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from: from.trim(), keep_addr: keep }) }).then(x => x.json());
  if (!r.ok) return toast("克隆失败: " + (r.error || ""));
  toast(`已克隆 ${r.count} 信号`); engMapping($("#engbody"));
}
async function mapExport() {
  const r = await api(`/api/machine/${S.machine}/signals/export`);
  const blob = new Blob([JSON.stringify(r.signals || [], null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `signals_${S.machine}.json`;
  a.click(); URL.revokeObjectURL(a.href);
  toast(`已导出 ${(r.signals || []).length} 信号`);
}
function mapImport() {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = ".json,application/json";
  inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return;
    let arr; try { arr = JSON.parse(await f.text()); } catch (e) { return toast("JSON 解析失败"); }
    if (!Array.isArray(arr)) arr = (arr && Array.isArray(arr.signals)) ? arr.signals : null;
    if (!arr) return toast("内容需为信号数组");
    const replace = confirm(`导入 ${arr.length} 信号到 ${S.machine}\n确定=替换(先清空现有)  取消=合并(upsert)`);
    const r = await fetch(`/api/machine/${S.machine}/signals/import`, { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ signals: arr, mode: replace ? "replace" : "merge" }) }).then(x => x.json());
    if (!r.ok) return toast("导入失败: " + (r.error || ""));
    toast(`已导入 ${r.count} 信号 (${r.mode})`); engMapping($("#engbody"));
  };
  inp.click();
}

async function engAcq(host) {
  host.innerHTML = "加载中…";
  const r = await api(`/api/machine/${S.machine}/acq-config`);
  const c = r.config || {}, aq = c.acquisition || {}, op = c.opcua || {}, nl = c.nclink || {};
  const chs = aq.channels || [];
  const f = (label, id, val, unit = "") => `<label class="cfg-row"><span>${label}</span>
    <input id="${id}" value="${esc(val ?? "")}"><em>${unit}</em></label>`;
  const sel = (label, id, val, opts) => `<label class="cfg-row"><span>${label}</span>
    <select id="${id}">${opts.map(o => `<option ${o === val ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
  const chk = (label, id, on, unit = "") => `<label class="cfg-row"><span>${label}</span>
    <input type="checkbox" id="${id}" ${on ? "checked" : ""}><em>${unit}</em></label>`;
  host.innerHTML = `<div class="card"><h3>NI 高频振动采集</h3>
    ${sel("数据源", "aq_source", aq.source, ["simulated", "nidaq"])}
    ${f("采样率", "aq_rate", aq.rate, "Hz")}
    ${f("每通道点数", "aq_spc", aq.samplesPerChannel, "samples/window")}
    ${f("输入缓冲", "aq_buf", aq.inputBufferSize, "samples")}
    ${f("表名前缀", "aq_table", aq.tableBaseName)}
    ${f("特征窗点数", "aq_win", aq.featureWindowSamples, "0=采样率(1秒)")}
    ${chk("事件触发", "aq_evt", aq.eventEnabled, "越限抓原始波形")}
    ${f("事件 RMS 阈值", "aq_thr", aq.eventRmsThresholdG, "g")}
    <h4 style="margin:14px 0 6px;color:var(--muted)">通道与灵敏度</h4>
    <table id="chtab"><thead><tr><th>物理通道</th><th>灵敏度 (mV/g)</th></tr></thead><tbody>
      ${chs.map((ch, i) => `<tr><td><input class="ch-pc" value="${esc(ch.physicalChannel)}"></td>
        <td><input class="ch-sn" value="${esc(ch.sensitivityMvPerG)}" style="max-width:120px"></td></tr>`).join("")}
    </tbody></table>
  </div>
  <div class="card"><h3>OPC UA 状态量</h3>
    ${chk("启用", "op_en", op.enabled)}
    ${sel("Profile", "op_prof", op.profile, ["kepserver", "machine"])}
    ${f("Endpoint", "op_ep", op.endpoint)}
    ${chk("匿名", "op_anon", op.anonymous)}
    ${f("用户名", "op_user", op.username)}
    ${f("密码", "op_pw", op.password)}
    ${f("轮询间隔", "op_poll", op.pollIntervalMs, "ms")}
  </div>
  <div class="card"><h3>NC-Link (后续台份)</h3>
    ${f("Host", "nl_host", nl.host)} ${f("Port", "nl_port", nl.port)} ${f("SN", "nl_sn", nl.sn)}
  </div>
  <button class="btn" onclick="saveAcq()">保存配置</button>
  <div class="note">结构同步线B app_config (configStore.js)。保存写入 phm_v2.acq_config; 边缘采集器接入后读它启动采集。</div>`;
}
async function saveAcq() {
  const v = (id) => $("#" + id).value.trim();
  const chs = [...document.querySelectorAll("#chtab tbody tr")].map(tr => ({
    physicalChannel: tr.querySelector(".ch-pc").value.trim(),
    sensitivityMvPerG: +tr.querySelector(".ch-sn").value
  })).filter(c => c.physicalChannel);
  const cfg = {
    acquisition: {
      source: v("aq_source"), rate: +v("aq_rate"), samplesPerChannel: +v("aq_spc"),
      inputBufferSize: +v("aq_buf"), tableBaseName: v("aq_table"),
      featureWindowSamples: +v("aq_win"), eventEnabled: $("#aq_evt").checked,
      eventRmsThresholdG: +v("aq_thr"), channels: chs,
    },
    opcua: {
      enabled: $("#op_en").checked, profile: v("op_prof"), endpoint: v("op_ep"),
      anonymous: $("#op_anon").checked, username: v("op_user"), password: v("op_pw"),
      pollIntervalMs: +v("op_poll"),
    },
    nclink: { host: v("nl_host"), port: +v("nl_port"), sn: v("nl_sn") },
  };
  const r = await fetch(`/api/machine/${S.machine}/acq-config`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cfg)
  }).then(x => x.json());
  toast(r.ok ? "配置已保存" : "保存失败: " + (r.error || ""));
}

async function engCtrl(host) {
  host.innerHTML = "加载中…";
  const [s, sg] = await Promise.all([
    api(`/api/machine/${S.machine}/collector-status`),
    api(`/api/machine/${S.machine}/signals`),
  ]);
  const sigs = sg.signals || [], hf = sigs.filter(x => x.high_freq);
  const waveOpts = (hf.length ? hf : sigs)
    .map(x => `<option value="${esc(x.code)}">${esc(x.name || x.code)}${x.high_freq ? " · 高频" : ""}</option>`).join("");
  const badge = (on, alive) => `<span class="conn ${on ? (alive ? "online" : "offline") : "offline"}">${on ? (alive ? "运行中" : "已请求(无心跳)") : "已停止"}</span>`;
  const bothOn = s.opcua.run && s.ni.run, bothOff = !s.opcua.run && !s.ni.run;
  host.innerHTML = `<div class="card"><h3>统一采集控制 · ${esc(S.machine)}</h3>
    <p class="sub">一次性同时启停 OPC UA + NI，避免人工分别启动产生时间差（关系到跨源数据对齐）。</p>
    <div style="display:flex;gap:10px;margin-top:8px">
      <button class="btn" onclick="ctrl('all','start')">▶ 全部启动</button>
      <button class="btn warn" onclick="ctrl('all','stop')">■ 全部停止</button>
      <span class="sub" style="align-self:center">当前: ${bothOn ? "全部运行" : bothOff ? "全部停止" : "部分运行"}</span></div></div>
  <div class="card"><h3>OPC UA 采集 ${badge(s.opcua.run, s.opcua.daemonAlive)}</h3>
    <div style="display:flex;gap:10px;margin-top:8px">
      <button class="btn ghost" onclick="ctrl('opcua','start')">开始</button>
      <button class="btn ghost" onclick="ctrl('opcua','stop')">停止</button></div></div>
  <div class="card"><h3>NI 振动采集 ${badge(s.ni.run, s.ni.daemonAlive)}</h3>
    <p class="sub">行 ${s.ni.rows} · ${s.ni.sps} sps · 心跳 ${s.ni.heartbeat || "—"}</p>
    <div style="display:flex;gap:10px;margin-top:8px">
      <button class="btn ghost" onclick="ctrl('ni','start')">开始</button>
      <button class="btn ghost" onclick="ctrl('ni','stop')">停止</button></div></div>
  <div class="card"><h3>波形查看 / 抓取</h3>
    <label class="cfg-row"><span>通道</span>
      <select id="wave_sig" style="max-width:320px">${waveOpts || "<option value=''>无可选信号 (先在信号映射登记)</option>"}</select></label>
    <div style="display:flex;gap:10px">
      <button class="btn" onclick="waveView()">查看波形</button>
      <button class="btn ghost" onclick="waveCapture()">抓取原始波形</button></div>
    <div id="ctrlwave" style="margin-top:12px"></div>
    <p class="sub" style="margin-top:8px">默认列出该机床高频(振动)通道(按 NI 型号登记)，可自选。查看走真实波形(无块回退 mock)；抓取通知采集器抓所选通道。</p></div>
  <div class="note">${esc(s.note)}</div>`;
}
async function ctrl(target, action) {
  await fetch(`/api/machine/${S.machine}/control`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target, action })
  }).then(x => x.json());
  if (target === "all") toast(action === "start" ? "已请求全部启动" : "已请求全部停止");
  engCtrl($("#engbody"));
}
async function waveView() {
  const sig = $("#wave_sig").value; if (!sig) return toast("无可选通道");
  const box = $("#ctrlwave"); box.innerHTML = `<div class="sub">加载中…</div>`;
  const r = await api(`/api/machine/${S.machine}/waveform?signal=${encodeURIComponent(sig)}`);
  box.innerHTML = `<div class="card" style="background:var(--bg)">
    <h4 style="margin:0 0 6px">${esc(sig)} <span class="badge">${r.rate}Hz${r.mock ? " · mock" : ""}</span></h4>
    ${lineChartRaw(r.samples)}</div>`;
}
async function waveCapture() {
  const sig = $("#wave_sig").value; if (!sig) return toast("无可选通道");
  await fetch(`/api/machine/${S.machine}/control`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target: "ni", action: "capture", signal: sig })
  }).then(x => x.json());
  toast(`已通知采集器抓取波形: ${sig}`);
}

async function engStatus(host) {
  const s = await api(`/api/machine/${S.machine}/collector-status`);
  host.innerHTML = `<div class="card"><h3>边缘 · 同步状态</h3>
    <table><tbody>
      <tr><th>边缘在线</th><td>${s.edge_online ? "在线" : "离线"}</td></tr>
      <tr><th>上次同步</th><td>${s.last_sync || "—"}</td></tr>
      <tr><th>OPC UA 采集器</th><td>${esc(s.opcua.state)}</td></tr>
      <tr><th>NI 采集器</th><td>${esc(s.ni.state)} · 心跳 ${s.ni.heartbeat || "—"}</td></tr>
    </tbody></table>
    <div class="note">${esc(s.note)} store-and-forward: 边缘断网积本地 SQLite, 联网经 /api/sync 补传。</div></div>`;
}

/* ---------- 公共: 系统选择条 ---------- */
async function pickSystem(m, title) {
  const mc = S.machines.find(x => x.id === S.machine) || { systems: [] };
  const sysList = mc.systems || [];
  if (!m.querySelector("#sysbar")) {
    const SYS_CN = { spindle: "主轴", feed: "进给", hydraulic: "液压" };
    m.innerHTML = `<h2 class="page-title">${title}</h2>
      <div id="sysbar" class="tabbar">${sysList.map(s => `<button class="tab" data-sys="${s}">${SYS_CN[s] || s}</button>`).join("")}</div>
      <div id="sysbody">加载中…</div>`;
    m._sys = sysList[0];
    m.querySelectorAll("#sysbar .tab").forEach(b => b.onclick = () => { m._sys = b.dataset.sys; markSys(); render(); });
  }
  m._sys = m._sys || sysList[0] || "spindle";
  markSys();
  return m._sys;
}
function markSys() {
  const m = $("#main");
  m.querySelectorAll("#sysbar .tab").forEach(b => b.classList.toggle("on", b.dataset.sys === m._sys));
}

/* ---------- SVG 折线图 ---------- */
function lineChart(vals, ts) {
  const W = 720, H = 240, padL = 30, padR = 12, padB = 22, padT = 8;
  if (!vals.length) return "";
  const xs = (i) => padL + i * (W - padL - padR) / Math.max(vals.length - 1, 1);
  const ys = (v) => padT + (1 - v) * (H - padT - padB);  // health 0..1
  const pts = vals.map((v, i) => `${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(" ");
  const grid = [0, 0.5, 1].map(g => `<line x1="${padL}" y1="${ys(g)}" x2="${W - padR}" y2="${ys(g)}" stroke="var(--line)"/>
    <text x="2" y="${ys(g) + 4}" fill="var(--muted)" font-size="11">${g.toFixed(1)}</text>`).join("");
  // 健康阈值参考线 (与图例一致: 0.6 关注 / 0.3 告警)
  const ref = [[0.6, "#f4b740"], [0.3, "#e5484d"]].map(([g, c]) =>
    `<line x1="${padL}" y1="${ys(g)}" x2="${W - padR}" y2="${ys(g)}" stroke="${c}" stroke-width="1" stroke-dasharray="4 4" opacity=".7"/>`).join("");
  // x 轴日期标签 (约 5 个)
  let xlab = "";
  if (ts && ts.length) {
    const step = Math.max(1, Math.floor(vals.length / 5));
    for (let i = 0; i < vals.length; i += step)
      xlab += `<text x="${xs(i).toFixed(1)}" y="${H - 6}" text-anchor="middle" fill="var(--muted)" font-size="10">${fmtDate(ts[i])}</text>`;
  }
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">
    ${grid}${ref}${xlab}
    <polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${pts}"/>
    ${vals.map((v, i) => `<circle cx="${xs(i).toFixed(1)}" cy="${ys(v).toFixed(1)}" r="2.5" fill="var(--accent)"/>`).join("")}
  </svg>`;
}

/* 原始波形折线 (y 自适应) */
function lineChartRaw(vals) {
  const W = 700, H = 200, pad = 24;
  if (!vals || !vals.length) return "";
  const lo = Math.min(...vals), hi = Math.max(...vals), rng = (hi - lo) || 1;
  const xs = (i) => pad + i * (W - 2 * pad) / Math.max(vals.length - 1, 1);
  const ys = (v) => H - pad - (v - lo) / rng * (H - 2 * pad);
  const pts = vals.map((v, i) => `${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(" ");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <polyline fill="none" stroke="var(--accent)" stroke-width="1.2" points="${pts}"/></svg>`;
}

init();
