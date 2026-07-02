# ADR-001 成熟期算法锁定 PCA + T² + SPE

状态: 已采纳 (step7-9 验证)

## Decision
成熟期异常检测用 PCA(标准化+SVD) + Hotelling **T²** + **SPE**(Q 统计量, Jackson-Mudholkar)。
`score = max(T²/UCL_T², SPE/UCL_SPE)`; `health = exp(-3·score)`。**SPE 不可省。**

## Reason
- step8/9 实测: 单变量阈值 / 对角协方差对**关系型异常** AUC≈0.5 (形同失明); 只有带 SPE 的模型 AUC≈1.0, 能看到"各通道边际都正常、但耦合关系变了"。
- 裸 full-covariance + pinv 病态 (cond# 1.1e8) 排除; 正则化协方差马氏距离次之, 作兜底 (`RegularizedCovModel`)。

## Consequence
- SPE 是本方案相对传统单变量阈值 / ISO 限 / 包络谱的**唯一差异化价值**。现场 4 振动测点 RMS 相关 0.98–1.00, 正是 SPE 用武之地。
- **T² 是地板** (已严格强于单通道阈值), **SPE 是上限**: 退化为**共模**(各通道一起放大)时 SPE 加成有限, T² 兜底。
- 若 SPE 落地不佳的替补阶梯 (物理残差 > 轴承包络 > 阶次跟踪 > 非线性) 见 memory `spe-value-and-fallback-ladder`。

参见 [[ADR-008]] (UCL 标定/门槛)。
