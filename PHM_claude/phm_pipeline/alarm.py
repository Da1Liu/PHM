"""
告警层: 双层告警 + EWMA 平滑 + K 连续去抖.

双层 (与用户讨论确定):
- L1 物理限守卫: 单变量越界检查 (电机铭牌/轴承手册物理上下界).
  廉价, 抓 UCI 那种单通道明显越界的"易"故障.
- L2 模型告警: PCA+T2+SPE 综合分越 UCL. 抓早期/耦合/关系型退化.
两层并行, 任一触发即告警, 分别标注来源 (落地文档 8).

复用: step2 EWMA (81-88), first_consecutive_alarm (step7:172-178).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


def ewma(values: np.ndarray, lam: float = 0.15) -> np.ndarray:
    """指数加权移动平均. lam 越小越平滑 (落地文档 6.3)."""
    values = np.asarray(values, dtype=float)
    out = np.zeros(len(values))
    if len(values) == 0:
        return out
    out[0] = values[0]
    for t in range(1, len(values)):
        out[t] = lam * values[t] + (1 - lam) * out[t - 1]
    return out


def first_consecutive_alarm(values, threshold, k: int = 5) -> int:
    """连续 k 点超阈才告警, 返回连续段起点索引, 无则 -1. 复用 step2/step7."""
    run = 0
    arr = np.asarray(values, dtype=float)
    for i, above in enumerate(arr > threshold):
        run = run + 1 if above else 0
        if run >= k:
            return i - k + 1
    return -1


def physical_limit_violation(
    feature_values: Dict[str, float],
    limits: Dict[str, Tuple[float, float]],
) -> List[str]:
    """L1: 返回越界的特征名列表 (空=未越界)."""
    out = []
    for name, (lo, hi) in limits.items():
        v = feature_values.get(name)
        if v is None:
            continue
        if not (lo <= v <= hi):
            out.append(name)
    return out


@dataclass
class AlarmState:
    """在线告警状态机. 维护 EWMA 与连续超阈计数."""

    ucl_score: float = 1.0
    lam: float = 0.15
    k_consecutive: int = 5
    limits: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    _ewma_prev: Optional[float] = None
    _run: int = 0
    history: List[dict] = field(default_factory=list)

    def update(self, score: float, feature_values: Optional[Dict[str, float]] = None) -> dict:
        """喂入一条新样本分数, 返回本次告警判定."""
        if self._ewma_prev is None:
            ewma_v = score
        else:
            ewma_v = self.lam * score + (1 - self.lam) * self._ewma_prev
        self._ewma_prev = ewma_v

        above = ewma_v > self.ucl_score
        self._run = self._run + 1 if above else 0
        l2_alarm = self._run >= self.k_consecutive

        l1_violations = (physical_limit_violation(feature_values, self.limits)
                         if (feature_values and self.limits) else [])
        l1_alarm = len(l1_violations) > 0

        result = {
            "score": float(score),
            "ewma": float(ewma_v),
            "ucl_score": self.ucl_score,
            "l2_alarm": bool(l2_alarm),
            "l1_alarm": bool(l1_alarm),
            "l1_violations": l1_violations,
            "alarm": bool(l1_alarm or l2_alarm),
            "source": ("L1+L2" if (l1_alarm and l2_alarm)
                       else "L1" if l1_alarm
                       else "L2" if l2_alarm else ""),
        }
        self.history.append(result)
        return result
