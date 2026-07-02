# 多变量马氏距离（协方差矩阵）有效性验证方案

> 目标：在不重复 `pronostia_health_curve_plan.md` 已完成实验的前提下，单独验证“完整协方差矩阵”在健康基线异常评分中的有效性。
>
> 结论定位：现有 Step 2/3/4/5 已经证明基于 Hotelling T2/马氏距离的健康曲线链路可运行、可告警、可跨 PRONOSTIA 多轴承复现。本方案不再验证“健康曲线能不能做成”，而是验证“使用完整协方差矩阵是否比忽略特征相关性的评分更有效”。

---

## 1. 这个问题现在验证得对吗？

是的，但需要把验证问题说得更精确：

```text
不是重新验证马氏距离/T2 能否生成健康曲线；
而是验证完整协方差矩阵 Σ 是否真的有用。
```

当前脚本中已经使用了完整协方差矩阵：

- `step2_scoring.py`：Bearing1_1，4 个水平振动特征，`np.cov(Xhz)` + `np.linalg.pinv(cov)`。
- `step3_multi_bearing_validation.py`：6 个 Learning_set 轴承复用同一链路。
- `step4_temp_fusion_t2.py`：对比振动、温度融合、PCA+T2。
- `step5_temp_regression_residual_t2.py`：对比原始振动 T2 与温度残差 T2。

这些实验已经能说明完整链路有基本可用性，但还不能单独说明“协方差项”本身有效。因为缺少以下对照：

- 完整协方差马氏距离 vs 对角协方差马氏距离。
- 完整协方差马氏距离 vs 标准化欧氏距离。
- 完整协方差马氏距离 vs 单特征/独立特征评分。
- 完整协方差马氏距离 vs 被破坏相关结构后的伪协方差评分。

---

## 2. 已有实验事实

### 2.1 已完成结果，不重复执行

已有结果位于：

```text
outputs/step2_scoring/
outputs/step3_multi_bearing/
outputs/step4_temp_fusion/
outputs/step5_temp_regression/
```

其中 Step 3 多轴承结果：

| 轴承 | FAR(%) | Spearman(health, TTF) | 首次告警寿命占比 | 提前量 |
|---|---:|---:|---:|---:|
| Bearing1_1 | 1.071 | 0.850 | 58.40% | 194.3 min |
| Bearing1_2 | 1.149 | 0.209 | 94.83% | 7.5 min |
| Bearing2_1 | 1.099 | 0.276 | 93.19% | 10.3 min |
| Bearing2_2 | 1.266 | 0.758 | 29.86% | 93.2 min |
| Bearing3_1 | 1.961 | 0.268 | 23.11% | 66.0 min |
| Bearing3_2 | 1.227 | 0.372 | 87.48% | 34.2 min |

Step 4/5 对 Bearing1_1 的扩展结果：

| 模型 | FAR(%) | Spearman | 告警寿命占比 | 提前量 | 曲线粗糙度 |
|---|---:|---:|---:|---:|---:|
| vib4_raw_t2 | 1.071 | 0.850 | 58.40% | 194.33 min | 0.140596 |
| vib4_temp_raw_t2 | 1.071 | 0.427 | 10.17% | 419.67 min | 0.018112 |
| vib4_temp_pca_t2 | 1.071 | 0.900 | 52.16% | 223.50 min | 0.091670 |
| vib4_temp_residual_t2 | 1.071 | 0.892 | 12.88% | 407.00 min | 0.080801 |

### 2.2 协方差值得单独验证的原因

Bearing1_1 健康基线窗口中，4 个水平振动特征存在明显相关性：

```text
特征: rms_h, kurt_h, crest_h, p2p_h

相关矩阵约为：
[[ 1.000,  0.106, -0.038,  0.897],
 [ 0.106,  1.000,  0.657,  0.418],
 [-0.038,  0.657,  1.000,  0.368],
 [ 0.897,  0.418,  0.368,  1.000]]
```

典型相关关系：

- `rms_h` 与 `p2p_h` 高相关，约 0.897。
- `kurt_h` 与 `crest_h` 中高相关，约 0.657。

这说明多个特征不是相互独立的。完整协方差矩阵理论上可以避免对相关特征重复计分，并识别“单个特征看似不异常、但组合关系异常”的样本。但这仍需通过消融实验验证。

---

## 3. 核心假设

### H1：完整协方差矩阵能减少相关特征的重复计分

如果 `rms_h` 和 `p2p_h` 同向变化属于健康基线中的正常相关模式，完整协方差 T2 不应把这种正常共变过度放大；对角协方差或欧氏距离可能会重复累计两个特征的偏移。

### H2：完整协方差矩阵能捕捉组合关系异常

如果某个样本的单特征 z-score 都不极端，但特征组合偏离健康基线相关结构，完整协方差 T2 应该比对角方法更敏感。

### H3：完整协方差矩阵的收益应体现在多指标综合表现上

不要求完整协方差在每个轴承、每个指标上都最好，但应在以下方面至少有稳定收益之一：

- 更好的退化单调性。
- 更合理的告警提前量。
- 更低的健康段误报率或更稳定的误报控制。
- 更平滑且不丢失退化敏感性的健康曲线。
- 更强的组合异常识别能力。

---

## 4. 验证对象与数据范围

### 4.1 主验证数据

使用已生成的特征文件，不重新提取原始振动：

```text
outputs/step3_multi_bearing/*_features.csv
```

覆盖 6 个 PRONOSTIA Learning_set 轴承：

```text
Bearing1_1
Bearing1_2
Bearing2_1
Bearing2_2
Bearing3_1
Bearing3_2
```

### 4.2 主特征集

沿用已完成实验中的主特征：

```text
rms_h, kurt_h, crest_h, p2p_h
```

理由：

- 与 Step 2/3 已有结果完全一致，便于对照。
- 水平振动方向已经作为主方向完成验证。
- 4 维特征数量足够小，适合清晰解释协方差矩阵作用。

### 4.3 可选扩展特征集

仅作为补充敏感性检查：

```text
rms_h, kurt_h, crest_h, p2p_h, rms_v, kurt_v, crest_v, p2p_v
```

作用：检查维度增加后，完整协方差矩阵是否仍稳定；同时暴露小样本协方差估计的风险。

---

## 5. 对照模型设计

所有模型共用同一健康基线窗口、同一标准化参数、同一告警规则、同一评价指标。唯一变化是距离度量/协方差结构。

### M0：单特征基线

每个特征独立计算 z-score，取最大值或加权平均作为异常分数。

```text
score_max_z = max(abs(z_i))
score_mean_z2 = mean(z_i^2)
```

目的：代表最简单的单变量异常检测。

### M1：标准化欧氏距离

使用健康段 mean/std 标准化后计算：

```text
D2_euclidean = z^T z
```

目的：只考虑各特征偏移量，不考虑方差相关结构。

### M2：对角协方差马氏距离

只保留协方差矩阵对角线：

```text
Σ_diag = diag(Σ)
D2_diag = (x - μ)^T Σ_diag^-1 (x - μ)
```

目的：保留各特征方差尺度，但忽略特征之间的相关性。

注意：如果已经在健康段 z-score 标准化，M1 与 M2 可能非常接近。这是合理结果，说明对角协方差无法利用特征相关结构。

### M3：完整协方差马氏距离

当前 Step 2/3 使用的方法：

```text
D2_full = (x - μ)^T Σ_full^-1 (x - μ)
```

协方差逆矩阵使用 `pinv`，与现有脚本保持一致。

目的：验证完整协方差矩阵对相关特征的建模收益。

### M4：正则化完整协方差马氏距离

为了避免小样本或强共线导致协方差矩阵病态，增加岭正则：

```text
Σ_reg = (1 - λ)Σ + λI
λ ∈ {0.01, 0.05, 0.10}
```

目的：判断完整协方差收益是否依赖不稳定的矩阵求逆；若 M3 波动较大而 M4 更稳，应优先采用 M4。

### M5：相关结构破坏对照

在健康段内对每一列特征独立打乱顺序，保持每个特征的边际分布不变，但破坏特征间相关关系，再估计协方差：

```text
Xh_shuffle[:, j] = shuffle(Xh[:, j])
```

目的：如果完整协方差真的利用了相关结构，则 M3 应优于 M5；否则说明收益可能只来自边际尺度，而非协方差相关项。

---

## 6. 实验步骤

### Step A：复用已有特征与统一数据切分

对每个轴承读取：

```text
outputs/step3_multi_bearing/{bearing}_features.csv
```

固定健康基线窗口：

```text
health_frac = 0.10
h_end = int(n * health_frac)
```

敏感性检查窗口：

```text
health_frac ∈ {0.05, 0.10, 0.20}
```

### Step B：基线段标准化

所有模型均使用健康段统计量：

```text
μ_std = mean(X[:h_end])
σ_std = std(X[:h_end])
Z = (X - μ_std) / σ_std
```

这样可以保证模型差异主要来自协方差结构，而不是量纲。

### Step C：估计不同协方差结构

在 `Z[:h_end]` 上分别估计：

- 单特征统计。
- 单位矩阵。
- 对角协方差。
- 完整协方差。
- 正则化完整协方差。
- 打乱相关结构后的伪完整协方差。

记录每个协方差矩阵的诊断信息：

```text
condition_number
min_eigenvalue
max_eigenvalue
offdiag_abs_mean
offdiag_abs_max
```

### Step D：计算异常分数与健康度

对每个模型计算异常分数 `score(t)`。

健康度统一映射为：

```text
health(t) = exp(-3 * score(t) / UCL)
```

其中：

```text
UCL = quantile(score[:h_end], 0.99)
```

### Step E：告警规则保持一致

沿用已有实验规则：

```text
连续 K=5 个点 score > UCL，记为首次告警
```

输出：

```text
alarm_idx
alarm_life_pct
lead_snaps
lead_min
```

### Step F：多轴承汇总与排名

对每个模型、每个轴承输出完整指标，再计算跨轴承均值/中位数/排名。

不只看平均值，还要看稳定性：

```text
median_spearman
median_alarm_life_pct
median_lead_min
num_valid_alarm
num_good_spearman
num_excessive_early_alarm
num_late_alarm
```

---

## 7. 评价指标

### 7.1 主指标

| 指标 | 含义 | 期望 |
|---|---|---|
| FAR(%) | 健康段误报率 | 接近 1%，不显著高于其他模型 |
| Spearman(health, TTF) | 退化单调性 | 越高越好 |
| alarm_life_pct | 首次告警寿命占比 | 不能过早，也不能过晚 |
| lead_min | 告警提前量 | 有足够提前量 |
| roughness | 健康曲线跳变程度 | 越低越好，但不能以牺牲敏感性为代价 |

### 7.2 协方差专属指标

| 指标 | 含义 | 期望 |
|---|---|---|
| offdiag_abs_mean | 非对角相关强度 | 用于解释完整协方差是否有建模价值 |
| condition_number | 协方差矩阵病态程度 | 过大时需正则化 |
| rank_full_vs_diag | 完整协方差相对对角协方差的排名 | M3/M4 优于 M2 |
| full_minus_diag_spearman | 单调性提升 | 大于 0 为正收益 |
| full_minus_diag_roughness | 曲线粗糙度变化 | 小于 0 为更平滑 |
| shuffle_drop | M3 相对 M5 的性能差 | M3 优于 M5 说明相关结构有效 |

### 7.3 告警时机分档

PRONOSTIA 是加速退化数据，不宜用真实机床的慢退化尺度解释。这里只做相对分档：

```text
过早告警：alarm_life_pct < 10%
合理偏早：10% <= alarm_life_pct < 40%
中段告警：40% <= alarm_life_pct < 75%
偏晚告警：75% <= alarm_life_pct < 95%
过晚/失效前告警：alarm_life_pct >= 95% 或无告警
```

完整协方差不要求告警越早越好。若过早告警导致大量提前但退化单调性差，应判为不优。

---

## 8. 通过判据

### 8.1 强通过

满足以下条件可认为完整协方差矩阵有效：

1. M3 或 M4 在 6 个轴承中的综合排名优于 M1/M2。
2. M3/M4 的中位 Spearman 高于 M2。
3. M3/M4 的 FAR 不显著高于 M2。
4. M3/M4 的告警不是系统性过早或系统性过晚。
5. M3 明显优于 M5，说明收益来自真实相关结构，而不是随机矩阵效应。

### 8.2 弱通过

若 M3 不稳定，但 M4 稳定优于 M2，则结论为：

```text
完整协方差结构有价值，但必须使用正则化协方差，不建议直接 pinv 原始协方差。
```

### 8.3 不通过

出现以下情况应判定完整协方差矩阵在当前特征集上收益不足：

1. M3/M4 与 M2 指标基本持平，且 M3 不优于 M5。
2. M3/M4 明显提高误报率或造成系统性过早告警。
3. 协方差矩阵病态严重，正则化后收益消失。
4. 完整协方差仅在 Bearing1_1 有收益，但跨轴承不稳定。

不通过不代表马氏距离不可用，而是说明当前 4 个特征下“非对角协方差项”的收益不足，可以退回对角协方差或正则化协方差。

---

## 9. 需要产出的文件

建议新增一个独立实验脚本和输出目录：

```text
step6_mahalanobis_covariance_ablation.py
outputs/step6_mahalanobis_covariance/
```

输出文件：

```text
outputs/step6_mahalanobis_covariance/covariance_diagnostics.csv
outputs/step6_mahalanobis_covariance/model_comparison_by_bearing.csv
outputs/step6_mahalanobis_covariance/model_comparison_summary.csv
outputs/step6_mahalanobis_covariance/full_vs_diag_delta.csv
outputs/step6_mahalanobis_covariance/mahalanobis_covariance_ablation.png
```

### 9.1 `covariance_diagnostics.csv`

每个轴承一行：

```text
bearing,n,h_end,feature_set,condition_number,min_eigenvalue,max_eigenvalue,
offdiag_abs_mean,offdiag_abs_max,corr_rms_p2p,corr_kurt_crest
```

### 9.2 `model_comparison_by_bearing.csv`

每个轴承、每个模型一行：

```text
bearing,model,n,h_end,far_pct,spearman_health_ttf,alarm_idx,
alarm_life_pct,lead_min,roughness,diff_p95,ucl
```

### 9.3 `model_comparison_summary.csv`

每个模型一行：

```text
model,median_far_pct,median_spearman,mean_spearman,
median_alarm_life_pct,median_lead_min,num_valid_alarm,
num_good_spearman,num_too_early,num_too_late,overall_rank
```

### 9.4 图像

建议至少包含 4 类图：

1. 各模型 Spearman 跨轴承箱线图。
2. 各模型告警寿命占比分布。
3. Bearing1_1 上 M2/M3/M4 的健康曲线对比。
4. 完整协方差相关矩阵热力图。

---

## 10. 解释口径

最终结论应按以下口径输出：

```text
完整协方差矩阵是否有效：
  有效 / 弱有效需正则化 / 当前特征集下收益不足

有效原因：
  是否因为特征间存在稳定相关结构；
  是否因为完整协方差改善了单调性、告警时机或曲线稳定性。

工程建议：
  直接 full covariance；
  regularized covariance；
  diagonal covariance；
  或先做 PCA/特征筛选再 T2。
```

不建议只用单个轴承或单张曲线下结论。至少应以 6 个轴承的汇总指标为主，Bearing1_1 作为可视化解释案例。

---

## 11. 风险与注意事项

1. **协方差矩阵病态风险**：Bearing1_1 的健康段协方差特征值中存在很小值，说明特征相关性强，直接求逆可能放大噪声。必须报告条件数，并与正则化协方差对照。
2. **PRONOSTIA 退化形态不完全单调**：部分轴承是长期平稳后突变，Spearman 偏低不一定代表异常检测失败，需要结合告警提前量判断。
3. **健康窗口假设仍然影响结论**：必须做 5%/10%/20% 健康窗口敏感性检查。
4. **不要把温度融合结论混入本验证**：Step 4/5 是传感器融合和协变量处理问题，本方案只验证振动特征协方差结构。
5. **完整协方差不一定总是最优**：如果特征高度冗余且样本少，PCA+T2 或正则化协方差可能比原始 full covariance 更稳。

---

## 12. 推荐执行顺序

1. 先做 4 维水平振动特征的 M0-M5 消融。
2. 汇总 6 个轴承的指标，判断 M3/M4 是否优于 M2。
3. 若 M3 不稳定，检查条件数与特征相关矩阵。
4. 再做 5%/10%/20% 健康窗口敏感性。
5. 最后才考虑 8 维水平+垂直特征扩展。

本验证完成后，才能更有把握地决定后续工程版本使用：

```text
对角协方差 T2
完整协方差 T2
正则化协方差 T2
PCA + T2
```

