# 振动采集系统 × PHM 整合 — 开发计划

> 把 `数控机床数据采集与状态监测系统/`(C#/Node 采集落库) 与 `PHM_claude/`(算法主线) 整合成一套"采集→健康基线"系统。
> 本文是整合工作的权威参考。算法/采集各自的现状见两子目录的 CLAUDE.md 与 `PHM_claude/PROJECT_STATUS_AND_HANDOFF.md`。
> 更新: 2026-07-02 (B1 振动桥落地 / A3 桥路径 / B4 采集子系统导出+可配置采集页 / B5+D9 采集配置单真相源)。状态标记: [✓done] [进行] [待讨论] [待办]。

---

## 0. 已拍板决策 (2026-06-22)

| 议题 | 结论 |
|---|---|
| 两系统关系 | 互补: 线B 采集落库(补振动短板, 自述不做报警), 线A 健康判定+界面 |
| 采集协议 | NC-Link + OPC UA **并存且预留协议接口** (机床不止华中/西门子) |
| 数据契约边界 | PostgreSQL `vibration_db`, 新建 **`phm_v2`** schema (长表+维度表) |
| schema 收口 | **phm_v2 直接作生产**; public 旧空表逐步废弃 |
| 合并范围 | 只取 PHM **最终产品形态** = `phm_pipeline/` 包; step1-9*/各验证 plan/regression_anchor 不并 |
| 界面 | **合并到 Web 端** (响应式, 不做数控原生 HMI 富界面); 建立期方案A。**前端正式架构 = v2 master-detail (2026-06-29 拍板, v1 五页平级废弃)**, 详见 §D |
| 前端基座 | **线 A Flask+WS 演进**(无CDN, 复用线B ECharts组件); 新建中心看板 `server/dashboard.py` |
| 部署形态 | **边缘 store-and-forward + 中心只读富前端**(见 §2b); 首台先一台机子全包, 代码按"引擎/前端可分离"写 |
| 显示面 | 数控HMI简略健康界面(边缘供数,断网免疫) / 综合大屏(领导展示,按需) / 平板·手机(iOS+安卓纯Web)·办公电脑 |
| 数据节奏 | 事件性(交班/热机后才一个样本)非连续; 建立期 x/N 以"月"计 |
| 采集层架构 | **傻采集器(多语言保留)写 telemetry + Python 统一做工况/稳态/评分** (见 §2) |
| 算法核 | 成熟期 PCA+T²+SPE, SPE 不可省; 新增参数化 UCL(可选)压成熟期门槛 (主轴 ~5p, 而非 10p) |

## 1. 数据契约 (phm_v2 schema) [✓done 建表+干跑闭环]

独立 schema, 可 `DROP SCHEMA phm_v2 CASCADE` 回滚。建表脚本 `_integration_probe/phm_v2_schema.sql`。
- `machine`(机床维表: SN/数控系统/current_epoch)
- `signal`(信号定义维表 = channel_map 的库版: protocol/source_addr/phm_system/signal_kind/temp_role/regime_role/**is_high_freq**)
- `telemetry`(标量遥测长表, **按月分区**: machine_id/signal_id/ts/value/**feature**/epoch/regime) — OPC UA/NC-Link 标量(feature=NULL) 与振动窗特征(feature=rms…)统一
- `vib_raw_blocks`(事件/手动原始波形 float32 块, TOAST 压缩)
- `health_result` **[✓done]**: PHM 评分回写表 (建表 `_integration_probe/health_result_schema.sql`)。显示字段(mode/light/message/target_n)由评分侧算好写入, 中心看板**纯读**。UNIQUE(machine_id,phm_system,epoch,regime,ts) 幂等, 对上 `/api/sync` UPSERT TODO。

**已验证**: 159 窗振动特征写入 telemetry → 读回 pivot 还原 → 过 BaselineModel, 健康曲线与直算逐窗差 2.11e-15。契约闭环成立。

## 2. 采集层架构 (骨架已确认)

**两类数据性质不同**: 高频振动(25.6kHz, 必须 C# native, 特征就地算) vs 低频标量(~Hz, 轻量轮询, 无 native 依赖)。

**第1层 · 协议采集器 (瘦, 各管各, 任意语言)** — 只做 采集→映射 signal_id→写 telemetry:
- NI 振动 (C#, 线B 采集器): 就地算窗特征写 telemetry + 事件原始块。
- OPC UA (Node, 线B poller): 写 telemetry 原始读数。
- NC-Link (Python, 线A acquisition/): 写 telemetry。
- **预留协议接口 = 新协议只需"写一个瘦采集器(任意语言) + signal 维表登记几行"**, 不碰已有代码。契约是 telemetry 表, 不是代码接口。

**第2层 · 工况标注 + 健康引擎 (集中 Python/PHM)** — 读 telemetry 做:
① 稳态判定 ② regime 工况标注(**跨源**: 工况来自标量通道, 要按时间戳 join 给振动打标, 故必须上移到统一层) ③ 健康评分 ④ 基线准入(lifecycle 已有)。

## 2b. 部署形态 (边缘 + 中心)

数据是**事件性**的(交班/热机后才一个样本, 非连续), 且要扛断网 → store-and-forward:

- **边缘 (每机床; 首台=采集那台工控机)**: 事件触发采集 → 特征 → **PHM 评分/生命周期** → **本地 SQLite 缓冲**(断网就积这, PHM `store/db.py` 现成) → 驱动**数控 HMI 简略健康界面**(本地可达, 断网免疫) → 联网后 push 未同步样本到中心 `/api/sync`。
- **中心 (内网服务器)**: 汇总各机床 phm_v2 + health_result → **只读**服务富前端(平板/手机/办公)+ 综合大屏 layout。
- **现在就把 PHM 引擎(评分)与前端服务层代码分离**: 近期同一进程, 将来引擎下沉边缘、前端留中心, 零重写。`server/app.py`(NC-Link 控制台)≈边缘侧; `server/dashboard.py`(只读看板)=中心侧。

## 3. 分阶段步骤

### 阶段 A — 数据契约收口
- A1 phm_v2 建表 + 干跑闭环 **[✓done]**
- A2 `signal` 维表填全 (首台 OPC UA, 据 OPCUA地址对照.xlsx) **[✓done]**: 41 信号 (4振动 + 主轴8标量 + 进给18 + 液压11 bool); 脚本 `_integration_probe/a2_seed_signals.py`。三个发现:
  - **成对轴 X1/X2·Y1/Y2·B1/B2 共用同一 OPC UA 地址** (r0027/R0035 同 uN) → 读到相同值, 冗余退化, 进给做基线前必须 probe 实测确认。
  - **液压只有 bool 压力监测, 无连续压力/流量** → 这台做不了 UCI 式液压效率基线, 液压退化为 L1 状态标志位。
  - **主轴信号最全** (振动+轴承温度耦合+电机温度混淆+转速/档位工况+电流) → 首台落地主系统 = 主轴。
- A3 月分区自动建分区 **[部分done 2026-06-30]**: 桥写入路径已做 (`acquisition/pg_bridge._ensure_partitions` 写前按 ts `CREATE ... PARTITION OF ... IF NOT EXISTS`)。NC-Link `TelemetryWriter` 直写路径可复用同逻辑(待)。

### 阶段 B — 采集层接入 (各采集器改写入目标为 telemetry)
- B0 采集层共享件 (2026-06-23) **[✓done desk]**: `acquisition/signal_loader.py`(signal维表→ChannelMapping, 角色映射规则; **真实库 FIELD_2026_06_18 37 OPC UA 信号验证** → condition13/channel14/confounder_temp10) + `acquisition/telemetry_writer.py`(record→telemetry 行格式范本: 标量 feature=NULL/振动 feature=rms.. + 惰性写库) + `acquisition/protocol.py`(`ProtocolClient` 接口/工厂). B1-B3 各瘦采集器据此写 telemetry. 全貌见 `ACQUISITION_CONTRACT.md`.
- B1 NI 振动采集器(C#): 写入目标 旧表→telemetry; 振动窗特征 is_high_freq=TRUE **[✓done via 过渡桥 2026-06-30]**: 未改 C# 采集器(仍写 `public.vib_features`), 改用 Python **过渡桥** `acquisition/pg_bridge.py` 增量搬 `public.vib_features`→`telemetry`(HF 特征流, channel 1..N→signal_id 按 source_addr ai 序号派生, 5 reducer, watermark 幂等于新表 `phm_v2.bridge_state`, 写前自动建当月分区)。真库 round-trip 验收(隔离测试全清理)+ anchor/smoke 全绿。详见 `ACQUISITION_CONTRACT.md §4b`。**终态**: C# 直写 telemetry 后桥退役; public 旧表按 §0 决策逐步废弃。
- B2 OPC UA poller(Node): 写入目标→telemetry (feature=NULL) **[待办]**: 桥 Phase 2 (OPC UA 标量) 同此目标, 阻塞于 PostgresSource 低频窗聚合分支 + rpm 工况分层端到端 (§4 P1)。
- B3 NC-Link 采集(Python): 写 telemetry **[待办]**
- B4 采集子系统增强 (WebDashboard) **[✓done 2026-06-30]**: ① **原始数据导出**(CSV+`#`注释 JSON 元数据, 供 ML 验证): 抓取原始块 `/api/export/vib/block` + 特征流 `/api/export/vib/features` + OPC UA 状态量 `/api/export/opcua`(`src/exportStore.js`); pandas `read_csv(comment='#')`/numpy `genfromtxt(skip_header=4)` 可直接消费(注释行纯 ASCII 防 GBK 编码坑)。② **可配置采集页**: `web/index.html`+`app.js` 改动态图表网格——图表数量自由增删、每图自选信号(统一信号目录覆盖振动特征+OPC UA, time 轴自动对齐多源, 布局存 localStorage)。详见 `数控.../CLAUDE.md` web/ 节。
- B5 **采集配置单真相源 / 边缘工作台接入** **[✓done 2026-07-02]**: 首阶段不改振动落库路径, 先把配置/控制权威源收口到 `phm_v2`。`phm_v2.signal` 作为 WebDashboard 信号目录与采集地址权威; `phm_v2.acq_config` 作为 per-machine 采集参数、边缘网关信息和控制/状态权威。WebDashboard Node API 默认按 `EDGE_MACHINE_ID` (默认 `FIELD_2026_06_18`) 读写 `phm_v2.acq_config.data`, `public.app_config` 仅 legacy fallback; `/api/config`、OPC UA start/stop、NI start/stop/capture 均改写同一 JSONB `control`。Node 增加 1s reconcile, 根据 `control.opcua_run` 与 OPC UA 配置自动启动/停止/重启 poller。C# collector 读取 `data.acquisition` 与 `control.ni_run/capture_seq`, 并把 `ni_state`/`ni_message`/`ni_heartbeat`/`ni_rows`/`ni_sps`/`session`/`capture_done` 回写同一 JSONB。中心看板采集页在 `data.edge.baseUrl` 上提供“打开采集工作台”入口。验证见 `docs/CURRENT_STATE.md` 2026-07-02 条。
- 注: 稳态判定/regime 不在采集器做, 全上移到阶段 C2。采集器写全量, 准入由 PHM 决定。

### 阶段 C — PHM 在线消费 (离线先行)
- C1 新增 `datasource.PostgresSource`: 从 telemetry 拉 CollectionRecord, 按 `is_high_freq` 分流(高频=直接用预算特征, 低频=features.py 现场 reduce) **[✓done]**
  - 产品核向后兼容扩展: `CollectionRecord.precomputed` 字段 + `extract_vector` 命中分支; 新增 `config.spindle_field_v1()`; regression_anchor/smoke_test 复跑 PASS。
  - 低频原始序列窗聚合分支待 OPC UA telemetry 到位后启用。
- C1b 成熟期门槛压缩 (2026-06-23) **[✓done]**: `BaselineModel.ucl_method` 参数化限(T²~F + SPE~Jackson-Mudholkar) + lifecycle 接入(`cfg.ucl_method`); 主轴 config 压缩档(门槛 ~5p, ucl_method=auto, 按 rpm 分层, 特征裁剪 p20→12 砍共线 std/p2p). 液压代理验证(`_integration_probe/time_to_maturity_experiment.py`): 10p(140)→5p(70) 进成熟期 46→23 天, 去抖 FAR 仍 0%、无跳变; 锚点/smoke/selfcheck 全绿. 动机: 解决新机出厂前无长积累时间 (详见两子目录 CLAUDE.md 时间账).
- C1c NC 空跑程序框架 + 协议扩展点 (2026-06-23) **[✓done desk骨架]**: `nc_profile.py`(idle-run profile = regime **单一定义源** -> 派生 C2 regime_bins/baseline_by + 生成空跑 G代码 + 稳态标记; 机型预设 车/铣/镗) + `acquisition/protocol.py`(`ProtocolClient` 接口 + `make_client` 工厂, 正式化协议扩展点; `ChannelEntry` 加 protocol 标签向后兼容). 验证 `_integration_probe/nc_profile_and_protocol_check.py`; e2e_mock_test 仍全过. 稳态门控两层: 程序标记(权威, =settle 后驻留段) + 信号 CV 核验/兜底. **多协议主接缝是 telemetry+signal 维表, 非此 Python 层. 方言 M码/G04驻留单位、rpm容差、信号名归一待现场.**
- C2 工况标注 + 稳态门控 + HealthEngine **[✓done desk骨架]**: 新增 `regime.py`(`SteadyGate` 稳态门控 + `RegimeLabeler` 工况分箱) + `engine.py`(`HealthEngine`: 每 regime 一套 lifecycle + 混淆温残差化"基线集拟合后冻结"). 验证(`_integration_probe/c2_engine_desk_check.py`): 液压单 regime 逐点复现 LifecycleManager(Δhealth=0), 合成双 rpm 档路由 + 斜坡记录门控(不准入) + 残差化冻结重建全跑通; 回归网全绿. **门控阈值/rpm档边界/低频原始序列窗聚合/残差化是否随大修 reset 重拟合 待真实数据标定 (阶段 E)**.
- C3 多机床×多系统调度 (每机床每系统一 epoch) **[✓done 桌面 2026-06-24]**: `score_runner.discover_targets`(机床 signal phm_system ∩ CONFIGS) + `run_all`(epoch=各机床 current_epoch, 单 (机床,系统) 失败隔离) + CLI `--all`。详见 D6。

### 阶段 D — Web 前端 (中心只读富前端)
> **前端正式架构 = v2 (方案B master-detail, `static/dashboard_v2/`) [✓拍板 2026-06-29]**: v1 五页平级 (`static/dashboard/`) 已废弃, `dashboard.py` 根 `/` 重定向 `/v2/`, `/v1/` 仅留参照 (文件不删)。下方 D1–D8 的功能/接口 v2 复用同一套 `/api`, IA 由"五平级页"改 master-detail (机群→机床详情五标签 + 设置建档 + ⌘K)。详见 `docs/modules/center-dashboard.md`。
- D1 基座选型 = 线 A Flask+WS 演进 **[✓done]**; 新建中心看板 `server/dashboard.py`(只读 phm_v2 + mock 健康)。
- D2 **响应式五页骨架** **[✓done 脚手架]**: `server/static/dashboard/`(index.html/styles.css/app.js, 纯原生无CDN)。
  - 四档断点: 手机<600(底部tab) / 平板(窄侧栏) / 桌面 / 大屏>1600(领导展示放大)。
  - 五页: 总览(健康灯+建立期x/N) / 系统诊断(T²·SPE贡献条) / 维护·基线(epoch·reset占位) / 趋势·历史(SVG折线) / 工程设置(signal维表)。
  - 两层: 操作工(默认, 隐藏工程页) / 工程(切换, 现场接 PIN)。
  - 接口: `/api/machines|overview|machine/<id>/{signals,trend,diagnose}`, `/api/status/<id>`(数控HMI投影), `/api/sync`(边缘 store-and-forward 入口, 契约占位)。
  - 已验证: HTTP/API/静态全 200; 读真实 machine/signal, 健康数值 mock。运行 `python -m phm_pipeline.server.dashboard --port 8080`。
- D2b **整合线B 采集配置/控制** **[✓done 脚手架]**: 新建 `phm_v2.acq_config`(per机床 JSONB, 整合线B app_config+collector_control)。
  - 总览加**告警条**(确认占位); 系统诊断加**原始波形查看**(点贡献条→波形, mock); 工程设置改**多 tab**:
    - 信号映射(signal维表 + probe占位) / **采集配置**(NI 采样率·通道·灵敏度·特征窗·事件阈值 + OPC UA endpoint·profile·轮询 + NC-Link host/port/sn, 读写 acq_config) / **采集控制**(OPC UA·NI 开关·抓取波形·心跳状态徽标) / **同步·状态**(边缘在线·store-and-forward)。
  - 接口: `/api/machine/<id>/{acq-config(GET/PUT),control(POST),collector-status,waveform,alarms}`。
  - 采集器真实启停/心跳/probe 已从占位推进到配置单真相源: 中心看板、WebDashboard Node 与 C# collector 共用 `phm_v2.acq_config.data.control`; C# 心跳/NI 状态回写真实字段, Node OPC UA 由 1s reconcile 自动跟随控制位。live 真机 probe、OPC UA 标量入 `telemetry`、边缘离线同步仍在阶段 B/C 后续。
- D2c **视觉提升 + 必备功能 + 同步线B真实默认配置** **[✓done]**:
  - `acq_config` 结构对齐线B `app_config`(configStore.js DEFAULTS): acquisition{source,rate,samplesPerChannel,inputBufferSize,tableBaseName,featureWindowSamples,event*,channels[{physicalChannel,sensitivityMvPerG:98.94}]} + opcua{enabled,profile,endpoint,anonymous,user,pw,pollIntervalMs}。修复 PUT 整行覆盖 bug → 改顶层浅合并(不再冲掉 control)。
  - 视觉: 健康环形仪表 + sparkline + 机群条(多机床快览/大屏) + 告警条(带时间) + 健康图例 + 趋势阈值参考线/日期轴 + toast + 顶栏机床元信息/时钟/刷新 + 自动刷新(总览15s) + 时间格式化。
- D2d **多机床管理 + 柔和刷新** **[✓done]**:
  - 工程设置加「机床管理」tab(列出/新增机床, POST /api/machines); 总览机群条加「＋接入机床」入口。多机床接入 = machine行 + 各自 signal维表 + 各自 acq_config + 各自边缘网关(协议/地址可不同)。
  - 自动刷新改**软更新** updateOverview(set-if-changed): 数据不变则零视觉跳动; 变化时卡片淡入。tab 高亮统一 .tab.on。
- D2待续(已考虑, 缺真实数据/决策): PIN鉴权 / 告警历史+确认持久化 / 趋势时间范围选择 / 导出·维护报告 / 边缘离线数据陈旧横幅 / 维护前后裸指标对比 / 复用线B ECharts 密集图 / ~~信号映射在线编辑~~(✓ 见 D7) / ~~删除机床~~(✓ 见 D8)。
- D3 两层(已具雏形, PIN 待接)
- D4 **评分回写闭环 (Phase 1)** **[✓done, 真实数据端到端验收]**: 建 `health_result` + `score_runner.py`(telemetry→`HealthEngine`→UPSERT health_result, 看板显示字段评分侧算好) + dashboard overview/trend 改读真值(空表回退 mock)。
  - 验收: FIELD_2026_06_18 主轴 159 窗振动特征回放 → 走完 建立期(stage1:30/stage2:30)→成熟期(stage3:99, 真实 PCA+T²+SPE), 末窗 health=0.31/黄灯; `/api/overview`+`/api/.../trend` source=real; regression_anchor/smoke PASS。
  - **数据节奏注**: 这批是一段 2.5min 连续标定数据, runner 按窗序当事件样本回放(day=窗序)驱动生命周期; 分期的运营意义需真实事件节奏(阶段 E)。**且 vibration-only 无 steady 通道→稳态门控未启用→高振瞬态窝进池**, 健康偏低偏噪是忠实反映(印证"真做基线只取稳态窗"), 非 bug。
  - **D5 diagnose 去 mock (Phase 2) [✓done, 真实数据端到端验收 2026-06-24]**: `BaselineModel.explain()`(T²/SPE/UCL + 逐特征精确可加贡献: SPE 贡献=残差平方/T² 贡献=z·Dz) → `LifecycleResult`/`HealthResult` 透传 → `score_runner` 补写 `t2/spe/ucl_t2/ucl_spe/contributions(JSONB)` → dashboard `_real_diagnose`(真实优先) + 诊断页每通道 T²(蓝)/SPE(黄高亮)双条。验收: FIELD 主轴 stage3 99 行五列全落值, `/api/.../diagnose` source=real, SPE top3 点出关系异常驱动通道; explain 自检(Σ贡献==T²/SPE)/anchor/smoke/HTTP 全 PASS。
  - **D6 波形读 vib_raw_blocks + C3 多机床调度 [✓done 桌面 2026-06-24]**: ① dashboard `waveform` 真实优先读 `vib_raw_blocks`(`_decode_f32` 小端 float32 + 贡献名 `<code>_<feature>` 最长前缀解析→signal_id, 空表回退 mock); 验证 解码单元+合成块 DB round-trip(可逆)+回退 全 PASS。② `score_runner.discover_targets`/`run_all` + `--all`(各机床 signal phm_system ∩ CONFIGS, epoch=各机床 current_epoch, 失败隔离); FIELD 发现 hydraulic(0 no-op)/spindle(159·stage3 99), `--all` 幂等写 159。
  - **Phase 2 剩余待办 (非纯桌面)**: 低频窗聚合分支(等 B2 OPC UA telemetry); 真实波形块由阶段B NI 采集器写入后自动转真值。
- D7 **信号映射在线编辑器 [✓done 桌面 2026-06-24]**: 工程页「信号映射」从只读占位 → 在线编辑 `phm_v2.signal`(权威登记, 采集器与算法两侧都读它)。`DataProvider` 加 `upsert/update/delete/export/import/clone_signals` + 路由(`POST /signals`, `PUT|DELETE /signals/<sid>`, `POST /signals/{clone,import}`, `GET /signals/export`); 前端逐条增改删 + 下拉枚举(协议/系统/类型/温度角色) + **从其他机床克隆**(默认清空地址, 解决"同点位每台 OPC UA NodeId 不同") + JSON 导入导出。验证: `__MAPTEST__` 一次性机床全链 PASS(克隆 FIELD 41 信号), HTTP 路由烟测 ok, 测试数据已清。**注: probe 实测确认地址仍占位(需 live 采集器); 此编辑只配登记, 不驱动采集——采样率/连接在 acq_config/采集子系统**。
- D8 **工程页交互增强 5 项 [✓done 桌面 2026-06-24]**: ① 删除机床(`DELETE /api/machines/<id>`+`delete_machine` 事务全清 signal/acq_config/health_result/telemetry/vib_raw_blocks+machine, UI 二次确认); ② 工程设置顶部机床快捷切换条(各 tab 共用 `setEngMachine`); ③ 采集控制在选中机床操作(并入②); ④ 统一启停(`set_control target='all'` 一次写同置 ni_run+opcua_run, 消除人工时间差利于跨源对齐); ⑤ 波形自选(采集控制通道下拉, 默认高频通道=按 NI 型号登记, 查看内联走 waveform 真实优先 / 抓取写 `control.capture_signal`)。验证: `__CTLTEST__`/`__HTTPDEL__` 全链 PASS, `node --check` app.js OK, HTTP 200, 测试机已清。
- D9 **中心采集入口对接边缘工作台** **[✓done 2026-07-02]**: `phm_v2.acq_config.data.edge` 增加 `mode=edge_gateway`/`gatewayId`/`baseUrl`; v2 工程页从采集配置读取边缘地址并跳转 WebDashboard。中心看板只保留机床选择、信号映射、采集配置、核心状态与入口, 不复制 WebDashboard 的实时曲线/调试工作台。
### 阶段 E — 现场标定与上真机
- E1 物理限 L1 / E2 稳态段匹配热机程序 / E3 工况分层粒度标定 / E4 大修 reset 流程 / E5 存量机退化验证(用户确认精度) **[待办]**

## 4. 待讨论/待确认清单
> **优先级活清单 (横向比较已分档) 在 `docs/CURRENT_STATE.md` §当前任务/下一步候选**; 本节只登记条目与依据, 不重复排序。
- 振动 4 通道 ↔ (3 箱体/1 前轴承套) 逐一映射顺序 (现假定 vib1-3=箱体, vib4=前轴承)
- 工况分层最初粒度落地 (主轴 rpm档[热态=协变量,不分层] / 进给 轴×方向×速度档 / 液压单基线 — 已定原则, 待现场标定)
  - **[算法核审查 2026-06-29 · P1 高 → 现 P0] rpm 分层端到端未接通**: spindle `baseline_by=("rpm_bin",)` 但 `regime_bins={}`、`PostgresSource` 写 `condition["regime"]` 而非 `rpm_bin`、`nc_profile.to_c2_regime()` 未被 score_runner 合并 → 实测单 regime `(None,)`。接多档真实数据前必须接通 (合并 nc_profile 派生 或 baseline_by 改读 regime 列), 否则静默单基线污染。同根: 稳态门控 steady_channels=() 亦未接。
- ~~**[P4 中] score_runner 的 `day` = 逐记录计数非日历日**~~ **[✓已修复 2026-06-30]**: 加 `--day-mode calendar(默认)|replay`; calendar 取 rec 日历日成熟门槛生效, replay 复现 FIELD burst。
- **硬化批次遗留待做 (2026-06-30, 多为纯桌面)** — 见 CURRENT_STATE 表分档:
  - **score_runner 增量评分 + 模型持久化** (P1 桌面): 现全量重放/不存模型 → 改增量 + 持久化 BaselineModel(<5KB), 实时评分/边缘下沉前置。落在阶段 C/D4 延伸。
  - **前端详情懒加载** (P1 桌面): boot 预取每台每系统明细 → 改点开机床才拉, 首屏 N×10→1。落在阶段 D。
  - **写接口鉴权 + CORS 收紧** (P0 安全, 桌面): 当前写接口/`DELETE` 无服务端鉴权 (仅前端置灰)。落在 D3 (两层 PIN 待接) 升级为服务端门控。
  - **`/api/sync` 边缘入库** (P2): 桩 → UPSERT telemetry/health_result 幂等; store-and-forward 闭环 (阶段 B/C)。
  - **采集子系统 `数控.../` 残留明文口令** (P3 杂项): 该子系统自带密钥管理, 单独一轮 (非本计划主线)。
- 数控 HMI 简略界面落地形态 (CNC 面板能否跑浏览器/Web视图? 还是定制 HMI 轮询 /api/status)
- 综合大屏多机床总览布局 (现单机床, 待多台份)
- (已定) 前端基座=线A Flask+WS ✓; PG 驱动=psycopg2-binary ✓; 中心看板生产 WSGI=waitress ✓ (2026-06-30)
