# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

数控机床数据采集与状态监测系统：从机床采集两类数据（高频振动 + 低频状态量）落入 PostgreSQL 并做 Web 可视化。
本仓库定位为更大"健康监测系统"的**数据采集 + 落库模块**，集成边界 = PostgreSQL 库 `vibration_db`。
代码、注释、变量名大量使用中文，命名混用中英文，属正常约定。

仓库含**两套实现**：

- **`WebDashboard/`（当前主线，活跃开发）** —— 已 Web 化的采集落库 + 看板系统。新功能都在这里做。
- **`WindowsFormsApp1/`（已退役，仅作参考/回滚）** —— 原 .NET Framework 4.7.2 WinForms 桌面程序，职责已全部迁到 WebDashboard，见 `WindowsFormsApp1/DEPRECATED.md`。**不要在这里加新功能。**

> 设计原则（已与用户确认）：**能 Web 化的都 Web 化，只保留不可消除的 native 部分（NI 振动采集），且不损失性能。本模块只做采集+落库，不做报警 UI。**

---

## WebDashboard 架构（核心）

```
[硬件主机] collector  (C# net472 守护进程, 唯一 native)
   └─ NI-DAQmx 振动采集 ── 特征/原始块 ──┐
[任意主机] api (Node + Express)          ▼
   ├─ OPC UA 轮询(node-opcua) ─落库──> PostgreSQL (vibration_db)  <── 上层健康系统读取
   ├─ 读 API（看板/趋势/波形）<──────────┘
   └─ 配置 API + 采集开关 API（默认写 phm_v2.acq_config）
[浏览器] web (静态 ECharts SPA)：看板 + 采集配置页 + 采集开关
```

**唯一 native = NI 振动采集回路**（依赖本机 NI-DAQmx 驱动 + 硬件，钉在硬件主机）。其余全部 Web。
两块采集（NI 振动、OPC UA 状态量）**完全独立开关**，互不影响。

### 通道 A — 高频振动（C# 采集器 collector，NI-DAQmx）
- `collector/` 是无界面 **守护进程**（`Program.cs` 主循环）。常驻运行，**监听 DB `collector_control.ni_run` 标志启停采集**，不自己立即采。
- 采集配置（采样率/通道/灵敏度/落盘参数）每次启动从 DB `app_config` 读取（`ConfigStore.cs`）。
- `NiDaqVibrationSource.cs`（`#if NIDAQ`）移植自旧 Form2 的 `start_sampling/OnDataReady`，加速度单位 `AIAccelerationUnits.G`（纵轴 = g）。`SimulatedVibrationSource.cs` 为无硬件验证用。
- 采集→落库**生产者/消费者解耦**（`Acquisition.cs`：源回调入队，处理线程消费），DB 延迟不阻塞采集。
- **落盘策略（C 特征 + D 事件/手动原始 + A 压缩块）**，见下节。
- **NI 读错误（如拔 USB，-88710）→ 守护进程自停并保留错误态**，不僵尸、不无脑重连；用户在网页点「停止」清错误后才能重开。

### 通道 B — 低频状态量（Node OPC UA 轮询）
- `api/src/opcua/poller.js`：替代旧 Form2 的 OPCUA2/3/new_Tick。一次批量读全部去重节点（首节点状态判定整批有效性），按映射拆分入 `_OPCUA_2`/`_OPCUA_3`/`_OPCUA_new` 三表。
- 节点地址两套 profile 在 `api/src/opcua/config.js`：`kepserver`（KEPServer 标签）/ `machine`（机床 Siemens 840D 地址，从旧 `GlobalVariables.cs` 注释掉的真实地址迁来）。运行时按 `app_config.opcua.profile` 切换。
- 类型转换在 `transform.js`（含 DWord→float 重解释 `dword2float`）。
- **解耦后跨通道 `reid` 序号对齐已弃用**（poller 写 `reid=NULL`），振动↔状态量靠时间戳对齐。

### 落盘策略（省盘且不丢关键信息）
旧版"一采样点一行"`_main` 表约 **208 GB/天**，已废弃。现版：
- **C 特征（常态）**：每窗每通道一行统计量（mean/rms/peak/p2p/std/kurtosis/crest）→ `vib_features`。窗默认 = 采样率（1 秒/窗），≈ MB/天。`WindowAggregator.cs` 切窗 + `WindowStats.Compute` 算特征。
- **D 事件 + A 块（按需）**：手动「抓取波形」或事件触发（某通道窗 RMS 越限）时，把原始波形按通道存为 **float32 bytea 块**（PG TOAST 自带压缩）→ `vib_raw_blocks`，关联 `vib_events`。`VibStore.cs` 负责写。
- 落盘参数在 `app_config.acquisition`：`featureWindowSamples`(0=采样率) / `eventEnabled` / `eventRmsThresholdG`，配置页可调。

---

## 关键文件（WebDashboard）

### collector/（C# net472 守护进程）
- `Program.cs`：守护进程主循环——读 `collector_control` 命令、启停 `Acquisition`、回写心跳/状态、故障自停。
- `Acquisition.cs`：一次采集会话（源→队列→处理线程：算特征 + 手动/事件原始块）。
- `CollectorControl.cs`：读写 `collector_control` 表（命令/心跳中介）。
- `VibStore.cs`：写 `vib_features` / `vib_events` / `vib_raw_blocks`。
- `WindowAggregator.cs`：按窗切片 + `WindowStats` 特征计算。
- `ConfigStore.cs`：从 `app_config` 读采集配置（Newtonsoft，属性名大小写不敏感匹配 camelCase）。
- `Config.cs`：`AppSettings`/`DatabaseOptions`/`AcquisitionOptions`/`ChannelOptions`。
- `NiDaqVibrationSource.cs`(`#if NIDAQ`) / `SimulatedVibrationSource.cs` / `IVibrationSource.cs`（含 `Faulted` 事件）。
- `appsettings.json`：DB 连接回退值（DB 无 app_config 时用）；运行时采集参数以 `app_config` 为准。
- `Collector.csproj`：net472，`DefineConstants=NIDAQ`，x64，PackageRef Npgsql/Newtonsoft + HintPath 引用本机 NI 程序集（DAQmx 64 位 + Common）。**用 .NET 8 SDK 的 `dotnet build` 即可编译，无需 Visual Studio。**

### api/（Node + Express + pg + node-opcua）
- `src/server.js`：路由 + 启动（`ensureConfigTable`/`ensureControlTable` + 据配置起 OPC UA poller）。
- `src/db.js`：pg 连接池 + `query()`。
- `src/repository.js`：看板读（spindle/axes/coords + 旧 `_main` 振动表，含 SQL 侧降采样 `row_number()%step`）。
- `src/configStore.js`：默认读写 `phm_v2.acq_config`，legacy fallback 到 `public.app_config`；同时提供 `phm_v2.signal` 读取、OPC UA NodeId 更新与启用集合保存。
- `src/niControl.js`：`collector_control` 读写（NI 开关/抓取/状态，含 `daemonAlive` = 心跳 10s 内）。
- `src/vibStore.js`：读 `vib_features`（RMS 趋势）/ `vib_events` / 解码 `vib_raw_blocks`（float32 bytea → 数组，按需降采样）。
- `src/opcua/`：`poller.js`（轮询落库 + start/stop/restart/getStatus；按 `acq_config.opcua.enabledSignalIds` 过滤已有映射并用 `signal.source_addr` 覆盖 NodeId）、`config.js`（两套 legacy profile）、`schema.js`、`transform.js`。
- `.env`：`PGPASSWORD` / `PORT` / `OPCUA_*` 默认值。`package.json` 有 `overrides.hexy=0.3.5`（修 node-opcua 的 ESM 依赖问题）。

### web/（静态 ECharts SPA，无构建步骤）
- `index.html` + `app.js` + `styles.css`：实时采集看板。顶部两块独立采集控制（OPC UA / NI，徽标+开始/停止+抓取）。
  - **可配置折线图**：图表数量自由增删（「＋ 添加图表」/ 卡片「✕」），每图自选信号——**统一信号目录**（catalog）覆盖振动特征(RMS/峰值/峭度·各通道) + OPC UA(主轴/进给各轴×电流温度速度/坐标)，振动与 OPC UA 一视同仁可选。多源信号用 **time 轴自动对齐**；布局+选择存 `localStorage('acqChartsV1')`，刷新不丢。底部保留「振动波形(原始抓取块)」专用卡(样本序号轴)。
  - **数据导出**(顶栏「⬇ 数据导出」)：三类 CSV(+`#`注释 JSON 元数据)供 ML 验证——原始抓取块 / 特征流 / OPC UA 状态量。读取 `pandas.read_csv(p, comment='#')` 或 `numpy.genfromtxt(p, delimiter=',', skip_header=4)`。
  - 取数按需：每刷新只拉被选信号涉及的接口(一源一次)；图例显隐跨自动刷新保留(`setTimeLine` 回灌 `legend.selected`)。
- `config.html`：采集配置页（替代旧 Form1）——NI 参数 + OPC UA 连接，读写 `/api/config`。
- `signals.html` + `signals.js`：现场 OPC UA 信号维护页。读取 `/api/opcua/catalog`，可编辑 `phm_v2.signal.source_addr`、启用/停用采集信号并保存到 `acq_config.opcua.enabledSignalIds`；中心看板只读这些现场地址。
- ECharts 走 CDN。

### REST API 一览
- 读：`/api/health` `/tables` `/spindle/trend` `/axes/trend` `/coordinates` `/vibration[/range]`（旧 _main） `/vib/sessions` `/vib/features` `/vib/events` `/vib/block`
- 导出（CSV + `#`注释 JSON 元数据，`src/exportStore.js`）：`/api/export/vib/block?event=` `/api/export/vib/features?from=&to=&channels=` `/api/export/opcua?table=opcua2|opcua3|opcuanew&from=&to=&maxPoints=`
- 配置：`GET|PUT /api/config`（PUT 改 OPC UA 配置则热重启 poller）
- OPC UA 信号维护：`GET /api/opcua/catalog`、`GET /api/signals/catalog`、`PUT /api/signals/:id`、`PUT /api/opcua/selection`
- 采集开关：`/api/opcua/start|stop` `/api/opcua/status`；`/api/ni/start|stop|capture` `/api/ni/status`

---

## PostgreSQL 表（集成边界，对上层系统的数据契约）

库 `vibration_db`。表结构中文名↔英文列名↔类型对照见 `WindowsFormsApp1/数据库对照.txt`（改字段先查它）。

- `_OPCUA_2` / `_OPCUA_3` / `_OPCUA_new`：OPC UA 状态量（主轴 / 各轴+油泵布尔 / 坐标）。
- `vib_features`：振动特征（常态落盘，session/channel/time + 7 个统计量）。
- `vib_events` + `vib_raw_blocks`：事件/手动抓取的原始波形块（bytea float32，事件级联）。
- `app_config`（单行 id=1, JSONB `data`）：采集模块共享配置面（acquisition + opcua）。
- `collector_control`（单行 id=1）：NI 采集器命令/状态中介（`ni_run`/`ni_state`/`ni_heartbeat`/`ni_rows`/`ni_sps`/`current_table`/`capture_seq`/`capture_done`）。
- `_tb_field_2026_06_18_14_31_51_main`：一次现场实测的部分振动数据（386MB），用户要求**保留**，勿删。
- 旧 WinForms 的 `_main`/`_bool`/`_other` 持久表结构仍被 `/api/vibration` 读路径兼容。

---

## 构建与运行（WebDashboard）

环境前置（本机已装）：**.NET 8 SDK、Node v20、PostgreSQL 16、NI-DAQmx 26.3 + NI MAX**。
DB：`localhost:5432 / postgres / 库 vibration_db`，**密码 `584412135lwx`**（早期从源码硬编码的 `123456` 重置而来）。
NI 设备：`cDAQ1Mod4`，AI 通道 `cDAQ1Mod4/ai0..ai3`。

现场跑两个进程，**用 `.cmd` 启动器**（双击或在 cmd 输入文件名）：

```cmd
cd WebDashboard
start-server.cmd        :: 后端（看板+OPC UA+API），首次自动 npm install
start-collector.cmd     :: NI 采集守护进程（另开窗口，常驻待命）
```

然后浏览器 `http://localhost:4000`：配置页设 `source=nidaq`+通道+OPC UA → 看板点 NI/OPC UA「开始」→ 「抓取波形」看原始波形。
详见 `WebDashboard/RUNBOOK_现场.md`。复位脚本 `WebDashboard/tools/_field_reset.sql`。

### 编码约定（重要，曾踩坑）
- **`.cmd` 启动器必须纯 ASCII、不加 `chcp`**：cmd 处理含中文的批处理有 UTF-8 解析 bug（`chcp 65001`+UTF-8 会拆错行）。`.cmd` 只 `powershell -File xxx.ps1` 调起同名 `.ps1`，中文都在 `.ps1` 里。
- **`.ps1` 必须 UTF-8 带 BOM**：Windows PowerShell 5.1 读无 BOM 的 UTF-8 中文会乱码。
- C# 采集器 / PowerShell 的中文输出走系统默认代码页（936），普通 cmd 窗口即可正确显示。

---

## 关键约定与注意点

- **配置/控制都在 DB**：采集参数改 `app_config`（配置页 PUT），NI 启停改 `collector_control`（采集开关 API）。采集器与后端不共享内存、可不同主机，全靠这两张表协调。
- **改 OPC UA 节点/字段**需同步改：`api/src/opcua/config.js` 的 profile 映射 + `schema.js` 建表列 + `数据库对照.txt`。
- **连接信息**：后端走 `api/.env`，采集器走 `appsettings.json` + 环境变量 `COLLECTOR_PGPASSWORD`（`.ps1` 默认填 `584412135lwx`）。改库密码改这两处。
- **OPC UA 无服务器时优雅失败**：poller 连接失败不崩后端，`getStatus().lastError` 给出原因，看板徽标显示「已停止」。
- **WinForms 已退役**：`Form0.StopAllProcesses()`（会 Kill 系统所有进程的危险逻辑）已删除；新功能不要回到 WinForms。
- **并发会话警惕**：历史上出现过另一个 Claude 会话在同库/同目录并行建表/写文件（留下半成品 + 孤儿临时文件）。改 DB/文件前先核对当前实际状态，发现不是自己建的东西先查清再动。

---

## WindowsFormsApp1（已退役，仅参考）

原桌面程序：`Program.cs`→`Form0_导航栏`（构造时 new 全部子窗体并互相注入引用），`Form1_系统设置`（配置中心）、`Form2_状态监测`（采集/轮询/落库/绘图/报警全部实现，最大文件）、`Form3/Form4`（纯展示）、`PostgreSQL.cs`（每方法新建连接、字符串拼表名的数据访问层）、`OpcUa.cs`、`GlobalVariables.cs`（节点地址）。

旧约定（迁移时已演化）：`采集表*`=易失缓存 / `储存表*`=持久（`MergeTables`/`SplitTableIntoTwo` 转换后删缓存）；跨表 `reid`/`id` 序号对齐；报警（阈值 + 3σ）——**Web 版按用户要求未实现报警**。`Resources/fault_diagnosis.py`（IronPython 故障判据）当时即未接线。

仅在对照旧逻辑、回滚或迁移残余字段时查阅本目录。
---

## 2026-07-02 PHM 集成口径: `phm_v2.acq_config` 单真相源

当前 WebDashboard 仍是边缘网关内的采集执行/调试工作台, 主项目中心看板是统一入口。集成默认路径已经从旧 `public.app_config` + `collector_control` 切到 `phm_v2.acq_config`:
- 机床选择: 边缘进程用环境变量 `EDGE_MACHINE_ID` 绑定单台机床, 默认 `FIELD_2026_06_18`。
- 配置读取: Node `/api/config` 与 C# `ConfigStore` 默认读写 `phm_v2.acq_config.data`; `public.app_config` 只保留 legacy fallback。
- 控制位: `/api/opcua/start|stop`、`/api/ni/start|stop|capture` 与中心看板 control API 都写同一份 `data.control`。
- OPC UA: Node API 每 1s reconcile `control.opcua_run`、连接配置与 `opcua.enabledSignalIds`, 自动启停/重启 poller；`signals.html` 可维护 NodeId 与启用集合。当前 poller 仍写旧 `_OPCUA_*` 固定表, 仅对已有映射做过滤/地址覆盖；任意新增信号动态入 `telemetry` 属后续。
- NI: C# collector 轮询 `control.ni_run/capture_seq`, 回写 `ni_state`/`ni_message`/`ni_heartbeat`/`ni_rows`/`ni_sps`/`session`/`capture_done` 到同一 JSONB。
- 信号目录: WebDashboard `/api/opcua/catalog` 与 `/api/signals/catalog` 从 `phm_v2.signal` 生成; `signals.html` 是现场地址/probe/启用集合的维护入口, 中心看板只维护 PHM 语义。
- 边缘入口: `phm_v2.acq_config.data.edge.baseUrl` 供中心看板打开该机床采集工作台; 实时曲线/调试页仍留在 WebDashboard。

数据路径仍是阶段 1: C# 振动特征继续写 `public.vib_features`, 主项目 `pg_bridge.py` 增量搬到 `phm_v2.telemetry`; OPC UA 标量直入 telemetry、rpm/regime 分层与 C# 直写 telemetry 属后续阶段。科研阶段未做鉴权/CORS/审计, 服务只应绑定本机或内网, 不得暴露公网。

