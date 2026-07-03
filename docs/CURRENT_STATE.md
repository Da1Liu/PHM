# CURRENT_STATE.md — 当前状态

> 只记“现在在哪一步、刚做完什么、接下来做什么、有什么坑”。完整历史看 `INTEGRATION_PLAN.md`；具体模块看 `docs/INDEX.md` 路由。更新: 2026-07-03。

## 当前开发阶段
**整合期** — 把现场采集系统与算法核合成一套产品。
- 算法核 `phm_pipeline`: PCA+T²+SPE 路线稳定，回归锚点/自检/冒烟已长期通过。
- 数据契约 `phm_v2`: machine/signal/telemetry/vib_raw_blocks/health_result 已建并跑通采集→评分→看板闭环。
- 当前主线: **采集层接入首台 OPC UA + 中心看板去 mock/收边界**。

## 最近完成
- **云边边界第一阶段落地 [✓ 2026-07-03]**: 不拆数据库、不改 schema；新增 `PHM_claude/phm_pipeline/domain/{edge,cloud,shared}` 与 `WebDashboard/api/src/domain/`，中心 Flask API 用 `Domain.CLOUD/EDGE/SHARED` 标记，边缘 Node API 暴露 `API_DOMAINS` 清单；新增显式入口 Cloud `/cloud/`、Edge `/edge/`（原 `/v2/`、`/`、`config.html`、`signals.html` 保持兼容）；DB 访问层暴露 ownership metadata。正式说明见 `docs/architecture/cloud-edge-boundary.md`，临时 `cloud_edge_*` 草稿已删除。
- **多机床边缘工作台按机床绑定 [✓ 2026-07-03]**: 修复从中心打开 `CNC_TEST` 边缘工作台仍读取 `FIELD_2026_06_18` 配置的问题。中心生成 WebDashboard 链接时统一追加 `?machine_id=<机床ID>`；WebDashboard `config.html`/`signals.js` 保留并透传该参数；Node API 从 query/body/header 解析 `machine_id`，`/api/config`、`/api/opcua/catalog`、OPC UA NodeId 保存、采集勾选保存均按机床读写 `phm_v2.acq_config` 与 `phm_v2.signal`。中心“边缘接入”仍在设置页，负责读取并展示边缘采集配置摘要，不直接编辑采集参数。
- **中心看板 vs 边缘采集工作台职责收口 [✓ 2026-07-02]**: 中心 v2 不再复制实时曲线/采集调试台。`运行`标签改为只读采集状态；`采集入口`仅保留边缘工作台地址、状态、信号摘要和参数摘要；启停、实时曲线、波形抓取、导出统一归 WebDashboard。中心信号映射只维护 PHM 语义字段，`source_addr` 只读并提示到边缘维护。固定 UI 文案改中文，固有名词 NI/OPC UA/WebDashboard 保留。
- **WebDashboard OPC UA 信号维护 [✓ 2026-07-02]**: `web/signals.html/js` 从只读清单升级为现场维护页，可编辑 OPC UA NodeId、启用/停用采集信号并保存到 `phm_v2.signal.source_addr` 与 `phm_v2.acq_config.data.opcua.enabledSignalIds`。Node API 新增 `PUT /api/signals/:id`、`PUT /api/opcua/selection`；`/api/opcua/catalog` 只展示 OPC UA 信号并带启用状态；poller 兼容旧 `_OPCUA_*` 表路径，按启用集合过滤并用新 NodeId 覆盖旧映射。限制: 新增任意新信号真正动态落库仍需后续 telemetry 路径。
- **采集配置单真相源 / 边缘入口 [✓ 2026-07-02]**: WebDashboard Node API 与 C# collector 默认按 `EDGE_MACHINE_ID` 或请求 `machine_id` 读写对应机床的 `phm_v2.acq_config`，`public.app_config` 仅 legacy fallback。控制位统一在 `data.control`；Node 1s reconcile OPC UA；C# 回写 NI 状态/心跳/行数/采样率/会话等。
- **评分与看板产品化硬化 [✓ 2026-06-30]**: DB 口令改环境变量/`.env`，生产 DB 故障返回 503 degraded 不再静默 mock；连接池与 `/api/fleet` 聚合；`dashboard_smoke` 守护；waitress/healthz/logging；`score_runner --day-mode calendar|replay` 修复日历日口径。
- **采集落库桥 Phase 1 [✓ 2026-06-30]**: `phm_pipeline.acquisition.pg_bridge` 把 `public.vib_features` 增量搬到 `phm_v2.telemetry`，watermark 幂等、按月分区自动创建，真实库 round-trip 通过。振动仍是过渡桥，C# 直写 telemetry 未做。
- **前端 v2 架构与评分回写闭环 [✓ 2026-06-24~29]**: v2 master-detail 成为正式中心看板；health_result 读真值；diagnose 读真实 T²/SPE/UCL/贡献；waveform 可读 vib_raw_blocks；多机床/多系统调度、信号映射、机床管理已完成。

## 当前任务 / 下一步候选
| 档 | 待办 | 桌面/真机 | 为何此档 |
|---|---|---|---|
| **P0 上真机前必堵** | **rpm 工况分层端到端接通** | 桌面可接线验证；真值需多 rpm 真机 | 不做会把多 rpm 数据静默混进单一基线，违反“同工况才能比”，后续健康分会被污染。 |
| **P0 上真机前必堵** | **写接口鉴权 + CORS 收紧** | 纯桌面 | 当前写接口/DELETE 仍无服务端鉴权，权限主要靠前端置灰；多机内网部署前必须补。 |
| **P1 纯桌面可推** | **score_runner 增量评分 + 模型持久化** | 纯桌面 | 现全量重放、不存模型；这是实时评分和边缘下沉前置。 |
| **P1 纯桌面可推** | **前端详情懒加载** | 纯桌面 | 首屏仍会拉多机多接口，需改为 `/api/fleet` 首屏 + 点开详情再拉。 |
| **P2 需真机/真实数据** | 主轴稳态门控、OPC UA 标量 telemetry、低频窗聚合、`/api/sync` | 需现场数据 | 属阶段 B/E，真机数据到位后推进。 |

**建议**: 准备上真机先做 P0 `rpm 工况分层` + `鉴权/CORS`；继续纯桌面产品化先做 `score_runner` 增量+模型持久化。

## 已知风险 / 坑
- **rpm 工况分层未端到端接通 (高)**: spindle `baseline_by=("rpm_bin",)`，但 `regime_bins={}` 空、PostgresSource/score_runner 尚未把 rpm 档合入基线键。接多档真实数据前必须修。
- **稳态门控对 vibration-only 数据未启用**: 当前 FIELD 回放是连续标定 burst，无 steady 通道；高振瞬态进入基线池导致健康偏低偏噪，这是准入规则未接真机的结果，不是算法 bug。
- **OPC UA 动态落库仍未完成**: WebDashboard 现在能按机床维护启用集合/NodeId，并在旧 `_OPCUA_*` 固定表路径下过滤已有映射；任意新增信号要真正采集入 `telemetry` 仍需 B2 动态写入路径。当前 Node OPC UA poller 仍是单实例，适合一个边缘进程操作/采集当前机床；同一进程同时采多机需后续做 per-machine poller。
- **selfcheck 连续性判据口径 (低)**: P3 修复后原始连续性也过，但控制台/文档口径仍可再统一。
- **首台 signal 三个现场事实**: 成对轴 X1/X2、Y1/Y2、B1/B2 有共址风险；液压只有 bool 压力无连续压力/流量；首台落地主系统是主轴。
- **陈旧文档**: `PHM_claude/PROJECT_STATUS_AND_HANDOFF.md` 仍有“液压先行”等旧说法，默认看 `CURRENT_STATE.md` 与 ADR-006。

## 现场标定待办 (阶段 E)
物理限 L1 / 稳态段匹配热机程序 / 工况分层粒度标定 / 大修 reset 流程 / 存量机退化验证。




