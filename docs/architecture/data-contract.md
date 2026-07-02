# 数据契约 (phm_v2 schema)

> 采集系统 × 算法核的契约边界 = PostgreSQL `vibration_db` 的 **`phm_v2`** schema。
> **本文是可读性参考; 精确 DDL 以建表脚本为准** (`_integration_probe/phm_v2_schema.sql` + `health_result_schema.sql` + `phm_v2_acq_config.sql` + `bridge_state_schema.sql`)。
> 设计原则: **新机型/新协议只加数据行, 不改表结构**。可 `DROP SCHEMA phm_v2 CASCADE` 整体回滚。更新: 2026-07-02。

## 表一览

| 表 | 角色 | 关键点 |
|---|---|---|
| `machine` | 机床维表 | `machine_id`(SN, PK) / `cnc_system` / `model` / `current_epoch`(大修reset +1) |
| `signal` | **信号定义维表** (= channel_map 的库版) | 每台机床各自定义, 不假设统一通道集 → [[ADR-005]] |
| `telemetry` | **标量遥测长表** (按月分区) | OPC UA/NC-Link 标量 + 振动窗特征统一 |
| `vib_raw_blocks` | 事件/手动原始波形 float32 块 | BYTEA, PG TOAST 压缩 |
| `health_result` | **PHM 评分回写** (中心看板纯读) | UNIQUE 幂等 → `docs/modules/score-runner.md` |
| `acq_config` | per-machine 采集配置 (JSONB) | 结构对齐线B `app_config` → `docs/modules/center-dashboard.md` |
| `bridge_state` | 采集落库桥的增量 watermark | per (machine_id, source) 记 last_ts → `phm_pipeline/acquisition/pg_bridge.py` |

## 采集落库桥 (public → phm_v2)
现场采集器 (WebDashboard, C#/Node) 实时写 **`public`** schema 旧表 (`vib_features` / `_OPCUA_*`); 算法核读 **`phm_v2`**。两者**同库 (`vibration_db`) 不同 schema, 靠桥搬运**。
- **Phase 1 (振动, 已落地)**: `phm_pipeline/acquisition/pg_bridge.py` 把 `public.vib_features` 增量搬进 `phm_v2.telemetry` (HF 特征流, channel 1..N→signal_id 按 `source_addr` ai 序号派生, 5 reducer rms/std/kurtosis/crest/p2p, epoch=current_epoch, regime=NULL)。watermark 存 `bridge_state`, 写入+watermark 同事务幂等; 写前按 ts **自动建当月分区** (补 A3)。运行 `python -m phm_pipeline.acquisition.pg_bridge --machine <id>` 后照常 `score_runner`。
- **Phase 2 (OPC UA 标量, 缓)**: 阻塞于 `PostgresSource` 低频窗聚合分支 + rpm 工况分层端到端 (CURRENT_STATE P1)。
- **终态**: 瘦采集器直写 telemetry (ADR-005), 桥退役。

## signal (维表) — 承载 PHM channel_map 语义
关键列: `machine_id` / `code`(机内唯一短码) / `protocol`(nclink\|opcua\|ni_daq) / `source_addr`(NC-Link path@index \| OPC UA NodeId \| NI 通道, 原样留存) / `phm_system`(feed\|spindle\|hydraulic) / `signal_kind`(vibration\|current\|speed\|position\|temperature\|pressure\|bool) / `temp_role`(**confound** 回归剔除 \| **coupled** 进向量 \| NULL → [[ADR-002]]) / `regime_role`(bool, 参与工况分层 → [[ADR-003]]) / `is_high_freq`(bool, TRUE=走波形+特征, FALSE=标量遥测)。UNIQUE(machine_id, code)。

**角色→采集映射** 由 `acquisition/signal_loader.py` 自动派生 (详见 `ACQUISITION_CONTRACT.md §3`)。首台 41 信号 (4 振动 ni_daq + 37 OPC UA 标量)。

## acq_config (per-machine JSONB) — 采集参数/控制/边缘入口权威
`phm_v2.acq_config` 是采集参数与运行控制的单真相源, 与 `signal` 分工如下: `signal` 管“采什么/地址是什么/属于哪个 PHM 角色”, `acq_config` 管“怎么采/是否运行/边缘工作台在哪里”。首阶段 WebDashboard Node API 与 C# collector 已默认读写此表; `public.app_config` 只保留 legacy fallback。

当前 `data` 顶层约定:
- `edge`: `mode=edge_gateway`, `gatewayId`, `baseUrl`。中心看板用 `baseUrl` 打开该机床 WebDashboard 采集工作台。
- `acquisition`: NI source/rate/samplesPerChannel/inputBufferSize/tableBaseName/featureWindowSamples/event* 与 channels[]。
- `opcua`: endpoint/profile/anonymous/user/pw/pollIntervalMs/enabled。
- `nclink`: NC-Link 连接参数预留。
- `control`: `ni_run`, `opcua_run`, `capture_seq`, `capture_signal` 以及采集器回写的 `ni_state`, `ni_message`, `ni_heartbeat`, `ni_rows`, `ni_sps`, `session`, `capture_done`。

控制语义: 中心看板、WebDashboard 本地按钮和采集器只通过同一 JSONB 协调。Node 每 1s reconcile `control.opcua_run` 与 OPC UA 配置自动启停/重启 poller; C# collector 轮询 `ni_run/capture_seq` 并回写 NI 心跳与状态。振动数据首阶段仍由 `public.vib_features -> phm_v2.telemetry` 桥搬运, 未切到 C# 直写 telemetry。
## telemetry (长表, `PARTITION BY RANGE(ts)` 按月)
列: `machine_id` / `signal_id`(→signal) / `ts`(TIMESTAMPTZ) / `value` / `feature` / `epoch` / `regime`。
- `feature=NULL` = 原生标量读数 (PostgresSource 现场 reduce); `feature=rms/std/kurtosis/crest/p2p/...` = 振动窗特征 (采集端就地算)。
- 索引: `(signal_id, ts)` + `(machine_id, ts)`。PHM 取数天然按 (signal_id, ts) 拉时间序列; 看板"宽视图"用 pivot/视图。
- 分区: 干跑已建 `telemetry_2026_06`; **月分区自动化 = A3 待办**。

## health_result (PHM 回写, 看板纯读)
显示字段 (`mode`/`light`/`message`/`target_n`) 由**评分侧算好写入**, 中心看板不依赖 config。
核心列: `health`/`score`/`t2`/`spe`(Phase2)/`ucl_t2`/`ucl_spe` + 生命周期 `stage`/`n`/`n_days`/`target_n`/`admitted`/`steady` + 显示 `mode`/`light`/`message`/`contributions`(JSONB, Phase2)。
**UNIQUE(machine_id, phm_system, epoch, regime, ts)** → 幂等 UPSERT, 对上 `/api/sync`。

## 设计取舍
- 长表行数比宽表多, 但 `(signal_id, ts)` 复合索引 + 月分区使常用查询走索引+单分区, 稳定。
- 振动只存窗特征入 telemetry; 原始波形仅事件/手动入 raw_blocks (块+压缩)。
- 多机床/多协议横向扩展**不触碰 DDL** → [[ADR-005]]。

## 相关
- 整合计划/进度 (A–E) → `INTEGRATION_PLAN.md §1`
- 采集层全貌 → `ACQUISITION_CONTRACT.md`
- (历史) v0 设计稿 → `docs/archive/schema_design_draft.md`
