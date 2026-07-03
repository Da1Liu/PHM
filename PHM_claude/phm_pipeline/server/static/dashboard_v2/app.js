/* 机床健康基线 · 原型 v2 (静态 UI)
   - 真实占位数据 (硬编码，见 DATA)
   - 不接接口 (无 fetch), 不实现业务逻辑 (健康值/T²/SPE 均为占位常量)
   - 仅做视图渲染与下钻、标签/角色切换等“界面交互”
   方案 B: 机群列表 → 机床详情(概览/诊断/趋势/维护/运行) → 概览→诊断下钻 */
"use strict";

/* ============================== 占位数据 ============================== */
const SYS_CN = { spindle: "主轴", feed: "进给", hydraulic: "液压" };

// 主轴诊断贡献 (告警期 CNC_01): SPE 由 主轴X 振动耦合驱动
const SPINDLE_CONTRIB_ALARM = [
  { name: "ch_sx", label: "主轴X振动", t2: 0.8, spe: 8.9, rate: 25600, seed: 1 },
  { name: "ch_sy", label: "主轴Y振动", t2: 0.4, spe: 5.1, rate: 25600, seed: 2 },
  { name: "T_brgF", label: "前轴承温", t2: 1.6, spe: 2.0, rate: 1, seed: 3 },
  { name: "ch_sz", label: "主轴Z振动", t2: 0.3, spe: 1.4, rate: 25600, seed: 4 },
  { name: "I_sp", label: "主轴电流", t2: 1.1, spe: 0.6, rate: 1, seed: 5 },
  { name: "n_sp", label: "spindle_speed", t2: 0.2, spe: 0.3, rate: 1, seed: 6 },
];
const SPINDLE_CONTRIB_WATCH = [
  { name: "ch_sx", label: "主轴X振动", t2: 0.9, spe: 3.1, rate: 25600, seed: 7 },
  { name: "T_brgF", label: "前轴承温", t2: 1.4, spe: 1.8, rate: 1, seed: 8 },
  { name: "ch_sy", label: "主轴Y振动", t2: 0.5, spe: 1.2, rate: 25600, seed: 9 },
  { name: "I_sp", label: "主轴电流", t2: 0.7, spe: 0.5, rate: 1, seed: 10 },
];
const FEED_CONTRIB_OK = [
  { name: "ax_X1", label: "X1 进给振动", t2: 0.4, spe: 0.6, rate: 25600, seed: 11 },
  { name: "ax_Y1", label: "Y1 进给振动", t2: 0.3, spe: 0.5, rate: 25600, seed: 12 },
  { name: "T_mot", label: "feed_motor_temp", t2: 0.5, spe: 0.4, rate: 1, seed: 13 },
];

// 健康趋势 (0..1, 同 epoch 内可比. 末点对应当前健康度)
const TREND_DECLINE = [0.79, 0.77, 0.74, 0.75, 0.7, 0.66, 0.61, 0.55, 0.48, 0.42, 0.36, 0.3, 0.26, 0.24];
const TREND_WATCH = [0.86, 0.84, 0.81, 0.8, 0.77, 0.74, 0.7, 0.66, 0.62, 0.58, 0.55, 0.52];
const TREND_OK = [0.9, 0.92, 0.89, 0.91, 0.93, 0.9, 0.92, 0.91, 0.9, 0.92];

function days(n) { // 生成 n 个递减的占位时间戳 (秒)
  const now = Math.floor(Date.now() / 1000), out = [];
  for (let i = 0; i < n; i++) out.push(now - (n - 1 - i) * 86400);
  return out;
}

const DATA = {
  lastSync: "12:01",
  machines: [
    {
      id: "CNC_01", cnc: "华中 HNC-848", epoch: 2, light: "red", message: "主轴 SPE 越限", updated: "1分钟前",
      alarm: { text: "spindle SPE exceeded", ts: "12:02", driver: "ch_sx spindle vibration" },
      systems: {
        spindle: { mode: "scored", light: "red", health: 0.24, message: "SPE exceeded", t2: 3.8, spe: 12.4, ucl_t2: 4.7, ucl_spe: 5.0, contrib: SPINDLE_CONTRIB_ALARM },
        feed: { mode: "scored", light: "green", health: 0.88, message: "T²/SPE 正常",
          t2: 2.2, ucl_t2: 8.8, spe: 1.9, ucl_spe: 5.4, contrib: FEED_CONTRIB_OK, trend: TREND_OK },
        hydraulic: { mode: "status_only", light: "l1", message: "液压状态正常" },
      },
    },
    {
      id: "CNC_02", cnc: "siemens 840D", epoch: 1, light: "yellow", message: "主轴 关注", updated: "2分钟前",
      systems: {
        spindle: { mode: "scored", light: "yellow", health: 0.52, message: "略偏离基线, 持续观察",
          t2: 5.6, ucl_t2: 9.0, spe: 4.2, ucl_spe: 5.5, contrib: SPINDLE_CONTRIB_WATCH, trend: TREND_WATCH },
        feed: { mode: "scored", light: "green", health: 0.86, message: "T²/SPE 正常",
          t2: 2.0, ucl_t2: 8.6, spe: 1.7, ucl_spe: 5.2, contrib: FEED_CONTRIB_OK, trend: TREND_OK },
        hydraulic: { mode: "status_only", light: "l1", message: "液压状态正常" },
      },
    },
    {
      id: "CNC_03", cnc: "fanuc 0i-MF", epoch: 1, light: "green", message: "全部正常", updated: "1分钟前",
      systems: {
        spindle: { mode: "scored", light: "green", health: 0.91, message: "T²/SPE 正常",
          t2: 1.8, ucl_t2: 9.1, spe: 1.5, ucl_spe: 5.6, contrib: FEED_CONTRIB_OK, trend: TREND_OK },
        feed: { mode: "scored", light: "green", health: 0.89, message: "T²/SPE 正常",
          t2: 2.1, ucl_t2: 8.7, spe: 1.6, ucl_spe: 5.3, contrib: FEED_CONTRIB_OK, trend: TREND_OK },
        hydraulic: { mode: "status_only", light: "l1", message: "液压状态正常" },
      },
    },
    {
      id: "CNC_04", cnc: "华中 HNC-818", epoch: 1, light: "slate", message: "基线建立中 62%", updated: "5分钟前",
      systems: {
        spindle: { mode: "building", light: "slate", n: 62, N: 100, message: "建立期 · 事件性采集(交班/热机)" },
        feed: { mode: "building", light: "slate", n: 38, N: 100, message: "building" },
        hydraulic: { mode: "status_only", light: "l1", message: "液压状态正常" },
      },
    },
  ],
};
const LIGHT_CN = { green: "正常", yellow: "关注", red: "报警", slate: "建立期", l1: "状态" };
const LIGHT_ICON = { green: "●", yellow: "●", red: "▲", slate: "●", l1: "■" };

/* 设置页占位数据: 信号维表 / 采集配置 / 同步状态 (各机床独立, 协议/地址各异) */
const SIGNALS = {};
(function () {
  const base = [
    { code: "SP_VIB_X", name: "主轴X振动", system: "spindle", kind: "vibration", protocol: "ni_daq", high_freq: true, addr: "Dev1/ai0" },
    { code: "SP_VIB_Y", name: "主轴Y振动", system: "spindle", kind: "vibration", protocol: "ni_daq", high_freq: true, addr: "Dev1/ai1" },
    { code: "SP_VIB_Z", name: "主轴Z振动", system: "spindle", kind: "vibration", protocol: "ni_daq", high_freq: true, addr: "Dev1/ai2" },
    { code: "SP_TMP_BF", name: "前轴承温", system: "spindle", kind: "temperature", protocol: "opcua", temp_role: "coupled", addr: "ns=2;s=Spindle.BrgFrontTemp" },
    { code: "SP_TMP_BR", name: "后轴承温", system: "spindle", kind: "temperature", protocol: "opcua", temp_role: "coupled", addr: "ns=2;s=Spindle.BrgRearTemp" },
    { code: "SP_RPM", name: "spindle_speed", system: "spindle", kind: "speed", protocol: "opcua", regime: true, addr: "ns=2;s=Spindle.Speed" },
    { code: "SP_CUR", name: "主轴电流", system: "spindle", kind: "current", protocol: "opcua", addr: "ns=2;s=Spindle.Current" },
    { code: "FD_VIB_X1", name: "X1进给振动", system: "feed", kind: "vibration", protocol: "ni_daq", high_freq: true, addr: "Dev1/ai3" },
    { code: "FD_TMP_MOT", name: "feed_motor_temp", system: "feed", kind: "temperature", protocol: "opcua", temp_role: "confound", addr: "ns=2;s=Feed.MotorTemp" },
    { code: "FD_POS_X", name: "x_axis_position", system: "feed", kind: "position", protocol: "opcua", regime: true, addr: "ns=2;s=X.Position" },
    { code: "HY_PRS_OK", name: "液压压力正常", system: "hydraulic", kind: "bool", protocol: "opcua", addr: "ns=2;s=Hyd.PressureOK" },
    { code: "HY_OIL_T", name: "油温", system: "hydraulic", kind: "temperature", protocol: "opcua", temp_role: "coupled", addr: "ns=2;s=Hyd.OilTemp" },
  ];
  const wid = (arr) => arr.map((r, i) => ({ id: i + 1, unit: "", temp_role: "", regime: false, high_freq: false, ...r }));
  SIGNALS.CNC_01 = wid(base);
  SIGNALS.CNC_02 = wid(base.map(r => ({ ...r, addr: "" })));  // 克隆后清空地址 (每台 NodeId 不同)
  SIGNALS.CNC_03 = wid(base);
  SIGNALS.CNC_04 = [];  // 新接入, 空映射 (演示空态 + 克隆 CTA)
})();
const ACQ_DEF = {
  ni: { source: "nidaq", rate: 25600, samplesPerChannel: 25600, bufferSize: 102400, tableBase: "vib_raw", featureWin: 0, eventEnabled: true, eventThr: 8,
    channels: [{ pc: "Dev1/ai0", sens: 100 }, { pc: "Dev1/ai1", sens: 100 }, { pc: "Dev1/ai2", sens: 100 }, { pc: "Dev1/ai3", sens: 100 }] },
  opcua: { enabled: true, profile: "kepserver", endpoint: "opc.tcp://192.168.1.10:49320", anonymous: false, username: "phm", password: "******", pollMs: 1000 },
  nclink: { host: "", port: 0, sn: "" },
  edge: { baseUrl: "http://localhost:4000", gatewayId: "FIELD_2026_06_18", mode: "edge_gateway" },
};
const STATUS_DEF = { edge_online: true, last_sync: "2026-06-24 12:01", opcua: "running", ni: "running", heartbeat: "12:03:58",
  note: "store-and-forward placeholder" };
const ACQ = {}, STATUS = {};  // 按机床索引，在线由适配层填入，离线回退 ACQ_DEF/STATUS_DEF

/* ============================== 工具 ============================== */
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/[<>&]/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));
const stateText = (v) => ({ running: "运行", stopped: "停止", idle: "空闲", error: "异常", starting: "启动中", stopping: "停止中" }[String(v || "").toLowerCase()] || (v || "--"));
const highFreqSignals = (mid) => (SIGNALS[mid] || []).filter(s => s.high_freq || s.is_high_freq || s.protocol === "ni_daq" || s.kind === "vibration");
const signalCounts = (mid) => (SIGNALS[mid] || []).reduce((acc, s) => {
  if (s.high_freq || s.is_high_freq) acc.high += 1;
  else if (s.protocol === "ni_daq" || s.kind === "vibration") acc.high += 1;
  else acc.low += 1;
  return acc;
}, { high: 0, low: 0 });
const M = (id) => DATA.machines.find(m => m.id === id);
function edgeUrlFor(mid, path = "") {
  const a = ACQ[mid] || ACQ_DEF;
  const base = (a.edge?.baseUrl || "").replace(/\/$/, "");
  if (!base) return "";
  const url = `${base}${path}`;
  return `${url}${url.includes("?") ? "&" : "?"}machine_id=${encodeURIComponent(mid)}`;
}

const S = { view: "fleet", machine: "CNC_01", tab: "overview", system: "spindle", setTab: "machines" };
const MAPED = { editing: null }; // 信号映射内联编辑态 (UI 占位)

/* 机床运行态 (UI 占位, 非真实采集，仅为演示"按钮随状态变") */
const RUN = {};
function runState(id) { return RUN[id] || (RUN[id] = { opcua: true, ni: true }); }

/* 大屏卡片头条: 取最差受评系统的健康分，全建立中则取建立进度 */
function machineHeadline(m) {
  const scored = Object.values(m.systems).filter(s => s.mode === "scored");
  if (scored.length) { const worst = scored.reduce((a, b) => a.health <= b.health ? a : b);
    return { num: Math.round(worst.health * 100), sub: m.message }; }
  const bld = Object.values(m.systems).find(s => s.mode === "building");
  if (bld) return { num: Math.round(100 * bld.n / bld.N) + "%", sub: "建立期" };
  return { num: "--", sub: m.message };
}

function toast(msg, ms = 2200) {
  let t = $("#toast"); if (!t) { t = document.createElement("div"); t.id = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.className = "show";
  clearTimeout(toast._t); toast._t = setTimeout(() => t.className = "", ms);
}
function fmtDate(sec) { const d = new Date(sec * 1000), p = n => String(n).padStart(2, "0"); return `${p(d.getMonth() + 1)}/${p(d.getDate())}`; }
function chip(light) { return `<span class="chip ${light}">${LIGHT_ICON[light]} ${LIGHT_CN[light]}</span>`; }

/* 写操作按钮, 工程师可用 / 操作工置灰色锁 (点击给上报提示). act = 工程师状态下的动作标识 */
function wbtn(label, cls = "btn--secondary", size = "", act = "") {
  return `<button class="btn ${cls} ${size} gated" data-write="1"${act ? ` data-act="${act}"` : ""}>${esc(label)}<span class="lock">🔒</span></button>`;
}

/* 健康环 */
function healthRing(val, light, size = 116) {
  const r = size / 2 - 9, cx = size / 2, c = 2 * Math.PI * r, off = c * (1 - (val ?? 0));
  const COL = { green: "#26C281", yellow: "#F4B740", red: "#E5484D", slate: "#6B86A3" };
  const col = COL[light] || "#3DA9FC";
  const label = val == null ? "--" : Math.round(val * 100);
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" class="ring">
    <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="#1F2C3A" stroke-width="9"/>
    <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${col}" stroke-width="9" stroke-linecap="round"
      stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 ${cx} ${cx})"/>
    <text x="${cx}" y="${cx - 1}" text-anchor="middle" font-size="${size * 0.3}" font-weight="800" fill="#E6EDF3" class="mono">${label}</text>
    <text x="${cx}" y="${cx + size * 0.17}" text-anchor="middle" font-size="${size * 0.1}" fill="#8AA0B4">健康度</text>
  </svg>`;
}
function sparkline(vals, w = 220, h = 38) {
  if (!vals || vals.length < 2) return "";
  const xs = i => i * w / (vals.length - 1), ys = v => h - 3 - v * (h - 6);
  return `<svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="spark">
    <polyline fill="none" stroke="#3DA9FC" stroke-width="1.5"
      points="${vals.map((v, i) => `${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(" ")}"/></svg>`;
}
/* 健康趋势折线 (0..1 + 阈值参考线) */
function lineChart(vals, ts) {
  const W = 760, H = 240, padL = 30, padR = 12, padB = 22, padT = 8;
  if (!vals || !vals.length) return "";
  const xs = i => padL + i * (W - padL - padR) / Math.max(vals.length - 1, 1);
  const ys = v => padT + (1 - v) * (H - padT - padB);
  const pts = vals.map((v, i) => `${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(" ");
  const grid = [0, 0.5, 1].map(g => `<line x1="${padL}" y1="${ys(g)}" x2="${W - padR}" y2="${ys(g)}" stroke="#2B3A4A"/>
    <text x="2" y="${ys(g) + 4}" fill="#5E7387" font-size="11">${g.toFixed(1)}</text>`).join("");
  const ref = [[0.6, "#F4B740"], [0.3, "#E5484D"]].map(([g, c]) =>
    `<line x1="${padL}" y1="${ys(g)}" x2="${W - padR}" y2="${ys(g)}" stroke="${c}" stroke-width="1" stroke-dasharray="4 4" opacity=".7"/>`).join("");
  let xlab = "";
  if (ts && ts.length) { const step = Math.max(1, Math.floor(vals.length / 5));
    for (let i = 0; i < vals.length; i += step) xlab += `<text x="${xs(i).toFixed(1)}" y="${H - 6}" text-anchor="middle" fill="#5E7387" font-size="10">${fmtDate(ts[i])}</text>`; }
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">${grid}${ref}${xlab}
    <polyline fill="none" stroke="#3DA9FC" stroke-width="2" points="${pts}"/>
    ${vals.map((v, i) => `<circle cx="${xs(i).toFixed(1)}" cy="${ys(v).toFixed(1)}" r="2.5" fill="#3DA9FC"/>`).join("")}</svg>`;
}
/* 原始波形 (确定性合成，仅作占位形状) */
function genWave(seed, n = 260) {
  const out = [];
  for (let i = 0; i < n; i++) { const t = i / n;
    out.push(Math.sin(2 * Math.PI * 5 * t) + 0.5 * Math.sin(2 * Math.PI * 17 * t + seed) + 0.22 * Math.sin(2 * Math.PI * 43 * t + seed)); }
  return out;
}
function lineChartRaw(vals) {
  const W = 720, H = 180, pad = 16;
  const lo = Math.min(...vals), hi = Math.max(...vals), rng = (hi - lo) || 1;
  const xs = i => pad + i * (W - 2 * pad) / (vals.length - 1);
  const ys = v => H - pad - (v - lo) / rng * (H - 2 * pad);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:180px">
    <polyline fill="none" stroke="#3DA9FC" stroke-width="1.2" points="${vals.map((v, i) => `${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(" ")}"/></svg>`;
}

/* ============================== 路由 ============================== */
function render() {
  document.body.dataset.view = S.view;
  // 机床选择器仅在机床详情有意义; 机群/大屏隐藏 (消除"看全机群却显示某台被选中"的歧义)
  const sel = $("#machineSel"); if (sel) sel.style.display = S.view === "machine" ? "" : "none";
  const app = $("#app");
  app.className = S.view === "wall" ? "app wall" : "app";
  if (S.view === "wall") return renderWall(app);
  if (S.view === "settings") return renderSettings(app);
  if (S.view === "machine") return renderMachine(app);
  renderFleet(app);
}

/* ---------- 机群列表 ---------- */
function renderFleet(app) {
  const ms = DATA.machines;
  const cnt = { green: 0, yellow: 0, red: 0, slate: 0 };
  ms.forEach(m => cnt[m.light] != null && cnt[m.light]++);
  const order = { red: 0, yellow: 1, slate: 2, green: 3 };
  const sorted = [...ms].sort((a, b) => order[a.light] - order[b.light]);
  const rowSys = (m) => Object.keys(m.systems).map(k => {
    const s = m.systems[k];
    return `<span class="sysmini"><span class="dot ${s.light}" style="width:9px;height:9px"></span>${SYS_CN[k]}</span>`;
  }).join("");
  const reasonCell = (m) => {
    if (m.light === "green") return `<span class="tiny">--</span>`;
    const col = { red: "var(--red)", yellow: "var(--yellow)", slate: "var(--slate)" }[m.light];
    const ts = m.alarm ? ` <span class="tiny mono">${esc(m.alarm.ts)}</span>` : "";
    return `<span style="color:${col};font-size:13px">${esc(m.message)}</span>${ts}`;
  };
  app.innerHTML = `
    <div class="toolbar">
      <h1 class="page-title">机群 · ${ms.length} 台</h1>
      <div class="spacer"></div>
      <span class="sub">最后同步 <b class="mono">${DATA.lastSync}</b></span>
      <button class="btn btn--ghost btn--sm" id="setBtn">⚙ 设置</button>
      <button class="btn btn--ghost btn--sm" id="wallBtn">大屏模式 →</button>
    </div>
    <div class="summary">
      <div class="tile red lead"><div class="n mono">${cnt.red}</div><div class="k">${chip("red")}</div></div>
      <div class="tile yellow"><div class="n mono">${cnt.yellow}</div><div class="k">${chip("yellow")}</div></div>
      <div class="tile slate"><div class="n mono">${cnt.slate}</div><div class="k">${chip("slate")}</div></div>
      <div class="tile green"><div class="n mono">${cnt.green}</div><div class="k">${chip("green")}</div></div>
    </div>
    <table class="fleet-table">
      <thead><tr><th>状态</th><th>机床</th><th>说明</th><th>数控系统</th><th>各系统</th><th>epoch</th><th>更新</th></tr></thead>
      <tbody>${sorted.map(m => `
        <tr class="${m.light === "red" ? "alarm" : ""}" data-go="${esc(m.id)}">
          <td>${chip(m.light)}</td>
          <td><b>${esc(m.id)}</b> <span class="tiny">→</span></td>
          <td>${reasonCell(m)}</td>
          <td class="muted">${esc(m.cnc)}</td>
          <td>${rowSys(m)}</td>
          <td class="mono">${m.epoch}</td>
          <td class="tiny">${esc(m.updated)}</td>
        </tr>`).join("")}</tbody>
    </table>
    <p class="sub" style="margin-top:12px">每台独立 signal 维表 + acq_config + epoch · 告警机自动置顶 · 点行进入详情。</p>`;
  $("#wallBtn").onclick = () => { S.view = "wall"; render(); };
  $("#setBtn").onclick = () => { S.view = "settings"; S.setTab = "machines"; render(); };
  app.querySelectorAll("tr[data-go]").forEach(tr => tr.onclick = () => openMachine(tr.dataset.go));
}

function openMachine(id, tab, system) {
  S.machine = id; S.view = "machine";
  S.tab = tab || "overview";
  const m = M(id);
  S.system = system || Object.keys(m.systems)[0];
  $("#machineSel").value = id;
  render();
}

/* ---------- 机床详情 (标签墙) ---------- */
const TABS = [["overview", "概览"], ["diagnose", "诊断"], ["trend", "趋势"], ["maintenance", "维护"], ["run", "运行"]];
function renderMachine(app) {
  const m = M(S.machine);
  app.innerHTML = `
    <div class="crumb"><a data-home>机群</a><span class="sep">/</span><span class="cur">${esc(m.id)}</span></div>
    <div class="mhead">
      <h1>${esc(m.id)}</h1><span class="meta">${esc(m.cnc)} · epoch ${m.epoch}</span>
      ${chip(m.light)}<div class="spacer"></div>
      <button class="btn btn--ghost btn--sm" data-cfg>⚙ 该机配置</button>
    </div>
    <div class="tabs">${TABS.map(([k, v]) => `<button class="tab ${k === S.tab ? "on" : ""}" data-tab="${k}">${v}${
      k === "diagnose" && m.light === "red" ? `<span class="pill">${chip("red")}</span>` : ""}</button>`).join("")}</div>
    <div id="tabbody"></div>`;
  app.querySelector("[data-home]").onclick = () => { S.view = "fleet"; render(); };
  app.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { S.tab = b.dataset.tab; render(); });
  const cfgB = app.querySelector("[data-cfg]"); if (cfgB) cfgB.onclick = () => { S.view = "settings"; S.setTab = "mapping"; render(); };
  ({ overview: tabOverview, diagnose: tabDiagnose, trend: tabTrend, maintenance: tabMaintenance, run: tabRun }[S.tab])(M(S.machine), $("#tabbody"));
}

/* ---------- 概览 (下钻起点) ---------- */
function tabOverview(m, host) {
  let alarm = "";
  if (m.alarm) alarm = `<div class="alarm-bar"><b>${LIGHT_ICON.red} ${esc(m.alarm.text)}</b>
    <span class="tiny mono">${esc(m.alarm.ts)}</span><span class="sub">驱动: ${esc(m.alarm.driver)}</span>
    <div class="spacer"></div><button class="btn btn--secondary btn--sm" data-ack>确认</button>
    <button class="btn btn--primary btn--sm" data-dig="spindle">查看诊断 →</button></div>`;
  else alarm = `<div class="alarm-bar ok"><b>✓ 无活动告警</b></div>`;

  const cards = Object.keys(m.systems).map(k => {
    const s = m.systems[k], light = s.light;
    let visual, body, clickable = s.mode === "scored";
    if (s.mode === "building") {
      const pct = Math.round(100 * s.n / s.N);
      visual = healthRing(s.n / s.N, "slate", 104);
      body = `<div class="health-msg">${esc(s.message)}</div>
        <div class="progress"><i style="width:${pct}%"></i></div>
        <div class="tiny">进度 ${pct}% · 建立期约以月计</div>`;
    } else if (s.mode === "status_only") {
      visual = `<div class="status-medal">✓</div>`;
      body = `<div class="health-msg">${esc(s.message)}</div><span class="badge">仅 L1 · 无连续量基线</span>`;
    } else {
      visual = healthRing(s.health, light, 104);
      body = `<div class="health-msg">${esc(s.message)}</div>
        ${sparkline(s.trend)}<div class="go">查看诊断 →</div>`;
    }
    return `<div class="card status ${light} ${clickable ? "click" : ""}" ${clickable ? `data-dig="${k}"` : ""}>
      <div class="sys-head"><h3>${SYS_CN[k]}</h3>${chip(light)}</div>
      <div class="sys-body"><div class="sys-visual">${visual}</div><div class="sys-info">${body}</div></div>
    </div>`;
  }).join("");

  host.innerHTML = alarm + `<div class="grid">${cards}</div>`;
  host.querySelectorAll("[data-dig]").forEach(el => el.onclick = () => openMachine(m.id, "diagnose", el.dataset.dig));
  const ack = host.querySelector("[data-ack]"); if (ack) ack.onclick = () => toast("告警已确认");
}

/* ---------- 诊断 (下钻目标: T²/SPE 贡献 → 波形) ---------- */
function tabDiagnose(m, host) {
  const sysList = Object.keys(m.systems).filter(k => m.systems[k].mode !== "status_only");
  if (!sysList.includes(S.system)) S.system = sysList[0] || "spindle";
  const seg = `<div class="seg">${sysList.map(k =>
    `<button class="${k === S.system ? "on" : ""}" data-sys="${k}">${SYS_CN[k]}</button>`).join("")}</div>`;
  const s = m.systems[S.system];

  if (s.mode === "building") {
    host.innerHTML = topbar(seg) + `<div class="card"><p class="sub">基线建立中，暂不评分, 无贡献分解。</p></div>`;
    bindSeg(host, m); return;
  }
  const ct = s.contrib || [];
  const pos = v => Math.max(0, +v || 0);
  // 锚定绝对标尺: 取 (统计量, UCL) 较大者留 15% 余量 → 正常系统条天然短, UCL 线落右侧;
  // 越限通道(贡献>UCL)会越过虚线, 直接指向驱动通道.
  const scaleT2 = Math.max(s.t2, s.ucl_t2) * 1.15, scaleSPE = Math.max(s.spe, s.ucl_spe) * 1.15;
  const uclT2 = 100 * s.ucl_t2 / scaleT2, uclSPE = 100 * s.ucl_spe / scaleSPE;
  const w = (v, sc) => Math.min(100, 100 * pos(v) / sc);
  const t2over = s.t2 > s.ucl_t2, speover = s.spe > s.ucl_spe;
  host.innerHTML = topbar(seg) + `
    <div class="card">
      <div class="kpis">
        <span class="kpi ${speover ? "over" : ""}">SPE <b class="mono">${s.spe}</b><small>UCL ${s.ucl_spe}</small></span>
        <span class="kpi ${t2over ? "over" : ""}">T² <b class="mono">${s.t2}</b><small>UCL ${s.ucl_t2}</small></span>
        ${chip(s.light)}
      </div>
      <p class="sub" style="margin:0 0 var(--s4)">关系型异常看 <b style="color:var(--viz-spe)">SPE</b> — 各通道边际正常但耦合变了; 越过 |UCL 才算越限。点行看该通道原始波形。</p>
      ${ct.map((c, i) => `<div class="diag-row" data-wave="${i}">
        <span class="nm" title="${esc(c.label)}">${esc(c.label)}</span>
        <div class="bars">
          <div class="diag-line spe"><span class="lbl">SPE</span><div class="bar spe"><i style="width:${w(c.spe, scaleSPE)}%"></i><u style="left:${uclSPE.toFixed(1)}%"></u></div></div>
          <div class="diag-line"><span class="lbl">T²</span><div class="bar"><i style="width:${w(c.t2, scaleT2)}%"></i><u style="left:${uclT2.toFixed(1)}%"></u></div></div>
        </div><span class="go">展开 →</span></div>`).join("")}
      <div class="legend"><span><i style="background:var(--viz-spe)"></i>SPE 贡献 (重点)</span>
        <span><i style="background:var(--viz-t2)"></i>T² 贡献</span>
        <span><i style="width:3px;background:repeating-linear-gradient(var(--text-1) 0 3px,transparent 3px 6px)"></i>UCL 控制限</span></div>
    </div>
    <div id="wavebox"></div>`;
  bindSeg(host, m);
  host.querySelectorAll("[data-wave]").forEach(r => r.onclick = () => {
    host.querySelectorAll(".diag-row").forEach(x => x.classList.remove("sel"));
    r.classList.add("sel");
    showDiagWave(ct[+r.dataset.wave], m.id);
  });
  // 默认展开 SPE 最大的通道, 直观指向关系型异常驱动  if (ct.length) host.querySelector('[data-wave="0"]').click();
}
/* 诊断通道波形: 在线读 /waveform (vib_raw_blocks, 无块后端回退 mock), 离线合成占位 */
async function showDiagWave(c, mid) {
  const box = $("#wavebox"); if (!box) return;
  if (NET.online) {
    box.innerHTML = `<div class="card inset"><div class="sub">加载波形…</div></div>`;
    const r = await getJSON(`/api/machine/${mid}/waveform?signal=${encodeURIComponent(c.name)}`);
    box.innerHTML = `<div class="card inset"><div class="row between">
      <h3 style="font-size:14px">原始波形 · ${esc(c.label)} <span class="badge">${r.rate || "?"}Hz${r.mock ? " · mock" : ""}</span></h3>
      <span class="tag">${r.mock ? "后端占位" : "vib_raw_blocks"}</span></div>${lineChartRaw(r.samples || [])}</div>`;
  } else {
    box.innerHTML = `<div class="card inset"><div class="row between">
      <h3 style="font-size:14px">原始波形 · ${esc(c.label)} <span class="badge">25600Hz · 高频</span></h3>
      <span class="tag">占位合成波形</span></div>${lineChartRaw(genWave(c.seed))}</div>`;
  }
}
function topbar(seg) {
  return `<div class="row wrap" style="margin-bottom:var(--s4)"><span class="sub">系统</span>${seg}</div>`;
}
function bindSeg(host, m) {
  host.querySelectorAll("[data-sys]").forEach(b => b.onclick = () => { S.system = b.dataset.sys; render(); });
  const rt = host.querySelector("[data-tab]"); if (rt) rt.onclick = () => { S.tab = rt.dataset.tab; render(); };
}

/* ---------- 趋势 ---------- */
function tabTrend(m, host) {
  const sysList = Object.keys(m.systems).filter(k => m.systems[k].mode === "scored");
  if (!sysList.includes(S.system)) S.system = sysList[0] || "spindle";
  const seg = `<div class="seg">${sysList.map(k => `<button class="${k === S.system ? "on" : ""}" data-sys="${k}">${SYS_CN[k]}</button>`).join("")}</div>`;
  const s = m.systems[S.system], pts = s.trend || [], ts = s.trendTs || days(pts.length);
  host.innerHTML = topbar(seg) + `<div class="card">
    <h3>健康度趋势 · 近 ${pts.length} 个采集点</h3>
    <p class="sub">事件性数据, 每交班/热机一点, 仅同一 epoch 内可比 (虚线: 0.6 关注 / 0.3 告警)。</p>
    ${lineChart(pts, ts)}</div>`;
  bindSeg(host, m);
}

/* ---------- 维护 · 基线 ---------- */
function tabMaintenance(m, host) {
  host.innerHTML = `<div class="card">
    <h3>基线 · epoch ${m.epoch}</h3>
    <p class="sub">大修/拆装后 reset 基线 (跨 epoch 不可比)。维护好坏看绝对裸指标台阶 + 维护后稳定性，不看综合分。</p>
    <div class="row" style="margin-top:14px">
      ${wbtn("标注维护事件", "btn--secondary", "", "annotate")}
      ${wbtn("Reset baseline", "btn--danger-quiet", "", "reset")}
    </div>
    <div id="resetConfirm"></div>
    <div class="note">reset 为不可逆操作 (跨 reset 不可比), 工程师权限 + 二次确认 + 留痕。当前为静态占位，不写库。</div>
  </div>`;
  host.querySelectorAll("[data-act]").forEach(b => b.onclick = () => {
    if (document.body.dataset.role === "operator") return; // 操作工由全局门控拦截
    if (b.dataset.act === "annotate") return toast("maintenance event recorded");
    // 破坏性动作，默认 quiet, 仅在显示确认步骤才出现实心红
    $("#resetConfirm").innerHTML = `<div class="note" style="border-left:3px solid var(--red);margin-top:12px">
      <b>确认 reset?</b> 将 epoch ${m.epoch} → ${m.epoch + 1}, 跨 reset 历史不可比，不可撤销。
      <div class="row" style="margin-top:10px">
        <button class="btn btn--danger btn--sm" id="rcYes">确认 reset (epoch+1)</button>
        <button class="btn btn--ghost btn--sm" id="rcNo">取消</button></div></div>`;
  });
  host.addEventListener("click", e => {
    if (e.target.id === "rcYes") { toast("baseline reset"); $("#resetConfirm").innerHTML = ""; }
    else if (e.target.id === "rcNo") $("#resetConfirm").innerHTML = "";
  });
}

/* ---------- 运行 · 采集控制 (从设置“搬出的日常操作”) ---------- */
function tabRun(m, host) {
  const r = runState(m.id);
  const a = ACQ[m.id] || ACQ_DEF;
  const s = STATUS[m.id] || STATUS_DEF;
  const counts = signalCounts(m.id);
  const edgeUrl = edgeUrlFor(m.id);
  const edgeLink = edgeUrl
    ? `<a class="btn btn--primary" href="${esc(edgeUrl)}" target="_blank" rel="noreferrer">打开采集工作台</a>`
    : `<button class="btn btn--secondary" disabled>未配置采集工作台</button>`;
  const pill = (label, on, value) => `<span class="pill ${on ? "on" : ""}">${label} · ${esc(value)}</span>`;
  host.innerHTML = `<div class="card">
    <h3>采集运行状态 · ${esc(m.id)}</h3>
    <div class="statline">
      ${pill("OPC UA", r.opcua, r.opcua ? "运行" : "停止")}
      ${pill("NI 振动", r.ni, r.ni ? "运行" : "停止")}
      <span class="pill ${s.edge_online ? "on" : ""}">边缘 · ${s.edge_online ? "在线" : "离线"}</span>
    </div>
    <table class="tbl"><tbody>
      <tr><th style="width:160px">OPC UA 状态</th><td>${esc(stateText(s.opcua))}</td></tr>
      <tr><th>NI 状态</th><td>${esc(stateText(s.ni))}</td></tr>
      <tr><th>NI 心跳</th><td class="mono">${esc(s.heartbeat || "--")}</td></tr>
      <tr><th>最近同步</th><td class="mono">${esc(s.last_sync || "--")}</td></tr>
      <tr><th>信号登记</th><td>高频/振动 ${counts.high} 路 · 低频状态量 ${counts.low} 路</td></tr>
    </tbody></table>
    <div class="row" style="margin-top:var(--s4)">${edgeLink}<button class="btn btn--secondary" id="runSignals">查看信号映射</button></div>
    <div class="note">中心看板只显示采集运行状态。启停、实时曲线、波形抓取和导出请在边缘 WebDashboard 中完成。</div>
  </div>`;
  const goSignals = $("#runSignals", host); if (goSignals) goSignals.onclick = () => { S.view = "settings"; S.setTab = "mapping"; render(); };
}
/* ---------- 大屏诊治 (独立 surface) ---------- */
function renderWall(app) {
  const ms = DATA.machines;
  const cnt = { green: 0, yellow: 0, red: 0, slate: 0 };
  ms.forEach(m => cnt[m.light]++);
  const order = { red: 0, yellow: 1, slate: 2, green: 3 };
  const sorted = [...ms].sort((a, b) => order[a.light] - order[b.light]);
  const now = new Date(), p = n => String(n).padStart(2, "0");
  app.className = "app wall";
  app.innerHTML = `
    <div class="toolbar"><h1 class="page-title">大屏 · 全厂诊治</h1>
      <button class="btn btn--ghost btn--sm" id="exitWall">← 退出大屏</button></div>
    <div class="wall-sum">
      <div class="tile red"><div class="n mono">${cnt.red}</div><div class="k">${chip("red")}</div></div>
      <div class="tile yellow"><div class="n mono">${cnt.yellow}</div><div class="k">${chip("yellow")}</div></div>
      <div class="tile slate"><div class="n mono">${cnt.slate}</div><div class="k">${chip("slate")}</div></div>
      <div class="tile green"><div class="n mono">${cnt.green}</div><div class="k">${chip("green")}</div></div>
    </div>
    <div class="wall-grid">${sorted.map(m => { const h = machineHeadline(m);
      const c = m.light === "l1" || m.light === "slate" ? "slate" : m.light;
      return `<div class="wall-card ${m.light} ${m.light === "red" ? "span2" : ""}">
        <div class="row between"><b style="font-size:18px">${esc(m.id)}</b>${chip(m.light)}</div>
        <div class="muted" style="margin:6px 0">${esc(m.cnc)}</div>
        <div class="n mono" style="color:var(--${c})">${h.num}</div>
        <div class="sub">${esc(h.sub)}</div>
      </div>`; }).join("")}</div>`;
  $("#exitWall").onclick = () => { app.className = "app"; S.view = "fleet"; render(); };
}

/* ---------- 设置 · 建档 (机床目录 / 信号映射 / 数据巡检 / 边缘接入 / 同步状态) ---------- */
const SET_TABS = [["machines", "机床目录"], ["mapping", "信号映射"], ["live", "数据巡检"], ["acq", "边缘接入"], ["status", "同步状态"]];
function gatedBlocked() { // 行内 read 控件触发写时的兜底 (data-write 按钮已由全局门控拦截)
  if (document.body.dataset.role === "operator") { toast("需要工程权限"); return true; }
  return false;
}
function renderSettings(app) {
  const tab = S.setTab || "machines", perMachine = tab !== "machines";
  app.innerHTML = `
    <div class="crumb"><a data-home>机群</a><span class="sep">/</span><span class="cur">设置</span></div>
    <div class="row between wrap" style="margin-bottom:var(--s3)">
      <h1 class="page-title">设置 · 建档</h1><span class="chip slate">机床接入由边缘同步</span></div>
    <div class="tabs">${SET_TABS.map(([k, v]) => `<button class="tab ${k === tab ? "on" : ""}" data-set="${k}">${v}</button>`).join("")}</div>
    ${perMachine ? `<div class="row wrap" style="margin-bottom:var(--s4)"><span class="sub">机床</span>
      <div class="seg">${DATA.machines.map(m => `<button class="${m.id === S.machine ? "on" : ""}" data-setm="${esc(m.id)}">${esc(m.id)}</button>`).join("")}</div></div>` : ""}
    <div id="setbody"></div>`;
  app.querySelector("[data-home]").onclick = () => { S.view = "fleet"; render(); };
  app.querySelectorAll("[data-set]").forEach(b => b.onclick = () => { S.setTab = b.dataset.set; MAPED.editing = null; render(); });
  app.querySelectorAll("[data-setm]").forEach(b => b.onclick = () => { S.machine = b.dataset.setm; MAPED.editing = null; render(); });
  ({ machines: setMachines, mapping: setMapping, live: setLive, acq: setAcq, status: setStatus }[tab])($("#setbody"));
}

function setMachines(host) {
  host.innerHTML = `<div class="card">
    <table class="tbl"><thead><tr><th>机床 SN</th><th>数控系统</th><th>epoch</th><th>系统</th><th>边缘网关</th><th></th></tr></thead>
    <tbody>${DATA.machines.map(m => { const a = ACQ[m.id] || ACQ_DEF; return `<tr>
      <td><b>${esc(m.id)}</b></td><td class="muted">${esc(m.cnc)}</td><td class="mono">${m.epoch}</td>
      <td>${Object.keys(m.systems).map(k => `<span class="tag">${SYS_CN[k]}</span>`).join(" ")}</td>
      <td class="mono tiny">${esc(a.edge?.gatewayId || "--")}</td>
      <td style="white-space:nowrap;text-align:right"><button class="lk" data-view2="${esc(m.id)}">查看</button></td></tr>`; }).join("")}</tbody></table>
    <p class="sub" style="margin-top:8px">共 ${DATA.machines.length} 台 · 中心机床目录来自边缘同步；新机床接入、基础信息和采集配置在边缘工作台完成。</p>
  </div>`;
  host.querySelectorAll("[data-view2]").forEach(b => b.onclick = () => openMachine(b.dataset.view2));
}
function setMapping(host) {
  const rows = SIGNALS[S.machine] || [];
  const a = ACQ[S.machine] || ACQ_DEF;
  const edgeUrl = edgeUrlFor(S.machine, "/signals.html");
  const edgeLink = edgeUrl
    ? `<a class="btn btn--secondary btn--sm" href="${esc(edgeUrl)}" target="_blank" rel="noreferrer">打开边缘工作台</a>`
    : `<button class="btn btn--secondary btn--sm" disabled>未配置边缘工作台</button>`;
  const body = rows.length ? rows.map(mapRow).join("")
    : `<tr><td colspan="7" class="sub">该机床尚无信号映射。请先在边缘工作台完成信号登记与采集点维护，再由中心同步查看。</td></tr>`;
  host.innerHTML = `<div class="card">
    <div class="map-toolbar"><span class="sub">${esc(S.machine)} · ${rows.length} 信号</span>${edgeLink}</div>
    <table class="tbl"><thead><tr><th>编码</th><th>名称</th><th>系统</th><th>类型</th><th>协议</th><th>角色</th><th>采集地址</th></tr></thead>
      <tbody>${body}</tbody></table>
    <p class="sub" style="margin-top:10px">中心只展示信号映射总览；新增、删除、克隆、导入导出、OPC UA 节点地址和启用状态统一在边缘采集工作台维护。</p></div>`;
}
function mapRow(s) {
  let role = "";
  if (s.high_freq) role += `<span class="tag high">高频</span> `;
  if (s.temp_role === "coupled") role += `<span class="tag coupled">耦合温</span> `;
  if (s.temp_role === "confound") role += `<span class="tag confound">混淆温</span> `;
  if (s.regime) role += `<span class="tag">工况</span>`;
  return `<tr><td class="mono">${esc(s.code)}</td><td>${esc(s.name)}</td><td>${SYS_CN[s.system] || ""}</td>
    <td>${esc(s.kind)}</td><td>${esc(s.protocol)}</td><td>${role || '<span class="tiny">--</span>'}</td>
    <td class="tiny mono" style="word-break:break-all">${esc(s.addr || "")}</td></tr>`;
}
function fmtTs(t) { if (!t) return "--"; return new Date(t * 1000).toLocaleString("zh-CN", { hour12: false }); }
function fmtNum(v) { if (v == null || Number.isNaN(Number(v))) return "--"; const n = Number(v); return Math.abs(n) >= 100 ? n.toFixed(1) : n.toFixed(3); }
function freshness(v) {
  if (!v || v.ts == null) return '<span class="tag">无数据</span>';
  const sec = v.fresh_sec;
  if (sec != null && sec <= 10) return '<span class="tag high">新鲜</span>';
  if (sec != null && sec <= 120) return '<span class="tag">延迟</span>';
  return '<span class="tag confound">过期</span>';
}
function liveRow(v) {
  const label = v.feature ? `${esc(v.code)} · ${esc(v.feature)}` : esc(v.code);
  return `<tr><td class="mono">${label}</td><td>${esc(v.name || "")}</td><td>${SYS_CN[v.system] || esc(v.system || "")}</td>
    <td>${esc(v.kind || "")}</td><td>${esc(v.protocol || "")}</td><td class="mono">${fmtNum(v.value)} ${esc(v.unit || "")}</td>
    <td>${freshness(v)}</td><td class="mono tiny">${fmtTs(v.ts)}</td></tr>`;
}
function setLive(host) {
  host.innerHTML = `<div class="card"><div class="row between wrap"><h3>数据巡检</h3><button class="btn btn--secondary btn--sm" id="liveReload">刷新</button></div>
    <div id="liveBody"><p class="sub">正在读取中心 telemetry 最新值...</p></div></div>`;
  const load = async () => {
    const box = $("#liveBody", host);
    if (!NET.online) {
      const rows = (SIGNALS[S.machine] || []).map((s, i) => ({ ...s, value: i + 1, ts: Math.floor(Date.now() / 1000) - i * 5, fresh_sec: i * 5 }));
      box.innerHTML = `<table class="tbl"><thead><tr><th>信号</th><th>名称</th><th>系统</th><th>类型</th><th>协议</th><th>最新值</th><th>状态</th><th>最近采样</th></tr></thead><tbody>${rows.map(liveRow).join("")}</tbody></table>`;
      return;
    }
    const r = await getJSON(`/api/machine/${S.machine}/latest-values`);
    const vals = r.values || [];
    box.innerHTML = vals.length ? `<table class="tbl"><thead><tr><th>信号</th><th>名称</th><th>系统</th><th>类型</th><th>协议</th><th>最新值</th><th>状态</th><th>最近采样</th></tr></thead><tbody>${vals.map(liveRow).join("")}</tbody></table>`
      : `<p class="sub">中心 telemetry 暂无最新值。此页只做数据到达与新鲜度巡检；现场实时曲线和采集调试请打开边缘工作台。</p>`;
  };
  $("#liveReload", host).onclick = load;
  load().catch(e => { $("#liveBody", host).innerHTML = `<p class="sub">读取失败: ${esc(e.message || e)}</p>`; });
}
function setAcq(host) {
  const a = ACQ[S.machine] || ACQ_DEF;
  const s = STATUS[S.machine] || STATUS_DEF;
  const counts = signalCounts(S.machine);
  const hf = highFreqSignals(S.machine);
  const edgeUrl = edgeUrlFor(S.machine);
  const configUrl = edgeUrlFor(S.machine, "/config.html");
  const signalsUrl = edgeUrlFor(S.machine, "/signals.html");
  const edgeLink = edgeUrl
    ? `<a class="btn btn--primary" href="${esc(edgeUrl)}" target="_blank" rel="noreferrer">打开采集工作台</a>`
    : `<button class="btn btn--secondary" disabled>未配置采集工作台</button>`;
  const channelRows = hf.length ? hf.slice(0, 8).map(x => `<tr><td class="mono">${esc(x.code)}</td><td>${esc(x.name || "")}</td><td>${esc(x.protocol || "")}</td><td class="mono">${esc(x.addr || "")}</td></tr>`).join("")
    : `<tr><td colspan="4" class="sub">该机床尚未同步高频振动信号。请在边缘工作台完成信号登记与采集配置。</td></tr>`;
  host.innerHTML = `<div class="card">
    <h3>边缘接入</h3>
    <div class="statline">
      <span class="pill ${s.edge_online ? "on" : ""}">边缘 · ${s.edge_online ? "在线" : "离线"}</span>
      <span class="pill ${s.opcua === "running" ? "on" : ""}">OPC UA · ${esc(stateText(s.opcua))}</span>
      <span class="pill ${s.ni === "running" ? "on" : ""}">NI · ${esc(stateText(s.ni))}</span>
    </div>
    <table class="tbl"><tbody>
      <tr><th style="width:160px">网关编号</th><td class="mono">${esc(a.edge?.gatewayId || "--")}</td></tr>
      <tr><th>工作台地址</th><td class="mono">${esc((a.edge?.baseUrl || "") || "--")}</td></tr>
      <tr><th>最近同步</th><td class="mono">${esc(s.last_sync || "--")}</td></tr>
      <tr><th>心跳</th><td class="mono">${esc(s.heartbeat || "--")}</td></tr>
    </tbody></table>
    <div class="row" style="margin-top:var(--s4)">${edgeLink}${configUrl ? `<a class="btn btn--secondary" href="${esc(configUrl)}" target="_blank" rel="noreferrer">采集配置</a>` : ""}${signalsUrl ? `<a class="btn btn--ghost" href="${esc(signalsUrl)}" target="_blank" rel="noreferrer">信号维护</a>` : ""}</div>
    <div class="note">机床身份、边缘绑定和采集配置由边缘工作台维护并同步到中心；中心只展示入口、状态与摘要。</div>
  </div>
  <div class="card">
    <h3>采集信号摘要</h3>
    <div class="statline"><span class="pill on">高频/振动 ${counts.high}</span><span class="pill">低频状态量 ${counts.low}</span></div>
    <table class="tbl"><thead><tr><th>编码</th><th>名称</th><th>协议</th><th>地址</th></tr></thead><tbody>${channelRows}</tbody></table>
    <div class="row" style="margin-top:var(--s4)"><button class="btn btn--secondary" id="goSignals">查看信号映射</button><button class="btn btn--ghost" id="goRun">查看运行状态</button></div>
  </div>
  <div class="card">
    <h3>采集参数摘要</h3>
    <table class="tbl"><tbody>
      <tr><th style="width:160px">采集源</th><td>${esc(a.ni.source || "--")}</td></tr>
      <tr><th>采样率</th><td class="mono">${esc(a.ni.rate || "--")} Hz</td></tr>
      <tr><th>每通道样本</th><td class="mono">${esc(a.ni.samplesPerChannel || "--")}</td></tr>
      <tr><th>输入缓冲</th><td class="mono">${esc(a.ni.bufferSize || "--")}</td></tr>
      <tr><th>特征窗</th><td class="mono">${esc(a.ni.featureWin || "按采样率")}</td></tr>
      <tr><th>OPC UA 地址</th><td class="mono">${esc(a.opcua.endpoint || "--")}</td></tr>
      <tr><th>OPC UA Profile</th><td class="mono">${esc(a.opcua.profile || "--")}</td></tr>
      <tr><th>OPC UA 轮询周期</th><td class="mono">${esc(a.opcua.pollMs || "--")} ms</td></tr>
    </tbody></table>
    <div class="note">复杂采样参数以边缘采集工作台为准；中心不直接编辑现场采集配置。</div>
  </div>`;
  const goSignals = $("#goSignals", host); if (goSignals) goSignals.onclick = () => { S.setTab = "mapping"; render(); };
  const goRun = $("#goRun", host); if (goRun) goRun.onclick = () => { S.view = "machine"; S.tab = "run"; render(); };
}
function setStatus(host) {
  const s = STATUS[S.machine] || STATUS_DEF;
  host.innerHTML = `<div class="card"><h3>边缘 · 同步状态<span class="badge">只读</span></h3>
    <table class="tbl"><tbody>
      <tr><th style="width:160px">边缘在线</th><td>${s.edge_online ? '<span class="chip green">● 在线</span>' : '<span class="chip red">■ 离线</span>'}</td></tr>
      <tr><th>上次同步</th><td class="mono">${esc(s.last_sync)}</td></tr>
      <tr><th>OPC UA 采集器</th><td>${esc(stateText(s.opcua))}</td></tr>
      <tr><th>NI 采集器</th><td>${esc(stateText(s.ni))} · 心跳 <span class="mono">${esc(s.heartbeat)}</span></td></tr>
    </tbody></table>
    <div class="note">${esc(s.note)}</div></div>`;
}

/* ============================== 全局交互 ============================== */
// 顶栏
function initTopbar() {
  const sel = $("#machineSel");
  sel.innerHTML = DATA.machines.map(m => `<option value="${m.id}">${m.id} · ${m.cnc}</option>`).join("");
  sel.value = S.machine;
  sel.onchange = () => openMachine(sel.value);
  $("#brand").onclick = () => { S.view = "fleet"; $("#app").className = "app"; render(); };
  $("#roleBtn").onclick = () => {
    const op = document.body.dataset.role === "operator";
    document.body.dataset.role = op ? "engineer" : "operator";
    $("#roleBtn").textContent = op ? "角色: 工程" : "角色: 操作";
    toast(op ? "工程模式" : "操作模式");
    render(); // 让运行 维护页按钮态随角色刷新
  };
  // 时钟 (纯展示)
  const tick = () => { const d = new Date(), p = n => String(n).padStart(2, "0");
    $("#clock").textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; };
  tick(); setInterval(tick, 1000);
  // 写操作门控, 操作工点击 → 上报提示 (占位)
  document.addEventListener("click", e => {
    const w = e.target.closest && e.target.closest('[data-write]');
    if (w && document.body.dataset.role === "operator") {
      e.preventDefault(); e.stopPropagation();
      toast("需要工程权限");
    }
  }, true);
  initPalette();
}
// 命令面板 ⌘K
function initPalette() {
  const pal = $("#palette"), inp = $("#palInput");
  let items = [];
  const buildItems = () => [   // 每次打开重建, 以反映在线加载后的真实机床列表
    ...DATA.machines.map(m => ({ t: "机床", label: `${m.id} · ${m.cnc}`, run: () => openMachine(m.id) })),
    { t: "页面", label: "机群列表", run: () => { S.view = "fleet"; render(); } },
    { t: "页面", label: "大屏诊治", run: () => { S.view = "wall"; render(); } },
    ...TABS.map(([k, v]) => ({ t: "当前机床标签", label: v, run: () => { S.view = "machine"; S.tab = k; render(); } })),
    ...SET_TABS.map(([k, v]) => ({ t: "设置", label: v, run: () => { S.view = "settings"; S.setTab = k; render(); } })),
  ];
  const draw = (q = "") => {
    const f = items.filter(i => (i.t + i.label).toLowerCase().includes(q.toLowerCase()));
    let html = "", grp = "";
    f.forEach((i, idx) => { if (i.t !== grp) { grp = i.t; html += `<div class="glabel">${grp}</div>`; }
      html += `<div class="item" data-i="${items.indexOf(i)}">${esc(i.label)}<span class="k">↵</span></div>`; });
    $("#palList").innerHTML = html || `<div class="item muted">无匹配</div>`;
    $("#palList").querySelectorAll("[data-i]").forEach(el => el.onclick = () => { closePal(); items[+el.dataset.i].run(); });
  };
  const openPal = () => { items = buildItems(); pal.hidden = false; inp.value = ""; draw(); inp.focus(); };
  const closePal = () => { pal.hidden = true; };
  $("#kbd").onclick = openPal;
  inp.oninput = () => draw(inp.value);
  document.addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); pal.hidden ? openPal() : closePal(); }
    if (e.key === "Escape") closePal();
  });
  pal.onclick = e => { if (e.target === pal) closePal(); };
}

/* ============================== 真实接口适配层 ============================== */
/* 在线时从现有 /api/... 拉数据，填入与静态占位相同的结构(DATA/SIGNALS/ACQ/STATUS/RUN),
   渲染层不变。取不到(file:// 直开 或 后端不可达) 则保留静态占位，顶栏标“离线·静态占位”。 */
const NET = { online: false, degraded: false, demo: false };
const getJSON = (u) => fetch(u).then(r => r.ok ? r.json() : Promise.reject(r.status)).catch(() => ({}));
const postJSON = (u, b, method = "POST") => fetch(u, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }).then(r => r.json()).catch(() => ({ ok: false }));
function fmtClock(sec) { if (!sec) return ""; const d = new Date(sec * 1000), p = n => String(n).padStart(2, "0"); return `${p(d.getHours())}:${p(d.getMinutes())}`; }

function sysFromOverview(it) {
  const mode = it.mode === "scoring" ? "scored" : it.mode;  // building / status_only / scored
  let light = it.light;
  if (mode === "building") light = "slate";
  if (mode === "status_only") light = "l1";
  const o = { mode, light, message: it.message, health: it.health };
  if (it.t2 != null) o.t2 = it.t2;
  if (it.spe != null) o.spe = it.spe;
  if (mode === "building") { o.n = it.n; o.N = it.N; }
  return o;
}
function applyWorst(m) {
  const order = { red: 3, yellow: 2, slate: 1, l1: 0, green: 0 };
  let worst = null;
  Object.values(m.systems).forEach(s => { if (worst === null || (order[s.light] || 0) > (order[worst.light] || 0)) worst = s; });
  m.light = worst ? worst.light : "green";
  m.message = worst ? worst.message : "no_data";
}
function acqFromApi(cfg) {
  const aq = cfg.acquisition || {}, op = cfg.opcua || {}, nl = cfg.nclink || {}, edge = cfg.edge || {};
  return {
    ni: { source: aq.source, rate: aq.rate, samplesPerChannel: aq.samplesPerChannel, bufferSize: aq.inputBufferSize,
      tableBase: aq.tableBaseName, featureWin: aq.featureWindowSamples, eventEnabled: aq.eventEnabled, eventThr: aq.eventRmsThresholdG,
      channels: (aq.channels || []).map(c => ({ pc: c.physicalChannel, sens: c.sensitivityMvPerG })) },
    opcua: { enabled: op.enabled, profile: op.profile, endpoint: op.endpoint, anonymous: op.anonymous,
      username: op.username, password: op.password, pollMs: op.pollIntervalMs },
    nclink: { host: nl.host, port: nl.port, sn: nl.sn },
    edge: { baseUrl: edge.baseUrl || "", gatewayId: edge.gatewayId || "", mode: edge.mode || "edge_gateway" },
  };
}
function statusFromApi(cs) {
  return { edge_online: !!cs.edge_online, last_sync: cs.last_sync || "--",
    opcua: (cs.opcua && cs.opcua.state) || "--", ni: (cs.ni && cs.ni.state) || "--",
    heartbeat: (cs.ni && cs.ni.heartbeat) || "--", note: cs.note || "" };
}
async function loadAll(machines, overviewItems) {
  DATA.machines = machines.map(m => ({ id: m.id, cnc: m.cnc || "", epoch: m.epoch || 1, light: "green", message: "", systems: {}, alarm: null }));
  const byId = {}; DATA.machines.forEach(m => byId[m.id] = m);
  // overview 用 /api/fleet 随随机群统一带回 (省一次往返); 未提供则单独取 (reloadSignals 等场景)
  const items = overviewItems || (await getJSON("/api/overview")).items || [];
  items.forEach(it => { const m = byId[it.machine]; if (m) m.systems[it.system] = sysFromOverview(it); });
  DATA.machines.forEach(applyWorst);
  await Promise.all(DATA.machines.map(async m => {
    const [sg, ac, cs, al] = await Promise.all([
      getJSON(`/api/machine/${m.id}/signals`), getJSON(`/api/machine/${m.id}/acq-config`),
      getJSON(`/api/machine/${m.id}/collector-status`), getJSON(`/api/machine/${m.id}/alarms`),
    ]);
    SIGNALS[m.id] = sg.signals || [];
    ACQ[m.id] = acqFromApi(ac.config || {});
    STATUS[m.id] = statusFromApi(cs);
    RUN[m.id] = { opcua: !!(cs.opcua && cs.opcua.run), ni: !!(cs.ni && cs.ni.run) };
    const a = (al.alarms || [])[0];
    if (a) m.alarm = { text: a.message, ts: fmtClock(a.ts), driver: SYS_CN[a.system] || a.system || "", system: a.system || "spindle" };
    await Promise.all(Object.keys(m.systems).map(async k => {
      const s = m.systems[k];
      if (s.mode === "scored" || s.mode === "building") {
        const tr = await getJSON(`/api/machine/${m.id}/trend?system=${k}`);
        s.trend = (tr.points || []).map(p => p.health);
        s.trendTs = (tr.points || []).map(p => p.t);
      }
      if (s.mode === "scored") {
        const dg = await getJSON(`/api/machine/${m.id}/diagnose?system=${k}`);
        s.contrib = (dg.contributions || []).map((c, i) => ({ name: c.name, label: c.name, t2: c.t2, spe: c.spe, seed: i + 1 }));
        if (dg.t2 != null) s.t2 = dg.t2;
        if (dg.spe != null) s.spe = dg.spe;
        if (dg.ucl_t2 != null) s.ucl_t2 = dg.ucl_t2;
        if (dg.ucl_spe != null) s.ucl_spe = dg.ucl_spe;
      }
    }));
  }));
}
async function reloadAll() { const j = await getJSON("/api/fleet"); if (j.machines) await loadAll(j.machines, j.items); buildMachineSel(); }
async function reloadSignals(id) { const sg = await getJSON(`/api/machine/${id}/signals`); SIGNALS[id] = sg.signals || []; }
function buildMachineSel() {
  const sel = $("#machineSel"); if (!sel) return;
  sel.innerHTML = DATA.machines.map(m => `<option value="${esc(m.id)}">${esc(m.id)} · ${esc(m.cnc || "")}</option>`).join("");
  if (DATA.machines.find(m => m.id === S.machine)) sel.value = S.machine;
}
/* 顶栏连接性 (四态: online 真实 / demo 演示(--no-db) / degraded DB不可达 / offline 静态·file://) */
function setConnLabel(state) {
  const c = $("#conn");
  const dot = (cl) => `<span class="dot ${cl}" style="width:8px;height:8px"></span>`;
  const M = {
    online: ["online", dot("green") + "online"],
    demo: ["demo", dot("slate") + "demo"],
    degraded: ["degraded", dot("red") + "degraded"],
    offline: ["offline", dot("slate") + "offline"],
  };
  const [cls, html] = M[state] || M.offline;
  if (c) { c.className = "conn " + cls; c.innerHTML = html; }
  setSysBar(state);
}
/* 系统级横幅，降级/演示态明示，防止把占位、陈旧数据当真实健康判定 */
function setSysBar(state) {
  const bar = $("#sysbar"); if (!bar) return;
  if (state === "degraded") {
    bar.hidden = false; bar.className = "sysbar degraded";
    bar.textContent = "Database unavailable. Check center DB connection and refresh.";
  } else if (state === "demo") {
    bar.hidden = false; bar.className = "sysbar demo";
    bar.textContent = "Demo data; no database connection.";
  } else {
    bar.hidden = true; bar.className = "sysbar"; bar.textContent = "";
  }
}
async function boot() {
  let resp = null;
  try { resp = await fetch("/api/fleet"); } catch (e) { resp = null; }  // file:// 或服务不可达
  if (resp && resp.status === 503) {                 // 服务在线但 DB 故障: 降级, 不渲染编造绿灯
    NET.online = true; NET.degraded = true; DATA.machines = [];
    setConnLabel("degraded"); buildMachineSel(); render(); return;
  }
  let j = null;
  if (resp && resp.ok) j = await resp.json().catch(() => null);
  if (j && j.ok && Array.isArray(j.machines)) {
    NET.online = true; NET.demo = !!j.demo;
    await loadAll(j.machines, j.items);
    if (!DATA.machines.find(m => m.id === S.machine)) S.machine = (DATA.machines[0] || {}).id;
    setConnLabel(j.demo ? "demo" : "online");
  } else {
    NET.online = false;                              // 保留静态占位 (file:// 直开演示)
    setConnLabel("offline");
  }
  buildMachineSel();
  render();
}

/* ============================== 启动 ============================== */
initTopbar();
boot();





