# 算法核架构 (algorithm-core)

> `PHM_claude/phm_pipeline/` 产品包的稳定参考: 数据流、各模块职责、生命周期三阶段。
> 现状/待办见 `PHM_claude/PROJECT_STATUS_AND_HANDOFF.md`; 决策依据见 `docs/decisions/`。更新: 2026-06-24。

## 数据流 (采集层与算法层解耦 —— 换采集源只换 DataSource, 上层不动)

```
DataSource → CollectionRecord → [regime标注·稳态门控] → segment → features → covariate
→ model(训练) / score(在线) → alarm → lifecycle⟲(每regime) → engine汇总 → selfcheck(report)
```

## 模块清单 (纯 numpy / SVD / pinv, 无 sklearn)

| 模块 | 职责 |
|---|---|
| `datasource.py` | **解耦点**。`CollectionRecord` 契约 (含 `precomputed` 预算特征字段, 供高频振动) + `FileSource`(回放UCI) / `MockSource` / `RealSource`(NC-Link 采集器) / `PostgresSource`(读 phm_v2.telemetry, 按 `is_high_freq` 分流) |
| `segment.py` | 稳态窗口截取 + 匀速段截断 (电流跃变法, 进给用) |
| `features.py` | 逐通道 reducer→特征向量 (FeatureSpec 配置驱动) + 派生特征 (q_over_p 等) |
| `covariate.py` | `TempResidualizer` 混淆温度回归剔除 (基线集拟合后冻结; 主轴热态作协变量) → [[ADR-002]] |
| `model.py` | `BaselineModel` = 标准化 + PCA(SVD) + T² + SPE; `ucl_method` 标定法 (经验分位/参数化/auto); 可序列化 <5KB; `RegularizedCovModel` 兜底 → [[ADR-001]] [[ADR-008]] |
| `score.py` | `health = exp(-3·max(T2/UCL_T2, SPE/UCL_SPE))` + T²/SPE 逐特征贡献分解 |
| `alarm.py` | `AlarmState`: 双层告警 (L1 物理限 ∥ L2 模型) + EWMA + K连续去抖 |
| `lifecycle.py` | `LifecycleManager`: 三阶段切换 + 混合过渡 + 基线准入门控 |
| `regime.py` | **C2 工况层**: `SteadyGate` 稳态门控 (非稳态不准入) + `RegimeLabeler` 工况标量分箱 (rpm档) → [[ADR-003]] |
| `engine.py` | **C2 健康引擎**: 多 regime 在线消费 (标注→门控→特征→残差化→每 regime 一套 lifecycle) → `HealthResult`; 混淆温空时退化为单 lifecycle (逐点复现 selfcheck) |
| `nc_profile.py` | 空跑 NC 程序框架 = regime **单一定义源** (详见 `ACQUISITION_CONTRACT.md §6`) |
| `config.py` | `SystemConfig` + `hydraulic_v1()` + `spindle_field_v1()`; `mature_min_n=max(stage2_max_n, ratio·p)` |
| `selfcheck.py` | FAR / 基线稳定性 / 阶段切换连续性 / 数据质检 |

## 生命周期三阶段 (lifecycle.py)
1. **n<30 工程先验** (CUSUM; `n<stage1_warmup` 池太小 std≈0, 健康度给中性, 不被噪声拖到 0)
2. **30–mature 分位评分**
3. **成熟期 PCA+T²+SPE** (混合过渡: 成熟门槛→`blend_hi`, w3 由 0 线性升满)
- 进成熟期门槛: `n ≥ mature_min_n` 且 `n_days ≥ stage3_min_days`。
- 混合起点锚定成熟门槛 `max(blend_lo, mature_min_n)`: 否则 `blend_lo` 早于门槛 (如液压 50<140) 时首条 stage3 样本权重已偏高 → 健康度台阶 (2026-06-29 修复, 详见 CURRENT_STATE)。
- **成熟期 `score>1` 样本不准入基线** (防故障污染); 阶段阈值/UCL法随 config 可调。

## 已验证结论 (step1-9, 证据基础)
- 多传感器联合基线可行; 成熟期 PCA+T²+SPE 最优, 正则化协方差次之, 裸 full-cov+pinv 病态排除 (cond# 1.1e8)。
- **关系异常 (step9) 是杀手锏**: 单变量/对角 AUC≈0.5, 只有带 SPE 的模型能看到"边际正常但耦合变了" → [[ADR-001]]。
- 混淆温回归 (step5) 使单通道预警提前 194→407min → [[ADR-002]]。
- 局限: step1-9 只覆盖轴承振动(FEMTO)+液压多传感器(UCI), **不含进给轴数据**; 进给反向间隙是物理推理未经数据验证。

## 自检命令 (在 `PHM_claude/` 下)
```bash
python -m phm_pipeline.regression_anchor   # 共享核 vs step7-9 数值对照 (改算法核必跑)
python -m phm_pipeline.run_selfcheck       # 端到端 (回放 UCI 液压逐日流)
python -m phm_pipeline.smoke_test          # 模块组合冒烟
```
没有 lint/CI; "测试" = 以上三脚本。

## 相关
- 评分回写到库 → `docs/modules/score-runner.md`
- 采集层 (telemetry/signal/regime 定义源) → `ACQUISITION_CONTRACT.md`
- 数据契约 (phm_v2 表) → `docs/architecture/data-contract.md`
