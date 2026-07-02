# vibration_db 统一数据契约设计稿 (v0, 待评审)

> 目的: 让 `vibration_db` 从"单台固定配置机床的采集落库"演进到"多机型 / 多协议 / 可扩展, 并直接服务 PHM 自基线"。
> 现新表(vib_features/_OPCUA_*/vib_raw_blocks)全空 -> 零迁移成本窗口。
> 原则: 新机型 / 新协议 = **只加数据行, 不改表结构**。

## 1. 设计目标 (来自已拍板决策)
- 多协议并存且**预留接口**: NC-Link / OPC UA / 其他数控系统, 数据须标协议来源。
- 多机床: 全表带 `machine_id`, 支撑 PHM "自基线 per 机床 + 大修 reset epoch"。
- 服务 PHM 算法核: 携带**工况标签**(同工况才能比) + **温度角色**(混淆 vs 耦合) + **系统归属**(进给/主轴/液压)。
- 时间戳统一 `TIMESTAMPTZ` (现宽表 TIMESTAMP/TIMESTAMPTZ 混用 -> 对齐隐患)。
- 性能稳定 + 可扩展: 高频原始波形按需存块; 标量遥测长表 + 复合索引 + 时间分区。

## 2. 核心结构: 维度表 + 长表

### 2.1 machine (机床维表)
```sql
CREATE TABLE machine (
  machine_id   TEXT PRIMARY KEY,          -- 设备 SN
  cnc_system   TEXT,                       -- 华中 / 西门子840D / ...
  model        TEXT,
  current_epoch INT NOT NULL DEFAULT 1,    -- 大修/拆装后 +1, 跨 epoch 不可比
  note         TEXT
);
```

### 2.2 signal (信号定义维表 —— 承载 PHM channel_map 语义)
```sql
CREATE TABLE signal (
  signal_id    BIGSERIAL PRIMARY KEY,
  machine_id   TEXT NOT NULL REFERENCES machine(machine_id),
  code         TEXT NOT NULL,             -- 机内唯一短码, 如 vib_gearbox_1 / spindle_current
  display_name TEXT,                       -- 中文名
  unit         TEXT,                       -- g / A / ℃ / ...
  protocol     TEXT NOT NULL,              -- 'nclink' | 'opcua' | ...  (协议来源, 可路由/溯源)
  source_addr  TEXT,                       -- NC-Link path@index 或 OPC UA NodeId, 原样留存
  phm_system   TEXT,                       -- 'feed'|'spindle'|'hydraulic'
  signal_kind  TEXT NOT NULL,              -- 'vibration'|'current'|'speed'|'position'|'temperature'|'pressure'|'bool'
  temp_role    TEXT,                       -- 温度专用: 'confound'(回归剔除) | 'coupled'(进向量) | NULL
  regime_role  BOOLEAN DEFAULT FALSE,      -- 是否参与工况分层判定
  is_high_freq BOOLEAN DEFAULT FALSE,      -- TRUE=高频波形(走 raw_blocks+特征), FALSE=标量遥测
  UNIQUE(machine_id, code)
);
```

### 2.3 telemetry (标量遥测长表 —— 统一容纳 OPC UA 标量 / NC-Link 标量 / 振动窗特征)
```sql
CREATE TABLE telemetry (
  machine_id TEXT NOT NULL,
  signal_id  BIGINT NOT NULL REFERENCES signal(signal_id),
  ts         TIMESTAMPTZ NOT NULL,
  value      DOUBLE PRECISION,            -- 标量读数; 振动则是某特征(配 feature 列)
  feature    TEXT,                         -- NULL=原生标量; 'rms'/'kurtosis'/... = 振动窗特征
  epoch      INT NOT NULL DEFAULT 1,
  regime     TEXT                          -- 工况分层键(可空), 如 'rpm=1500|load=mid'
) PARTITION BY RANGE (ts);
CREATE INDEX ix_telemetry_sig_ts ON telemetry (signal_id, ts);
CREATE INDEX ix_telemetry_machine_ts ON telemetry (machine_id, ts);
-- 按月声明式分区, 控制单分区体量(振动特征 1Hz/通道 ≈ MB/天)
```
> 说明: 新增任意机型/协议/通道, 只在 signal 加一行定义 + telemetry 加数据行, **DDL 不变**。
> PHM 取数天然按 (signal_id, ts) 拉时间序列, 长表比宽表更顺手; 看板需要的"宽视图"用 pivot / 视图解决。

### 2.4 vib_raw_blocks (保留, 加 machine_id/epoch)
现结构(event_id/channel/time_start/rate/n_samples/data bytea)设计好, 仅补 `machine_id`/`epoch`, 并把 `channel` 改为引用 `signal_id`。事件/手动抓取的 float32 块继续走 TOAST 压缩。

### 2.5 health_result (PHM 输出回写, 供前端读)
```sql
CREATE TABLE health_result (
  machine_id TEXT NOT NULL, phm_system TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL, epoch INT NOT NULL,
  health DOUBLE PRECISION, score DOUBLE PRECISION,
  t2 DOUBLE PRECISION, spe DOUBLE PRECISION,
  alarm_level INT,                          -- 0 正常 /1 关注 /2 告警
  top_contrib JSONB,                        -- 贡献分解 top 特征
  lifecycle_stage TEXT                      -- 建立期/过渡/成熟期
);
CREATE INDEX ix_health_machine_ts ON health_result (machine_id, ts);
```

## 3. 与现表的关系 / 迁移思路
- `_OPCUA_2/3/new`(空): 不迁数据, 改为**采集端写 telemetry**; 旧宽表读路径(`/api/vibration` 等)保留兼容期, 看板逐步切到 telemetry 视图。
- `vib_features`(空): 并入 telemetry (feature 列区分), 或保留为 telemetry 的振动特化视图。二选一, 倾向并入以统一。
- `_tb_field_..._main`(386MB 实测, 保留勿删): 作为离线回放/特征体检的素材, 不纳入新契约。
- `app_config` / `collector_control`: 不变(采集模块控制面, 与数据契约正交)。

## 4. 性能与可扩展取舍
- 长表行数比宽表多, 但 (signal_id, ts) 复合索引 + 月分区使常用查询(某信号某时段)走索引+单分区, 稳定。
- 振动只存窗特征(1Hz/通道级)入 telemetry, 原始波形仅事件/手动入 raw_blocks(块+压缩) -> 沿用线B已验证的"省盘且不丢关键信息"三级策略。
- 多机床/多协议横向扩展不触碰 DDL, 符合"预留协议接口"。

## 5. 定稿决策 (用户 2026-06-22)
1. **通道映射**: 暂无定论, 先假定 vib1/2/3=主传动变速箱箱体, vib4=主轴前轴承套。改映射只动 signal 表数据行, 不动 DDL。
2. **vib_features 并入 telemetry** (统一), 用 `feature` 列区分原生标量(NULL)与振动窗特征(rms/kurtosis/...)。不再单设 vib_features 表。
3. **工况分层 regime** 照 PROJECT_STATUS_AND_HANDOFF.md 已定: 液压=单基线(regime NULL); 主轴=rpm档×热态; 进给=轴×方向×速度档。取"满足诊断需求的最粗分层"。
4. **health_result 先缓**: 前端仅定到五页结构未到字段级, 本阶段不建; 设计保留, 上前端再建。

## 6. 落地范围 (本阶段)
- 建 `phm_v2` 独立 schema, 含 machine / signal / telemetry(分区) / vib_raw_blocks。**不建 health_result**。
- 与 public 现有表完全隔离, 可 `DROP SCHEMA phm_v2 CASCADE` 整体回滚。
- 干跑验证: 把第1步 159 窗振动特征按新契约写入 telemetry, 再由 PHM 侧读回, 闭环证明契约可用。
