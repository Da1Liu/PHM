# 多传感器协方差矩阵健康基线验证方案

> 目标：验证“多种传感器数据共同组成一个健康状态向量，并通过协方差矩阵建立正常状态分布”的技术路线是否可行。
>
> 纠偏说明：前一版 `mahalanobis_covariance_validation_plan.md` 验证的是“同一振动信号提取出的多个特征之间的协方差”。这不等价于你要的主轴系统场景。你真正关心的是：振动、温度、电流、功率等不同传感器之间的联合关系是否可以形成健康基线。本方案以此为核心重新设计。

---

## 1. 要验证的核心问题

主轴系统的目标形态可以抽象为：

```text
x_t = [
  vibration_feature_1,
  vibration_feature_2,
  temperature_feature,
  current_feature,
  power_feature,
  ...
]
```

健康基线不是单独看每个变量是否越界，而是学习健康状态下这些变量的联合分布：

```text
x ~ N(mu_healthy, Sigma_healthy)
```

异常分数：

```text
D2(t) = (x_t - mu)^T Sigma^-1 (x_t - mu)
```

本方案验证的问题是：

1. 多传感器联合向量是否能形成稳定健康基线。
2. 完整协方差矩阵是否比单变量阈值、对角协方差更能识别异常。
3. 协方差矩阵是否能捕捉“单个传感器未明显越界，但传感器之间关系异常”的情况。
4. 在小样本/多变量条件下，是否需要正则化协方差或 PCA/Hotelling T2。

---

## 2. 推荐验证数据集

### 2.1 首选：UCI Hydraulic System Condition Monitoring

本地已具备数据：

```text
data/uci_hydraulic/
```

选择理由：

- 多传感器类型完整，适合验证“多源信号联合建模”：
  - 压力：PS1-PS6
  - 流量：FS1-FS2
  - 温度：TS1-TS4
  - 振动：VS1
  - 电机功率：EPS1
  - 效率虚拟量：SE/CE/CP
- 每个 cycle 是标准化 60 秒受控循环，类似“标准采集程序”。
- 有部件状态标签，可验证健康基线对异常状态的区分能力。
- 数据集本身就是多变量状态监测数据，足以证明技术路线可行性。

### 2.2 与主轴系统的映射关系

| 主轴/机床目标变量 | UCI Hydraulic 对应变量 | 用途 |
|---|---|---|
| 振动 | VS1 | 机械动态状态 |
| 温度 | TS1-TS4 | 热状态/油温 |
| 电流/功率 | EPS1 | 驱动负载代理 |
| 压力/载荷代理 | PS1-PS6 | 系统负载和执行状态 |
| 流量/效率代理 | FS1-FS2, SE | 系统效率和泄漏/损耗 |

该映射不要求行业完全一致。它验证的是“多源传感器协方差健康基线”这个数学和工程路线，而不是验证真实主轴物理机理。

---

## 3. 数据集限制与处理原则

### 3.1 重要限制

UCI Hydraulic 中，四个部件同时处于最优状态且 `stable=0` 的样本只有 10 条：

```text
cooler=100, valve=100, pump=0, accumulator=130, stable=0 -> 10 samples
```

这不足以训练多维协方差健康基线。因此不能直接把“全系统绝对健康”作为唯一训练集。

### 3.2 处理原则

本方案采用“受控子任务”的方式验证技术路线：

```text
固定一部分工况/部件状态，把目标部件的正常状态作为相对健康基线，
再检测目标部件状态变化导致的多传感器联合分布偏移。
```

这相当于真实机床中的：

```text
固定标准采集程序 + 固定工况层级 + 在当前设备状态下建立相对健康基线
```

### 3.3 推荐子任务

优先使用泵泄漏检测子任务：

```text
筛选条件：
  cooler = 100
  stable = 0

目标标签：
  pump leakage:
    0 = no leakage
    1 = weak leakage
    2 = severe leakage
```

样本规模：

```text
pump=0:   169 samples
pump=1/2: 320 samples
```

选择理由：

- 健康样本量足够训练协方差矩阵。
- 温度变化被 cooler=100 大致约束，减少冷却器故障对温度的强混淆。
- 泵泄漏会同时影响压力、流量、功率、效率等多源变量，适合验证联合协方差。

备选子任务：

```text
固定 pump=0, stable=0，验证 cooler 状态变化导致的多传感器联合偏移。
```

备选任务适合验证温度/冷却相关传感器的联合异常，但更容易被温度本身主导。

---

## 4. 多传感器特征设计

### 4.1 第一版最小多传感器向量

每个 60 秒 cycle 提取一条样本向量。第一版建议控制在 10-14 维，避免协方差矩阵过度病态。

| 特征名 | 来源 | 物理含义 |
|---|---|---|
| `ps1_mean` | PS1 | 主压力水平 |
| `ps1_std` | PS1 | 压力波动 |
| `ps2_mean` | PS2 | 辅助压力水平 |
| `fs1_mean` | FS1 | 主流量 |
| `fs2_mean` | FS2 | 辅助流量 |
| `eps1_mean` | EPS1 | 电机功率/负载 |
| `vs1_mean` | VS1 | 振动平均水平 |
| `vs1_std` | VS1 | 振动波动 |
| `ts1_mean` | TS1 | 油温/温度状态 |
| `ts2_mean` | TS2 | 温度分布 |
| `se_mean` | SE | 效率因子 |
| `q_over_p` | FS1 / PS1 | 流量压力比 |

说明：

- 这里不把温度只当协变量剔除，而是先把它作为健康状态向量的一部分纳入协方差矩阵。
- 这是为了验证你关心的“振动、温度、电流/功率共同形成健康基线”。
- 后续再单独做“温度作为协变量剔除”的对照，判断温度应该进模型还是只做补偿。

### 4.2 稳态窗口

每个 cycle 前 20% 可能包含建立过程，后 10% 可能包含结束扰动。第一版取中间 70%：

```text
steady segment = cycle[20% : 90%]
```

对 100 Hz、10 Hz、1 Hz 信号分别按比例截取，不做重采样。

### 4.3 可选增强特征

第二阶段可加入：

```text
ps1_p95, ps1_p05, eps1_std, fs1_std, ts1_slope, vs1_max, ce_mean, cp_mean
```

但第一阶段不建议过多扩维。健康样本只有 169 条，维度过高会使协方差估计不稳。

---

## 5. 基线切分

在推荐子任务 `cooler=100 AND stable=0` 下：

```text
healthy_pool = pump=0 samples
fault_pool   = pump=1 or pump=2 samples
```

健康样本切分：

```text
baseline_train       healthy_pool 前 60%
baseline_calibration healthy_pool 后 40%
online_test          baseline_calibration + fault_pool
```

用途：

- `baseline_train`：估计 `mu`、`Sigma`、标准化参数、正则化参数。
- `baseline_calibration`：校准 UCL 阈值，估计健康段误报。
- `online_test`：模拟上线后的健康样本 + 异常样本。

注意：

- `fault_pool` 不参与任何训练或阈值估计。
- 如果要模拟时间序列，可按 `pump=0 -> pump=1 -> pump=2` 拼接成伪退化序列，但结论必须标注为“标签排序序列”，不是真实自然退化时间。

---

## 6. 对照模型

### M0：单变量阈值基线

每个传感器特征独立标准化，异常分数取最大 z-score：

```text
score = max(abs(z_i))
```

作用：代表传统单通道阈值方法。

### M1：对角协方差马氏距离

忽略传感器之间的相关性：

```text
D2_diag = (x - mu)^T diag(Sigma)^-1 (x - mu)
```

作用：代表“多传感器各自独立评分后求和”。

### M2：完整协方差马氏距离

使用完整协方差矩阵：

```text
D2_full = (x - mu)^T Sigma^-1 (x - mu)
```

作用：验证多传感器联合关系是否有效。

### M3：正则化协方差马氏距离

推荐作为工程候选：

```text
Sigma_reg = (1 - lambda) * Sigma + lambda * I
lambda ∈ {0.01, 0.05, 0.10}
```

作用：降低小样本、多变量、强相关导致的矩阵病态风险。

### M4：PCA + Hotelling T2

在健康样本上 PCA，保留 90% 或 95% 方差：

```text
z = W^T x
T2 = z^T Lambda^-1 z
```

作用：用低维主成分表达多传感器共变模式，适合变量较多、相关性强的情况。

### M5：PCA + T2 + SPE

同时监测主成分空间和残差空间：

```text
score = max(T2 / UCL_T2, SPE / UCL_SPE)
```

作用：避免只看主成分空间时漏掉局部传感器异常。

### M6：破坏相关结构对照

对健康训练集每个特征列独立 shuffle，保留边际分布但破坏跨传感器相关结构，再估计协方差。

作用：证明完整协方差的收益来自真实传感器相关结构，而不是数值偶然。

---

## 7. 核心评价指标

### 7.1 异常检测能力

| 指标 | 含义 | 期望 |
|---|---|---|
| `FAR_calibration` | 健康校准集误报率 | < 5% |
| `AUC_fault_vs_healthy` | 健康 vs 泄漏样本区分能力 | 越高越好 |
| `Spearman(score, pump_level)` | 分数与泄漏等级单调性 | 正相关，越高越好 |
| `mean_score_by_level` | pump=0/1/2 平均分 | 逐级升高 |
| `first_alarm_level` | 首次告警出现在 pump=1 还是 pump=2 | 越早越敏感，但不能高误报 |

### 7.2 协方差矩阵有效性

| 指标 | 含义 | 期望 |
|---|---|---|
| `offdiag_abs_mean` | 跨传感器相关强度 | 非零且可解释 |
| `condition_number` | 协方差病态程度 | 过高则倾向正则化/PCA |
| `full_vs_diag_auc_delta` | 完整协方差相对对角协方差提升 | > 0 为正收益 |
| `full_vs_shuffle_delta` | 真实相关结构相对 shuffle 的提升 | > 0 证明相关结构有效 |
| `top_contribution_features` | 主要贡献变量 | 应落在压力/流量/功率/效率等相关变量 |

### 7.3 多传感器关系异常验证

额外设计一个“关系异常”测试：

1. 从健康校准集中抽样。
2. 保留每个特征的健康边际范围。
3. 人为打乱某些传感器之间的配对关系，例如 `EPS1` 与 `FS1/PS1`。
4. 比较 M1 对角协方差与 M2/M3 完整协方差对这些样本的检出率。

预期：

```text
单变量阈值/对角协方差检出率低；
完整协方差/正则化协方差检出率高。
```

这一步最贴近主轴场景：例如振动、温度、电流都在各自正常范围内，但组合关系不再符合健康主轴的正常耦合。

---

## 8. 输出文件设计

建议新增方案和脚本：

```text
multisensor_covariance_baseline_validation_plan.md
step7_multisensor_covariance_baseline.py
outputs/step7_multisensor_covariance/
```

输出文件：

```text
features_multisensor.csv
covariance_diagnostics.csv
model_comparison.csv
model_summary.csv
relationship_anomaly_test.csv
multisensor_health_scores.png
covariance_correlation_heatmap.png
feature_contributions.png
```

### `features_multisensor.csv`

```text
cycle,cooler,valve,pump,accumulator,stable,
ps1_mean,ps1_std,ps2_mean,fs1_mean,fs2_mean,
eps1_mean,vs1_mean,vs1_std,ts1_mean,ts2_mean,se_mean,q_over_p
```

### `covariance_diagnostics.csv`

```text
model,feature_count,train_count,condition_number,
min_eigenvalue,max_eigenvalue,offdiag_abs_mean,offdiag_abs_max
```

### `model_summary.csv`

```text
model,FAR_calibration,AUC_fault_vs_healthy,
Spearman_score_pump,mean_score_pump0,mean_score_pump1,mean_score_pump2,
full_vs_diag_delta,full_vs_shuffle_delta,recommended
```

---

## 9. 关键停点

### 停点 1：特征分布自检

完成内容：

- 提取多传感器特征。
- 输出各特征在 pump=0/1/2 下的分布。
- 输出健康训练集相关矩阵。

需要判断：

```text
这些传感器变量是否确实存在跨传感器相关性？
异常等级是否在多个传感器上有可见偏移？
```

建议通过条件：

- `offdiag_abs_mean` 不接近 0。
- 至少压力/流量/功率/效率中的若干变量随 pump 泄漏变化。

### 停点 2：协方差模型对照

完成内容：

- M0-M6 模型对照。
- 输出 AUC、Spearman、FAR、分等级均值。

需要判断：

```text
完整协方差/正则化协方差是否优于单变量和对角协方差？
若不优，是否 PCA+T2/SPE 更稳定？
```

建议：

- 如果 `M3 正则化协方差` 或 `M4/M5 PCA` 优于对角模型，继续关系异常测试。
- 如果对角模型已经足够好且完整协方差无提升，说明该数据集的异常主要表现为单变量幅值偏移，需换数据集或引入人工关系异常验证。

### 停点 3：关系异常测试

完成内容：

- 构造边际正常但跨传感器关系被破坏的样本。
- 比较单变量/对角/完整协方差检出率。

需要判断：

```text
协方差矩阵是否确实捕捉到了多传感器耦合关系？
```

这是验证你需求的关键点。即使真实 fault 检测中对角模型表现不错，只要关系异常测试中完整协方差明显更强，也能证明技术路线对主轴多传感器健康基线有价值。

---

## 10. 通过判据

### 强通过

满足：

1. 健康训练集存在明确跨传感器相关结构。
2. 正则化完整协方差或 PCA+T2/SPE 的 AUC/Spearman 优于对角协方差。
3. 健康校准集 FAR < 5%。
4. pump=0/1/2 平均异常分数逐级升高。
5. 关系异常测试中，完整协方差检出率显著高于单变量/对角模型。

### 弱通过

满足：

1. 真实 fault 检测上完整协方差与对角模型接近。
2. 但关系异常测试中完整协方差明显优于对角模型。
3. 协方差矩阵需要正则化或 PCA 才稳定。

结论：

```text
多传感器协方差健康基线可行，但工程实现应使用正则化协方差或 PCA+T2/SPE。
```

### 不通过

出现：

1. 跨传感器相关结构很弱。
2. 完整协方差、正则化协方差、PCA 均不优于对角模型。
3. 关系异常测试也没有优势。

结论：

```text
该数据集不能证明多传感器协方差路线有效，需要更换数据集。
```

---

## 11. 如果 UCI Hydraulic 不足，备选数据集

如果 UCI 的异常主要由单变量幅值偏移驱动，建议换或补充以下数据：

### 11.1 NASA C-MAPSS

优点：

- 多传感器航空发动机数据，温度、压力、转速、流量等变量齐全。
- 有 run-to-failure 序列，适合健康基线和退化趋势。
- 多变量关系强，适合验证协方差/PCA/T2。

缺点：

- 与机床行业更远。
- 工况变量需要单独处理，否则工况会主导协方差。

适合验证：

```text
多传感器协方差健康基线 + 工况分层/归一化
```

### 11.2 Tennessee Eastman Process

优点：

- 经典多变量过程监控数据。
- 正常工况和多种故障清晰。
- SPC、PCA、Hotelling T2 的标准验证场景。

缺点：

- 化工过程，不是机械设备。

适合验证：

```text
多变量协方差异常检测的数学可行性
```

### 11.3 NASA Milling 或其他刀具磨损数据

优点：

- 更接近制造场景。
- 常包含力、振动、声发射、电流等多传感器。

缺点：

- 切削工况强混淆，不适合第一轮验证健康基线。

适合后续验证：

```text
制造场景下多传感器健康基线迁移
```

---

## 12. 推荐执行顺序

第一轮建议仍用本地 UCI Hydraulic，因为数据已在目录中，成本最低：

1. 提取多传感器 cycle-level 特征。
2. 使用 `cooler=100 AND stable=0`，以 pump 泄漏为目标。
3. 先做特征分布和相关矩阵自检，停下确认。
4. 再做 M0-M6 对照，停下确认。
5. 最后做关系异常测试，验证协方差矩阵是否捕捉多传感器耦合。

如果第一轮结果显示真实 fault 检测被单变量主导，则不要急于否定路线，优先执行关系异常测试；如果关系异常测试仍无优势，再换 C-MAPSS 或 Tennessee Eastman。

---

## 13. 已执行阶段结论

### 13.1 停点 1：多传感器特征自检

已执行脚本：

```text
step7_multisensor_covariance_baseline.py
```

输出目录：

```text
outputs/step7_multisensor_covariance/
```

筛选子集：

```text
cooler=100 AND stable=0
pump=0: 169 samples
pump=1: 160 samples
pump=2: 160 samples
```

健康样本相关结构：

```text
feature_count = 14
offdiag_abs_mean = 0.331
offdiag_abs_max = 0.996
condition_number = 111806771.7
```

结论：

```text
多传感器相关结构明确存在，但原始 14 维完整协方差矩阵严重病态。
后续不应把裸 full covariance + pinv 作为工程候选，应优先考虑正则化协方差或 PCA + T2/SPE。
```

### 13.2 停点 2：真实 pump 泄漏模型对照

在全部 14 个特征上，真实 pump 泄漏任务过于容易：

```text
所有模型 AUC = 1.000
所有模型 Spearman(score, pump_level) = 0.924
所有模型 calibration FAR = 1.47%
```

结论：

```text
该结果能证明多传感器健康基线可检测异常，
但不能证明完整协方差优于单变量/对角协方差，
因为 q_over_p、fs1_mean、se_mean 等单变量已经极强可分。
```

### 13.3 强单变量剔除实验

已执行脚本：

```text
step8_multisensor_weak_feature_ablation.py
```

输出目录：

```text
outputs/step8_multisensor_weak_features/
```

单变量分离度最高的特征：

| feature | sep(pump0 vs pump2) |
|---|---:|
| q_over_p | 65.58 |
| fs1_mean | 61.10 |
| se_mean | 29.88 |
| ps3_mean | 12.03 |
| ps1_mean | 6.87 |
| ps2_mean | 6.19 |
| eps1_mean | 3.69 |

剔除 `sep > 10` 的强特征后：

| model | AUC | Spearman |
|---|---:|---:|
| PCA95 + T2 + SPE | 1.000 | 0.919 |
| regularized covariance, lambda=0.01 | 0.984 | 0.910 |
| regularized covariance, lambda=0.05 | 0.983 | 0.909 |
| full covariance + pinv | 0.978 | 0.907 |
| diagonal covariance | 0.747 | 0.777 |
| shuffled covariance | 0.708 | 0.753 |
| max abs z | 0.681 | 0.719 |

结论：

```text
去掉最强单变量特征后，多变量协方差/PCA 仍显著优于单变量、对角协方差和破坏相关结构对照。
这支持“多传感器协方差健康基线”技术路线。
```

剔除 `sep > 3` 后，剩余变量基本不再包含 pump 泄漏信息：

```text
best AUC 约 0.256，Spearman 为负。
```

结论：

```text
协方差矩阵不能凭空创造信息；它只能利用传感器之间真实存在的联合结构。
```

### 13.4 关系异常测试

已执行脚本：

```text
step9_multisensor_relationship_anomaly.py
```

输出目录：

```text
outputs/step9_relationship_anomaly/
```

该测试使用剔除强单变量后的 10 个特征：

```text
ps1_mean, ps2_mean, eps1_mean, ps1_std, eps1_std,
vs1_mean, fs2_mean, vs1_std, ts1_mean, ts2_mean
```

构造“每个特征边际仍来自健康样本，但跨传感器配对关系被打乱”的伪异常。

代表性结果：

| scenario | 单变量 AUC | 对角协方差 AUC | 正则化/完整协方差 AUC | PCA+T2+SPE AUC |
|---|---:|---:|---:|---:|
| 全特征独立打乱 | 0.564 | 0.478 | 0.872-0.887 | 0.887 |
| 温度对打乱 | 0.555 | 0.474 | 0.835-0.850 | 0.874 |
| 压力对打乱 | 0.534 | 0.506 | 0.675-0.729 | 0.787 |
| 传感器块打乱 | 0.528 | 0.504 | 0.579-0.593 | 0.737 |
| 仅功率打乱 | 0.505 | 0.507 | 0.512-0.519 | 0.533 |

结论：

```text
单变量和对角协方差基本无法识别“边际正常但关系异常”的样本。
正则化/完整协方差和 PCA+T2+SPE 能识别压力、温度、全局关系破坏。
仅功率打乱检出弱，说明 EPS1 在该子集中的健康耦合关系不足，模型不会对所有配对扰动都敏感。
```

### 13.5 阶段性工程建议

当前证据支持以下路线：

```text
第一优先：PCA + T2 + SPE
第二优先：正则化协方差马氏距离
不推荐：裸 full covariance + pinv
不充分：单变量阈值 / 对角协方差
```

原因：

1. 真实故障检测中，PCA+T2+SPE 在剔除强单变量后仍保持最好表现。
2. 关系异常测试中，PCA+T2+SPE 对多种跨传感器关系破坏最稳。
3. 原始完整协方差矩阵病态严重，直接求逆有工程风险。
4. 对角协方差无法捕捉跨传感器耦合异常。

