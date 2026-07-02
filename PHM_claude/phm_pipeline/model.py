"""
建模层: PCA + Hotelling T2 + SPE 健康基线 (成熟期算法).

证据 (step7-9): 剔除强单变量后, PCA+T2+SPE 显著优于对角/单变量;
关系异常测试中只有带残差空间(SPE)的模型能看到"边际正常但关系异常".

复用:
- step7 pca_scores (SVD + T2 + SPE): step7:198-219
- step6 正则化协方差兜底: step6:90-92
- step2 UCL (经验分位数 + F 分布理论): step2:51-58

纯 numpy, SVD, pinv. 参数可序列化为 <5KB JSON, 供边缘侧推理.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


def _standardize_fit(X_train: np.ndarray):
    mu = X_train.mean(axis=0)
    sd = X_train.std(axis=0) + 1e-12
    return mu, sd


@dataclass
class BaselineModel:
    """PCA + T2 + SPE 健康基线模型. 在标准化空间内建模."""

    feature_names: List[str]
    keep: float = 0.95          # PCA 保留方差比例
    ucl_quantile: float = 0.99  # UCL 分位数 / 参数化限的置信水平
    ucl_method: str = "empirical"  # "empirical"=样本外经验分位(默认); "parametric"=T2~F + SPE~Jackson-Mudholkar

    # 拟合后参数
    mean: np.ndarray = None     # (p,) 标准化均值
    std: np.ndarray = None      # (p,) 标准化标准差
    W: np.ndarray = None        # (p, k) 主成分载荷
    lam: np.ndarray = None      # (k,) 各主成分方差
    eig_residual: np.ndarray = None  # (p-k,) 残差空间特征值, 供 SPE 参数化(J-M)限; 不序列化
    ucl_t2: float = None
    ucl_spe: float = None
    pca_explained: float = None
    n_train: int = 0

    def fit(self, X_train: np.ndarray, X_calib: np.ndarray = None) -> "BaselineModel":
        """拟合 PCA 并标定 UCL.

        ucl_method="empirical" (默认): UCL 由留出健康样本(X_calib)的分数分位标定,
        无 calib 则退回训练集内(样本内偏乐观). 样本外标定是控制 FAR 的关键, 但分位
        估计本身要样本量, 是 10p 成熟期门槛的主因(自检发现的小样本 FAR 失稳).
        ucl_method="parametric": T2 用 Hotelling F 分布限, SPE 用 Jackson-Mudholkar 限,
        由分布理论给出, 小样本即稳定 -> 不再靠分位估计, 可显著降低成熟期样本门槛.
        参数化退化(缺 scipy/残差空间为空)时按分量回退经验分位.
        """
        self.mean, self.std = _standardize_fit(X_train)
        Z = (X_train - self.mean) / self.std

        _, s, vt = np.linalg.svd(Z, full_matrices=False)
        eig = (s ** 2) / max(len(Z) - 1, 1)
        ratio = eig / (eig.sum() + 1e-12)
        k = int(np.searchsorted(np.cumsum(ratio), self.keep) + 1)
        k = max(1, min(k, Z.shape[1]))
        self.W = vt[:k].T
        self.lam = eig[:k] + 1e-12
        self.eig_residual = eig[k:]          # 残差空间特征值 (供 SPE 参数化限)
        self.pca_explained = float(ratio[:k].sum())
        self.n_train = len(X_train)

        ucl_t2_p = ucl_spe_p = None
        if self.ucl_method == "parametric":
            res = self._ucl_parametric()
            if res is not None:
                ucl_t2_p, ucl_spe_p = res
        # 经验分位 (默认路径, 或参数化按分量退化时回退)
        if ucl_t2_p is None or ucl_spe_p is None:
            if X_calib is not None and len(X_calib) >= 5:
                t2_c, spe_c = self.t2_spe(X_calib)
            else:
                t2_c, spe_c = self._t2_spe(Z)
        self.ucl_t2 = float(ucl_t2_p if ucl_t2_p is not None
                            else np.quantile(t2_c, self.ucl_quantile) + 1e-12)
        self.ucl_spe = float(ucl_spe_p if ucl_spe_p is not None
                             else np.quantile(spe_c, self.ucl_quantile) + 1e-12)
        return self

    def _ucl_parametric(self):
        """参数化控制限: T2~Hotelling F 分布, SPE~Jackson-Mudholkar.

        二者均由 PCA 结构(k, n, 残差特征值)解析给出, 不依赖样本分位估计,
        故小样本即稳定. 返回 (ucl_t2, ucl_spe); 某分量无法计算时该分量为 None,
        由调用方回退经验分位. 仅 fit 期用 scipy; 序列化后只剩标量, 推理仍纯 numpy.
        """
        try:
            from scipy.stats import f as _f, norm as _norm
        except ImportError:
            return None
        n = max(int(self.n_train), 2)
        k = int(self.W.shape[1])
        q = float(self.ucl_quantile)

        # T2: 新观测的 Hotelling 控制限 = k(n-1)(n+1)/(n(n-k)) * F_{q;k,n-k}
        if n > k:
            f_q = float(_f.ppf(q, k, n - k))
            ucl_t2 = k * (n - 1) * (n + 1) / (n * (n - k)) * f_q
        else:
            ucl_t2 = None

        # SPE: Jackson-Mudholkar, theta_i = sum(残差特征值^i)
        ev = np.asarray(self.eig_residual, dtype=float)
        ev = ev[ev > 1e-12]
        if ev.size == 0:
            ucl_spe = None
        else:
            th1, th2, th3 = float(ev.sum()), float((ev ** 2).sum()), float((ev ** 3).sum())
            if th1 <= 1e-18 or th2 <= 1e-18:
                ucl_spe = None
            else:
                h0 = 1.0 - (2.0 * th1 * th3) / (3.0 * th2 * th2)
                h0 = float(np.clip(h0, 1e-3, 1.0))
                ca = float(_norm.ppf(q))
                term = (ca * np.sqrt(2.0 * th2 * h0 * h0) / th1
                        + 1.0 + th2 * h0 * (h0 - 1.0) / (th1 * th1))
                ucl_spe = th1 * (term ** (1.0 / h0)) if term > 0 else None
        return ucl_t2, ucl_spe

    def _t2_spe(self, Z: np.ndarray):
        proj = Z @ self.W
        t2 = np.sum((proj ** 2) / self.lam, axis=1)
        residual = Z - proj @ self.W.T
        spe = np.sum(residual ** 2, axis=1)
        return t2, spe

    def standardize(self, X: np.ndarray) -> np.ndarray:
        return (np.atleast_2d(X) - self.mean) / self.std

    def t2_spe(self, X: np.ndarray):
        """返回 (T2, SPE), 均为 (n,) 数组."""
        return self._t2_spe(self.standardize(X))

    def score(self, X: np.ndarray) -> np.ndarray:
        """综合异常分 score = max(T2/UCL_T2, SPE/UCL_SPE). (n,)"""
        t2, spe = self.t2_spe(X)
        return np.maximum(t2 / self.ucl_t2, spe / self.ucl_spe)

    def explain(self, x: np.ndarray) -> dict:
        """单样本异常分解 (diagnose 页): T2/SPE/UCL/score + 逐特征贡献.

        贡献为精确可加分解 (各自之和分别等于 T2/SPE, 同 feature_names 顺序):
        - SPE 贡献_j = 残差_j^2 (该特征在残差空间的平方); 恒非负.
        - T2  贡献_j = z_j * (D z)_j, D = W diag(1/lam) W^T (完全分解 CDC),
          T2 = z^T D z = Σ_j z_j (D z)_j. D 半正定但单特征项含交叉项可为负
          (表示该特征实际在拉低 T2); 显示按 0 截断即可, 存储保留真值.
        """
        z = self.standardize(x)[0]                      # (p,)
        proj = self.W.T @ z                             # (k,) = z 在主成分上的得分
        t2 = float(np.sum((proj ** 2) / self.lam))
        residual = z - self.W @ proj                    # (p,) 残差空间
        spe = float(np.sum(residual ** 2))
        spe_contrib = residual ** 2                     # Σ = spe
        t2_contrib = z * (self.W @ (proj / self.lam))   # Σ = t2 (= z·Dz)
        contributions = [
            {"name": n, "t2": round(float(tc), 6), "spe": round(float(sc), 6)}
            for n, tc, sc in zip(self.feature_names, t2_contrib, spe_contrib)
        ]
        score = max(t2 / self.ucl_t2, spe / self.ucl_spe)
        return {"t2": t2, "spe": spe, "ucl_t2": float(self.ucl_t2),
                "ucl_spe": float(self.ucl_spe), "score": float(score),
                "contributions": contributions}

    def to_dict(self) -> dict:
        return {
            "feature_names": list(self.feature_names),
            "keep": self.keep,
            "ucl_quantile": self.ucl_quantile,
            "ucl_method": self.ucl_method,
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "W": self.W.tolist(),
            "lam": self.lam.tolist(),
            "ucl_t2": self.ucl_t2,
            "ucl_spe": self.ucl_spe,
            "pca_explained": self.pca_explained,
            "n_train": self.n_train,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BaselineModel":
        obj = cls(feature_names=d["feature_names"], keep=d["keep"],
                  ucl_quantile=d["ucl_quantile"],
                  ucl_method=d.get("ucl_method", "empirical"))
        obj.mean = np.array(d["mean"])
        obj.std = np.array(d["std"])
        obj.W = np.array(d["W"])
        obj.lam = np.array(d["lam"])
        obj.ucl_t2 = d["ucl_t2"]
        obj.ucl_spe = d["ucl_spe"]
        obj.pca_explained = d["pca_explained"]
        obj.n_train = d["n_train"]
        return obj


# ---- 工程兜底: 正则化协方差马氏距离 (step6:90-92) ----
@dataclass
class RegularizedCovModel:
    """正则化协方差马氏距离, 作为 PCA+T2+SPE 的第二优先兜底.

    Sigma_reg = (1-lam)*Sigma + lam*I, 降低小样本/强相关导致的病态风险.
    """

    feature_names: List[str]
    lam: float = 0.05
    ucl_quantile: float = 0.99

    mean: np.ndarray = None
    std: np.ndarray = None
    center: np.ndarray = None
    cov_inv: np.ndarray = None
    ucl: float = None

    def fit(self, X_train: np.ndarray) -> "RegularizedCovModel":
        self.mean, self.std = _standardize_fit(X_train)
        Z = (X_train - self.mean) / self.std
        self.center = Z.mean(axis=0)
        cov = np.cov(Z, rowvar=False)
        p = cov.shape[0]
        cov_reg = (1.0 - self.lam) * cov + self.lam * np.eye(p)
        self.cov_inv = np.linalg.pinv(cov_reg)
        d2 = self._d2(Z)
        self.ucl = float(np.quantile(d2, self.ucl_quantile) + 1e-12)
        return self

    def _d2(self, Z: np.ndarray) -> np.ndarray:
        d = Z - self.center
        return np.einsum("ij,jk,ik->i", d, self.cov_inv, d)

    def score(self, X: np.ndarray) -> np.ndarray:
        Z = (np.atleast_2d(X) - self.mean) / self.std
        return self._d2(Z) / self.ucl
