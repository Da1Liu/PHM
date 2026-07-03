# 中心健康看板 (center-dashboard)

> 中心侧**只读富前端**: `server/dashboard.py` + `server/static/dashboard_v2/`。读 `phm_v2`/`health_result` 渲染健康结果；现场采集调试归边缘 WebDashboard。更新: 2026-07-03。
> 运行: `python -m phm_pipeline.server.dashboard --port 8080` → Cloud 显式入口 `/cloud/`，兼容入口 `/` 默认进 v2。v1 (`/v1/`) 仅保留参照，勿再扩展。

## 信息架构
v2 master-detail: **机群列表** → **机床详情五标签** → **设置建档** + **大屏分诊** + 命令面板。响应式四档断点；纯原生 JS，无 CDN。

## 机床详情五标签
1. **概览** — 健康灯、建立期进度、健康环/sparkline；卡片可下钻诊断。
2. **诊断** — 真实 T²/SPE/UCL/贡献条，读 `health_result.contributions`；原始波形仅作诊断辅助读取。
3. **趋势** — 健康趋势折线与阈值参考。
4. **维护** — epoch/reset/维护事件入口；跨 reset 不可比。
5. **运行** — **只读采集状态**: OPC UA/NI 状态、心跳、最近同步、信号登记数量、打开 WebDashboard。启停、实时曲线、波形抓取、导出不在中心做。

## 设置建档职责
中心看板只管“健康系统资产与语义”，不复制现场采集工作台。

- **机床目录 / 边缘接入**: 中心列出已同步机床并提供边缘工作台入口；新机床接入、机床基础信息、采集配置优先在边缘 WebDashboard 完成并同步到中心。中心不再承担日常新增/删除采集点的工作台职责。
- **信号映射**: 中心只读展示 `phm_v2.signal` 的 PHM 语义字段与采集地址，用于检查信号覆盖和角色映射。新增信号、删除、克隆、导入/导出、OPC UA NodeId、启用/停用和 probe 实测在边缘 WebDashboard 维护。
- **边缘接入**: 展示 `acq_config.data.edge.gatewayId/baseUrl`、采集状态、信号摘要和采集参数摘要；跳转 WebDashboard 时自动追加 `machine_id=<当前机床>`。中心不直接编辑采样率、通道、OPC UA endpoint/profile/NodeId 等现场采集参数。
- **同步状态**: 只读边缘在线、最近同步、OPC UA/NI 采集器状态。

## 云边边界标记
- 中心侧代码归属 `PHM_claude/phm_pipeline/domain/cloud/`；共享契约与 ownership metadata 在 `domain/shared/`。
- `dashboard.py` 路由已用 `Domain.CLOUD / Domain.SHARED / Domain.EDGE` 标记归属；这些标记不改变现有行为，只用于约束后续新 API 放置。
- Cloud Dashboard 显式入口为 `/cloud/`；`/v2/` 和根 `/` 保持兼容。
- 云边边界正式说明见 `docs/architecture/cloud-edge-boundary.md`。

## API 摘要
- 读: `/api/fleet` `/api/machines` `/api/overview` `/api/machine/<id>/{signals,trend,diagnose,collector-status,waveform,alarms}`
- 机床: `/api/machines` 当前中心常规界面只读；历史写接口/删除流程需鉴权收口后再开放。
- 信号映射: `/api/machine/<id>/signals` 只读展示；信号新增/删除/克隆/导入导出下放边缘 WebDashboard。
- 采集配置/状态: `/api/machine/<id>/acq-config`、`collector-status`。中心读取边缘采集配置摘要并生成带 `machine_id` 的 WebDashboard 入口；不再暴露常规采集启停/采集参数编辑 UI。
- 边缘同步占位: `/api/sync` (Shared domain, store-and-forward 契约入口)

## 真/mock 状态
生产模式只读真实库；无数据返回 `source=empty`，DB 故障返回 503 degraded，不静默 mock。mock 仅 `--no-db`/demo 模式可达。连接池、`/api/fleet` 聚合、`/healthz`、waitress 已接。

## 待办
- **P0 写接口鉴权 + CORS 收紧**: 当前服务端写接口仍未鉴权，前端角色门控不能算安全边界。
- **P1 前端详情懒加载**: 首屏只拉 `/api/fleet`，机床详情按需拉 signals/acq/trend/diagnose。
- **P2 `/api/sync` 边缘入库**: store-and-forward 闭环仍待实现。

相关: `docs/modules/score-runner.md`、`docs/architecture/data-contract.md`、`INTEGRATION_PLAN.md`、`数控机床数据采集与状态监测系统/CLAUDE.md`。



