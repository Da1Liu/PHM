"""
分段层: 从一条采集记录的原始序列里截出用于特征提取的有效段.

- steady_segment: 稳态窗口 (取中间比例段), 复用 step7 steady_slice.
- constant_velocity_segment: 进给匀速段截断 (电流跃变法, 不依赖坐标),
  见落地文档 4.2. 进给系统用; 液压 v1 走 steady_segment.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np


def steady_slice(n: int, start: float = 0.20, end: float = 0.90) -> slice:
    """稳态窗口切片. 复用 step7_multisensor_covariance_baseline.py:50-53.

    前 start 可能含建立过程, 后 (1-end) 可能含结束扰动, 取中间段.
    """
    a = int(round(start * n))
    b = int(round(end * n))
    return slice(a, max(a + 1, b))


def steady_segment(x: np.ndarray, start: float = 0.20, end: float = 0.90) -> np.ndarray:
    return x[steady_slice(len(x), start, end)]


def constant_velocity_segment(
    current: np.ndarray,
    rise_frac: float = 0.5,
    keep_margin: int = 0,
) -> Tuple[int, int]:
    """进给匀速段截断 (新, 电流跃变法, 不读坐标).

    思路 (落地文档 4.2): 电流从静止到运动有跃升(加速段),
    从运动到静止有下降(减速段); 跃升结束到下降开始之间 = 匀速段.

    实现: 以电流幅值跨过 (静止 + rise_frac*(运动-静止)) 阈值的首次/末次位置
    作为匀速段边界的近似. 返回 [lo, hi) 索引.

    注意: 真实伺服电流上能否干净切出, 取决于采样率与加减速时间常数,
    建议用第一批真机数据专门验证 (见与用户讨论结论).
    """
    x = np.abs(np.asarray(current, dtype=float))
    if len(x) < 4:
        return 0, len(x)
    lo_level = np.quantile(x, 0.05)
    hi_level = np.quantile(x, 0.95)
    thr = lo_level + rise_frac * (hi_level - lo_level)
    moving = np.where(x > thr)[0]
    if len(moving) < 2:
        return 0, len(x)
    lo = moving[0] + keep_margin
    hi = moving[-1] + 1 - keep_margin
    if hi - lo < 2:
        return int(moving[0]), int(moving[-1] + 1)
    return int(lo), int(hi)
