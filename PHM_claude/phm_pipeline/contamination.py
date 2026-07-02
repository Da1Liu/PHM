"""
污染检测 / 稳定性加权 (v1 仅留接口, 不实现).

设计意图 (落地文档 7.1): 新机磨合期样本会污染基线. 用稳定性加权(近邻距离)
自动给不稳定样本低权重, 用 IsolationForest 剔除退化/异常样本.

v1 不实现原因 (与用户讨论确定): 存量设备优先, 已磨合, 靠人工大修 reset 健康状态;
新机磨合污染暂不是主要矛盾. 留接口, 后续接入.
"""
from __future__ import annotations

import numpy as np


def stability_weights(X: np.ndarray, n_neighbors: int = 5, sigma: float = 1.0) -> np.ndarray:
    """TODO: 近邻稳定性加权. 不稳定的磨合期样本获得低权重.

    v1 返回均匀权重 (等价于不加权).
    """
    n = len(X)
    return np.ones(n) / max(n, 1)


def contamination_mask(X: np.ndarray, contamination: float = 0.05) -> np.ndarray:
    """TODO: IsolationForest 污染检测, 返回 True=保留 的布尔掩码.

    v1 全部保留 (不剔除).
    """
    return np.ones(len(X), dtype=bool)
