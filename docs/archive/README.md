# archive/ — 归档 (默认不读)

> 这里是**废弃方案 / 验证期产物 / 历史快照**。新 Session **不应加载**这些文件; 仅在追溯"当初为何这样定"时按需查单篇。
> 归档动作: 2026-06-24 文档上下文优化重构 (详见 `../INDEX.md`)。

## 内容与缘由

| 文件 | 性质 | 为何归档 |
|---|---|---|
| `CLAUDE_full_2026-06-22.md` | 旧版完整单一入口 (~5k tok) | 已被根 `CLAUDE.md` 精简版 (~1.5k) + `docs/` 分层取代; 保留作详述快照, 算法核/整合细节可在此追溯 |
| `cnc_health_baseline_technical_plan.md` | 5月旧技术方案 | 部分设定 (对角 T²、温度一律剔除) 已被 step7-9 **推翻**; 原有根目录 + PHM_claude 两份完全相同, 已删重复只留此份 |
| `cnc_multisensor_health_baseline_implementation_plan.md` | step7-9 落地路线 | 已被 `INTEGRATION_PLAN.md` 取代 |
| `schema_design_draft.md` | phm_v2 schema v0 设计稿 | 已建表实现 (`_integration_probe/*.sql`); health_result 设计已被实际建表版取代 |
| `validation-plans/uci_hydraulic_validation_plan.md` | UCI 液压可行性验证方案 | step1-9 验证期产物, 结论已沉淀进算法核 |
| `validation-plans/hydraulic_health_demo_steps.md` | 液压 demo step 方案 | 已被 uci 校准版取代 |
| `validation-plans/pronostia_health_curve_plan.md` | PRONOSTIA 健康曲线验证方案 | 验证期产物 |
| `validation-plans/mahalanobis_covariance_validation_plan.md` | 协方差有效性验证方案 | 验证期产物 |
| `validation-plans/multisensor_covariance_baseline_validation_plan.md` | 多传感器协方差验证 (**含已执行结论 §13**) | 验证期产物; §13 结论被算法核/handoff 引用, 追溯时看此处 |

> 注: 归档内各 `*_plan.md` 之间的相对路径引用已随移动失效, 属正常 (归档件不再维护互链)。
> 现行权威结论以 `PHM_claude/PROJECT_STATUS_AND_HANDOFF.md` + `INTEGRATION_PLAN.md` + 根 `CLAUDE.md` 为准。
