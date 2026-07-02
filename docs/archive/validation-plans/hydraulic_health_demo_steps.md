# 液压系统健康基线验证 Demo Step 方案

> 目标：先用液压系统完成第一版可验证 demo，验证“标准采集数据 -> 特征提取 -> 温度补偿 -> 基线建立 -> 异常评分 -> 趋势告警 -> 贡献解释”的完整闭环。
> 范围：第一阶段只做异常检测，不做故障定位、不做 RUL 预测、不做热误差建模。

---

## 1. Demo 边界

### 1.1 第一版只验证液压系统

第一版 demo 只覆盖液压系统，原因是：

- UCI Hydraulic System Condition Monitoring 数据集的信号类型与方案中的液压采集体系最匹配。
- 压力、流量、温度信号可直接映射到方案中的液压特征。
- 不需要先解决机床进给轴的往复段截断和伺服电流同步问题，验证成本最低。

### 1.2 Demo 证明什么

本 demo 应证明：

- 液压类受控循环数据可以被转换为健康基线样本。
- 温度协变量回归可以降低油温变化对健康分数的干扰。
- 分位数评分适合冷启动阶段。
- PCA + Hotelling T2 + SPE 适合成熟基线阶段。
- EWMA 可以把单点异常转换成趋势告警。
- 特征贡献可以解释异常主要来自哪些液压特征。

### 1.3 Demo 不证明什么

本 demo 不直接证明：

- 真实重型机床现场的长期误报率。
- 所有机床液压系统都能共用同一数值基线。
- 健康度等于相对于出厂新机的绝对健康状态。
- 能定位具体液压故障部件。

---

## 2. 数据选择

### 2.1 数据集

首选数据集：

```text
UCI Hydraulic System Condition Monitoring
```

使用信号：

- 压力信号：用于压力均值、压力标准差、压力建立时间。
- 流量信号：用于 Q/P。
- 温度信号：油温作为协变量。
- 标签：优先选择 pump 或 valve degradation 标签作为退化等级。

### 2.2 样本语义

每个液压循环样本统一转换为一条 demo 样本：

```text
sample_id
sequence_index
degradation_label
pressure_features
flow_features
oil_temperature
health_score
anomaly_score
algorithm_stage
confidence_level
```

### 2.3 时间序列构造

UCI 数据不是严格的真实连续退化时序，因此 demo 中需要明确声明“模拟时序”：

```text
健康等级最优样本 -> 轻微退化样本 -> 严重退化样本 -> 失效样本
```

同一等级内部按原始样本顺序或固定随机种子排序。所有实验必须固定随机种子，保证结果可复现。

---

## 3. 特征设计

第一版只做 4 个液压健康特征。

| 特征 | 异常方向 | 说明 |
|------|----------|------|
| 稳态压力均值 | low_bad | 泄漏、泵效率下降或阀异常时可能下降 |
| 稳态压力标准差 | high_bad | 压力波动增强代表稳定性变差 |
| Q/P | high_bad | 同等压力需要更多流量，代表内泄漏或效率下降 |
| 压力建立时间 | high_bad | 建压变慢代表泵或阀响应能力下降 |

协变量：

| 协变量 | 用途 |
|--------|------|
| 油温 | 只用于回归去除温度影响，不进入健康度模型 |

### 3.1 稳态段选择

若数据已按循环切片，稳态段可先使用固定比例截断：

```text
丢弃前 20% 建压段
丢弃后 10% 结束段
中间 70% 作为稳态段
```

后续如果需要增强，可改为根据压力曲线斜率自动识别稳态段。

### 3.2 压力建立时间

压力建立时间定义为：

```text
压力从起始压力上升到稳态压力 90% 所需的时间
```

如果某条样本无法达到 90% 稳态压力，应标记为质检异常或使用最大窗口长度作为惩罚值。

---

## 4. 算法修正

### 4.1 特征方向配置

分位数评分必须支持异常方向，不能默认所有特征越大越坏。

```python
feature_direction = {
    "pressure_mean": "low_bad",
    "pressure_std": "high_bad",
    "q_over_p": "high_bad",
    "pressure_rise_time": "high_bad",
}
```

评分规则：

- `high_bad`：高于高分位数扣分。
- `low_bad`：低于低分位数扣分。
- `two_sided_bad`：偏离中位数两侧都扣分。

### 4.2 温度补偿

基线期对每个健康特征单独拟合：

```text
feature = beta0 + beta1 * oil_temperature + residual
```

后续建模使用残差：

```text
feature_residual = feature_raw - predicted_temperature_effect
```

注意：

- 只用可信健康基线样本训练温度回归。
- 油温覆盖范围不足时，不启用温度回归或降低其权重。
- demo 中必须输出“有温度补偿”和“无温度补偿”的对比结果。

### 4.3 成熟期算法

成熟期不只使用 Hotelling T2，还需要同时计算 SPE/Q 统计量。

```text
T2：主成分空间内的异常
SPE：PCA 残差空间内的异常
```

综合异常分数建议：

```text
score = max(T2 / T2_UCL, SPE / SPE_UCL)
```

健康度映射：

```text
health = exp(-alpha * score)
alpha = 1.0 或 1.5，demo 中可调参对比
```

### 4.4 EWMA 方向

建议对异常分数做 EWMA，而不是只对 health 做 EWMA：

```text
ewma_score_t = lambda * score_t + (1 - lambda) * ewma_score_{t-1}
```

告警条件：

```text
ewma_score > ewma_threshold
```

其中 `lambda` 对比 0.1、0.15、0.2 三组。

---

## 5. 验证 Step

### Step 1：准备数据加载器

输入：

```text
UCI Hydraulic 原始数据目录
```

输出：

```text
samples.parquet 或 samples.csv
```

每条样本包含：

- 压力时间序列。
- 流量时间序列。
- 油温。
- 退化标签。
- 样本顺序编号。

完成标准：

- 能稳定读取全量数据。
- 能按退化标签筛选健康样本和退化样本。
- 能生成固定顺序的模拟时间序列。

### Step 2：实现液压特征提取

输入：

```text
单条液压循环样本
```

输出：

```text
pressure_mean
pressure_std
q_over_p
pressure_rise_time
oil_temperature
```

完成标准：

- 每条有效样本都能生成 4 个健康特征和 1 个协变量。
- 异常样本有质检标记。
- 输出特征分布图，确认无明显计算错误。

### Step 3：建立基线切分

建议切分：

```text
baseline_train：健康等级最优样本前 60%
baseline_calibration：健康等级最优样本后 40%
online_test：剩余健康样本 + 退化样本
```

完成标准：

- 温度回归、分位数、PCA 只在 `baseline_train` 上拟合。
- 阈值只用 `baseline_calibration` 校准。
- `online_test` 不参与任何训练和阈值估计。

### Step 4：温度补偿消融

跑两套 pipeline：

```text
A：raw features -> model
B：temperature residual features -> model
```

完成标准：

- 输出两套健康度曲线。
- 输出两套基线段误报率。
- 输出油温与各特征的相关系数变化。

### Step 5：实现阶段二分位数评分

输入：

```text
baseline_train 特征
online_test 特征
feature_direction 配置
```

输出：

```text
percentile_health
feature_scores
feature_contributions
```

完成标准：

- 支持 `high_bad` 和 `low_bad`。
- 健康样本平均健康度高于退化样本。
- 输出单特征贡献排序。

### Step 6：实现阶段三 PCA + T2 + SPE

输入：

```text
baseline_train 残差特征
baseline_calibration 残差特征
online_test 残差特征
```

输出：

```text
T2
T2_UCL
SPE
SPE_UCL
score
health
feature_contributions
```

完成标准：

- PCA 保留 90% 或 95% 方差，参数可配置。
- T2_UCL 和 SPE_UCL 来自 calibration 分位数。
- 退化等级越严重，score 整体越高。

### Step 7：实现 EWMA 趋势告警

输入：

```text
online_test 的 score 时间序列
```

输出：

```text
ewma_score
alarm_flag
first_alarm_index
```

完成标准：

- 对比 lambda = 0.1、0.15、0.2。
- 输出首次告警位置。
- 输出基线段误报率。

### Step 8：模拟渐进式冷启动

模拟样本逐步积累：

```text
n < 30：工程阈值 / CUSUM 占位
30 <= n < 100：分位数评分
n >= 100 且跨批次满足：PCA + T2 + SPE
```

完成标准：

- 输出每个样本使用的算法阶段。
- 输出阶段切换时的健康度连续性。
- 若健康度跳变明显，需要加入混合过渡。

### Step 9：评价指标

至少输出：

| 指标 | 目的 |
|------|------|
| baseline false alarm rate | 验证正常段误报 |
| degradation label vs score Spearman | 验证退化等级单调性 |
| mean health by degradation level | 验证健康度区分能力 |
| first alarm index | 验证趋势告警时机 |
| raw vs temperature residual comparison | 验证温度补偿价值 |
| percentile vs T2/SPE comparison | 验证成熟期算法收益 |

### Step 10：可视化交付

最小可视化包括：

- 健康度时间序列。
- 异常分数与阈值线。
- EWMA 异常趋势曲线。
- 各退化等级的健康度箱线图。
- 特征贡献条形图。
- 温度补偿前后对比图。

---

## 6. 推荐实现结构

建议先做成 Python 脚本或 notebook，后续再封装成服务。

```text
hydraulic_demo/
  README.md
  config.yaml
  data_loader.py
  feature_extractor.py
  temperature_compensation.py
  scoring_percentile.py
  scoring_pca_t2_spe.py
  ewma.py
  evaluation.py
  visualize.py
  run_demo.py
```

第一版命令：

```bash
python hydraulic_demo/run_demo.py --data-dir ./data/uci_hydraulic --out-dir ./outputs/hydraulic_demo
```

输出目录：

```text
outputs/hydraulic_demo/
  features.csv
  scores.csv
  metrics.json
  health_curve.png
  ewma_curve.png
  contribution_bar.png
  temperature_ablation.png
```

---

## 7. 通过标准

第一版 demo 通过标准如下：

- 可以从原始数据一键生成特征、健康度、异常分数、EWMA 告警和图表。
- 健康等级最优样本的误报率可控，建议小于 5%。
- 退化等级与异常分数呈正相关，Spearman 相关系数为正且显著。
- 严重退化/失效等级的平均健康度明显低于健康等级。
- 温度补偿版本不劣于未补偿版本，最好能降低健康段波动。
- 分位数评分和 T2/SPE 的结果都能解释，且成熟期 T2/SPE 不明显劣于分位数。

---

## 8. 下一步实现顺序

建议按以下顺序实现，不并行拉太多模块：

1. 数据加载器和特征提取。
2. 基线切分和温度补偿。
3. 分位数评分。
4. PCA + T2 + SPE。
5. EWMA 和评价指标。
6. 图表和 README。

第一轮实现完成后，再决定是否接入进给系统数据。

