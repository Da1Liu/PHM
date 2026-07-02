"""
评分层: 健康度映射 + 特征贡献分解.

健康度: health = exp(-alpha * score / ucl), score = max(T2/UCL_T2, SPE/UCL_SPE).
  score=ucl 时 health≈exp(-alpha); alpha=3 -> UCL 对应 health≈0.05 (落地设计).

特征贡献分解 (新, 验证脚本里不存在):
- T2 贡献: 把 T2 = z^T (W Λ⁻¹ Wᵀ) z 按特征拆开, contrib_i = z_i·(M z)_i, 求和=T2.
- SPE 贡献: 残差空间分量平方 residual_i², 求和=SPE, 直接定位偏离通道.
告警时输出 top 贡献特征, 供解释 (落地文档 8.2).
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from .model import BaselineModel


def health_from_score(score, alpha: float = 3.0, ucl: float = 1.0):
    """score(标量或数组) -> 健康度 [0,1]."""
    score = np.asarray(score, dtype=float)
    return np.exp(-alpha * score / (ucl + 1e-12))


def t2_contributions(model: BaselineModel, X: np.ndarray) -> np.ndarray:
    """各特征对 T2 的贡献. 返回 (n, p), 每行求和 = 该样本 T2."""
    Z = model.standardize(X)                       # (n, p)
    M = model.W @ np.diag(1.0 / model.lam) @ model.W.T   # (p, p)
    MZ = Z @ M                                      # (n, p)
    return Z * MZ                                   # 逐元素, 行和 = z^T M z = T2


def spe_contributions(model: BaselineModel, X: np.ndarray) -> np.ndarray:
    """各特征对 SPE 的贡献 (残差分量平方). 返回 (n, p), 行和 = SPE."""
    Z = model.standardize(X)
    proj = Z @ model.W
    residual = Z - proj @ model.W.T
    return residual ** 2


def explain(model: BaselineModel, x: np.ndarray, top: int = 3) -> Dict[str, object]:
    """对单条样本输出 T2/SPE 及主要贡献特征, 供告警解释."""
    x = np.atleast_2d(x)
    t2, spe = model.t2_spe(x)
    t2c = t2_contributions(model, x)[0]
    spec = spe_contributions(model, x)[0]
    names = model.feature_names

    def top_feats(contrib):
        order = np.argsort(contrib)[::-1][:top]
        return [(names[i], float(contrib[i])) for i in order]

    score = float(max(t2[0] / model.ucl_t2, spe[0] / model.ucl_spe))
    dominant = "T2" if (t2[0] / model.ucl_t2) >= (spe[0] / model.ucl_spe) else "SPE"
    return {
        "t2": float(t2[0]),
        "spe": float(spe[0]),
        "t2_ucl": model.ucl_t2,
        "spe_ucl": model.ucl_spe,
        "score": score,
        "health": float(health_from_score(score)),
        "dominant_space": dominant,
        "top_t2": top_feats(t2c),
        "top_spe": top_feats(spec),
    }
