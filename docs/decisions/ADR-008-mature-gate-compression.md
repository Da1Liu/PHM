# ADR-008 参数化 UCL 压成熟期门槛 (主轴 ~5p)

状态: 已采纳 (2026-06-23, 液压代理验证)

## Decision
- `BaselineModel.ucl_method` 可选: **样本外经验分位**(默认, 锚点用) / **参数化**(T²~F + SPE~Jackson-Mudholkar, 小样本稳) / **auto**。
- 主轴 config 压缩档: 门槛 ~**5p** (而非 10p), `ucl_method=auto`, 按 rpm 分层, 特征裁剪 **p20→12** (砍共线 std/p2p)。

## Reason
- 新机出厂前**无长积累时间**, 10p 门槛 (主轴 ~140 样本) 装不进安装验收/跑合窗口。
- 液压代理验证 (`_integration_probe/time_to_maturity_experiment.py`): 10p(140)→5p(70), 进成熟期 **46→23 天减半**, 去抖 **FAR 仍 0%**、无跳变; 锚点/smoke/selfcheck 全绿。

## Consequence
- 首台主轴早期成熟期压到 ~**2.5–5 周**, 装得进安装验收/跑合窗口。
- 参数化限是为"压门槛"服务; **默认仍用样本外经验分位** (做外部锚点更稳)。
- 阶段阈值/UCL法随 config 可调 (`lifecycle.py` 接 `cfg.ucl_method`)。

参见 [[ADR-001]] (T²/SPE 本体)。
