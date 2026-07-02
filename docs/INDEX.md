# INDEX.md — 全项目知识路由器 (初稿)

> 新 Session 启动: 读根 `CLAUDE.md`(精简入口) → 本文件(决定该读哪份) → 按需取**单篇**。
> **不要一次性加载所有文档。** 更新: 2026-06-24。
>
> 状态列 **✅现存** = 文件已在该路径可直接读。(2026-06-24 重构后所有篇目均已落地。)

## 0. 新 Session 推荐加载顺序
1. `CLAUDE.md` (根, 精简入口, ~1.5k tok) — **必读**
2. `docs/CURRENT_STATE.md` — **必读**, 知道现在在哪一步、接哪个活
3. 按手头任务, 从下表取 **1–2 篇**, 不要全量加载
4. 仅当改算法核 / 改库 / 接采集器时, 才下钻 architecture 或 decisions 单篇

## 1. 入口与状态 (高频, 每次都可能读)
| 文件 | 作用 | 何时读 | 优先级 | 状态 |
|---|---|---|---|---|
| `CLAUDE.md` (根) | 精简单一入口: 简介/技术栈/约束/路由 | 每次开局 | 高 | ✅已精简 (~1.5k); 旧详版快照 `docs/archive/CLAUDE_full_2026-06-22.md` |
| `docs/CURRENT_STATE.md` | 当前阶段/最近完成/当前任务/下一步/风险 | 每次开局, 接续工作 | 高 | 现存 |
| `INTEGRATION_PLAN.md` (根) | **整合权威计划**: 决策表/phm_v2 契约/采集架构/分阶段步骤(A–E)/待办 | 推进整合任一阶段 | 高 | 现存 |

## 2. 架构 (architecture/ — 长期稳定知识)
| 文件 | 作用 | 何时读 | 优先级 | 状态 / 来源 |
|---|---|---|---|---|
| `docs/architecture/algorithm-core.md` | PCA+T²+SPE / 生命周期三阶段 / 工况层 / 数据流 | 改算法核、理解评分链路 | 高 | ✅现存 (来源: PROJECT_STATUS + archive 快照) |
| `ACQUISITION_CONTRACT.md` (根) | **采集层全貌**: 多协议 telemetry 契约 / signal维表↔采集映射 / NC空跑 profile↔regime / 稳态门控两层 | 接采集器、加协议、理解 regime | 高 | 现存 (= architecture/acquisition-layer) |
| `docs/architecture/data-contract.md` | phm_v2 schema: machine/signal/telemetry(月分区)/vib_raw_blocks/health_result | 改库、读写 telemetry/回写健康 | 高 | ✅现存 (DDL 以 `_integration_probe/*.sql` 为准) |

## 3. 模块 (modules/ — 各产品组件)
| 文件 | 作用 | 何时读 | 优先级 | 状态 / 来源 |
|---|---|---|---|---|
| `PHM_claude/phm_pipeline/server/README.md` | NC-Link 采集控制台 (边缘侧 app.py): 连接→映射→采集→评分→看板 | 改边缘控制台 | 中 | 现存 |
| `docs/modules/center-dashboard.md` | 中心只读看板 (dashboard.py) v2 master-detail/标签/API/线B采集配置 (v1 五页平级已废弃) | 改看板前端 | 中 | ✅现存 |
| `docs/modules/score-runner.md` | 评分回写闭环 (score_runner.py → health_result) | 改评分回写、加机床/系统调度 | 中 | ✅现存 |
| `数控.../CLAUDE.md` | **采集落库子系统入口** (自成体系, 含 PG 库结构/连接/运行) | 动 C#/Node 采集系统 | 中 | 现存 (**不迁移**, 子系统自带) |

## 4. 决策 (decisions/ — ADR 风格: Decision / Reason / Consequence)
> ✅已拆成独立 ADR (来源: 根CLAUDE §四「关键约束」+ `PROJECT_STATUS §2 决策表` + 验证结论), 便于单点引用。
| 文件 | 决策 | 优先级 | 状态 |
|---|---|---|---|
| `docs/decisions/ADR-001-pca-t2-spe.md` | 成熟期算法锁定 PCA+T²+SPE, SPE 不可省 | 高 | ✅现存 |
| `docs/decisions/ADR-002-temperature-roles.md` | 温度分混淆/耦合两类角色 | 高 | ✅现存 |
| `docs/decisions/ADR-003-regime-stratification.md` | 工况分层=诊断分辨率旋钮, 取最粗分层 | 高 | ✅现存 |
| `docs/decisions/ADR-004-self-baseline-epoch.md` | 自基线 + 大修 epoch reset, 跨 reset 不可比 | 高 | ✅现存 |
| `docs/decisions/ADR-005-multiprotocol-telemetry-seam.md` | 多协议接缝=telemetry+signal 维表, 非代码接口 | 高 | ✅现存 |
| `docs/decisions/ADR-006-spindle-first.md` | 首台落地主系统=主轴 (液压仅 bool, 进给共址需 probe) | 高 | ✅现存 |
| `docs/decisions/ADR-007-edge-center-split.md` | 边缘 store-and-forward + 中心只读富前端 | 中 | ✅现存 |
| `docs/decisions/ADR-008-mature-gate-compression.md` | 参数化 UCL 压成熟期门槛 (主轴 ~5p) | 中 | ✅现存 (来源 `INTEGRATION_PLAN C1b`) |

## 5. 运维 (operations/)
| 文件 | 作用 | 何时读 | 状态 |
|---|---|---|---|
| `docs/operations/run-commands.md` | 算法核/控制台/看板/评分/DB 运行与自检命令汇总 | 跑自检、起服务 | ✅现存 |
| `数控.../WebDashboard/RUNBOOK_现场.md` | 现场两进程启动 (NI 采集 + OPC UA) | 现场部署采集 | 现存 (**不迁移**) |

## 6. 归档 (`docs/archive/` — 废弃/历史/验证期, 默认不读)
> 已于 2026-06-24 归档完毕, 清单与缘由见 `docs/archive/README.md`。**新 Session 不应加载**; 仅追溯"为何这样定"时按需查单篇。
| 现路径 | 性质 | 状态 |
|---|---|---|
| `docs/archive/CLAUDE_full_2026-06-22.md` | 旧版完整单一入口快照 (~5k tok) | ✅已归档 (根 CLAUDE 已精简替换) |
| `docs/archive/cnc_health_baseline_technical_plan.md` | 5月旧方案 (对角T²/温度一律剔除已被 step7-9 推翻) | ✅已归档 (原两份完全相同, 已删重复留 1 份) |
| `docs/archive/cnc_multisensor_health_baseline_implementation_plan.md` | step7-9 落地路线 (已被 INTEGRATION_PLAN 取代) | ✅已归档 |
| `docs/archive/schema_design_draft.md` | phm_v2 schema v0 设计稿 (已建表实现取代) | ✅已归档 |
| `docs/archive/validation-plans/*.md` | 5 份 step1-9 验证方案 (uci/hydraulic-demo/pronostia/mahalanobis/multisensor) | ✅已归档 (multisensor §13 结论待来日抽进 algorithm-core) |
| `数控.../WindowsFormsApp1/{DEPRECATED,评审材料}.md` | 退役 WinForms 说明 + 旧评审报告 | 留原位 (子系统自管, 不迁移) |

## 迁移说明 (重要)
- **根 `CLAUDE.md` 已精简** (~1.5k, 自动加载); 旧详版快照在 `docs/archive/CLAUDE_full_2026-06-22.md`。Claude Code 只自动加载根 `CLAUDE.md` 与子目录 CLAUDE.md, 故 `docs/` 下不再另放 CLAUDE.md。
- `数控机床数据采集与状态监测系统/` 是**半独立子系统**, 自带 CLAUDE.md + RUNBOOK + 各 README, **不并入 docs/**, 仅本 INDEX 引用。
- architecture(2) / modules(2) / decisions(8 ADR) / operations(1) ✅**已建并填实** (2026-06-24)。`ACQUISITION_CONTRACT.md` 即采集层架构篇, 保留根目录不另立。待来日: multisensor §13 结论抽进 algorithm-core。
