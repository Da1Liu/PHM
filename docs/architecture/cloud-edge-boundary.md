# 云边边界第一阶段设计

更新: 2026-07-03

本文是当前阶段的正式云边边界说明。目标是**建立 Edge Domain 与 Cloud Domain 的代码/API/数据 ownership 边界**，但不物理拆库、不改数据库 schema、不引入消息队列或微服务。

## 目标

- 现有业务行为保持可用。
- 新功能能明确放入 Edge、Cloud 或 Shared。
- 数据库仍是当前 PostgreSQL，但代码中能看出未来 Edge Local DB / Cloud DB 的迁移方向。
- 后续逐步替换为真正的 store-and-forward 同步，而不是继续让两套 UI 共享运行状态。

## 代码边界

### Python / 中心侧

- `PHM_claude/phm_pipeline/domain/cloud/`: Cloud Domain 标记包。
- `PHM_claude/phm_pipeline/domain/edge/`: Edge Domain 标记包。
- `PHM_claude/phm_pipeline/domain/shared/`: 共享契约与 ownership metadata。
- `PHM_claude/phm_pipeline/server/dashboard.py`: 中心看板 API 通过 `tag_api(Domain.CLOUD|EDGE|SHARED, ...)` 标记归属。
- `PHM_claude/phm_pipeline/db_config.py`: 暴露 `DB_OWNERSHIP`，只声明 ownership，不改变连接行为。

### Node / 边缘侧

- `数控机床数据采集与状态监测系统/WebDashboard/api/src/domain/boundary.js`: Express API domain 常量。
- `数控机床数据采集与状态监测系统/WebDashboard/api/src/domain/ownership.js`: 边缘侧数据 ownership metadata。
- `WebDashboard/api/src/server.js`: 暴露 `API_DOMAINS` 清单，标记每个 API 属于 Edge 或 Shared。
- `WebDashboard/api/src/db.js`: 暴露 `DB_OWNERSHIP`，只声明 ownership，不改变连接行为。

### 顶层说明

- `domain/edge/README.md`
- `domain/cloud/README.md`
- `domain/shared/README.md`

这些文件是轻量边界说明，用于让新代码知道应放入哪个域。

## UI 入口

| UI | 显式入口 | 兼容入口 | 归属 |
|---|---|---|---|
| Cloud Dashboard | `/cloud/` | `/`、`/v2/` | Cloud |
| Edge UI | `/edge/`、`/edge/config`、`/edge/signals` | `/`、`/config.html`、`/signals.html` | Edge |

新增入口只是别名，不改变现有 URL 行为。

## API 归属原则

| Domain | API 类型 | 规则 |
|---|---|---|
| Edge | 采集启停、抓波、OPC UA/NI 配置、NodeId、导出、现场实时曲线 | 只由边缘 UI / 边缘服务常规写 |
| Cloud | 机群、健康趋势、诊断、资产、维护、中心大屏 | 中心看板读汇总数据，默认不直接控制采集 |
| Shared | `/api/sync`、信号契约、采集配置摘要、collector 状态投影 | 表示契约共享，不表示双方都有任意写权限 |

中心仍保留少量历史写能力和远程 control 路由以保持兼容，但已标为 Edge/legacy，不作为新功能入口。

## 数据归属矩阵

| 表/数据 | 当前物理位置 | 第一阶段 Domain | 未来位置 |
|---|---|---|---|
| `phm_v2.machine` | shared PostgreSQL | Cloud | Cloud DB 权威，Edge 缓存 |
| `phm_v2.signal` PHM 语义字段 | shared PostgreSQL | Cloud | Cloud DB 权威 |
| `phm_v2.signal.source_addr` | shared PostgreSQL | Edge | Edge Local DB 权威，上报 Cloud 摘要 |
| `phm_v2.acq_config.data.acquisition/opcua/nclink` | shared PostgreSQL | Edge | Edge Local DB |
| `phm_v2.acq_config.data.control` | shared PostgreSQL | Edge | Edge Local DB |
| `phm_v2.telemetry` | shared PostgreSQL | Shared | Edge buffer -> Cloud DB |
| `phm_v2.vib_raw_blocks` | shared PostgreSQL | Edge | Edge Local DB，按需同步 |
| `phm_v2.health_result` | shared PostgreSQL | Cloud | Cloud DB，可接收 Edge 评分 |
| `phm_v2.bridge_state` | shared PostgreSQL | Edge | Edge Local DB |
| `public.vib_features` | shared PostgreSQL | Edge | Edge Local DB |
| `public.vib_events` | shared PostgreSQL | Edge | Edge Local DB |
| `public.vib_raw_blocks` | shared PostgreSQL | Edge | Edge Local DB |
| `public._OPCUA_2/_OPCUA_3/_OPCUA_new` | shared PostgreSQL | Edge | Edge Local DB 或直写 telemetry |
| `public.app_config` | shared PostgreSQL legacy | Edge | 退役或 Edge fallback |

## 第一阶段不做

- 不拆 `phm_v2` schema。
- 不迁移 public 旧表。
- 不引入 Kafka/RabbitMQ/Redis。
- 不把中心看板或 WebDashboard 拆成微服务。
- 不改变现有采集、看板、评分行为。

## 后续迁移顺序

1. 写接口鉴权与 CORS 收紧。
2. 中心远程采集 control 默认禁用或显式开关化。
3. `/api/sync` 从占位变成幂等接收契约。
4. public 采集旧表补 `machine_id/session/gateway_id` 归属。
5. 边缘本地库试点，中心只通过 sync 消费数据。
6. 多站点、多网关和 per-machine poller。

## 验证

本阶段落地后已通过:

- `python -m py_compile ...`
- `node --check ...`
- `python -m phm_pipeline.server.dashboard_smoke`
- `python -m phm_pipeline.regression_anchor`
- `python -m phm_pipeline.smoke_test`
- `python -m phm_pipeline.run_selfcheck`
