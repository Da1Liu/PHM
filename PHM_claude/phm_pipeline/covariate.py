"""
协变量层: 温度处理.

两种角色 (与用户讨论确定, 证据见 step5 vs step9):
- 混淆温度 (环境/电机/暖机热态): 线性回归剔除, 残差进模型.
  step5 证明对单通道检测可显著提升预警提前量 (194->407min).
- 耦合温度 (轴承温度/油温, 参与故障物理耦合): 保留进健康向量.
  step9 证明这样才能抓到温度-关系异常.

本模块只负责"混淆温度回归剔除". 耦合温度由 features 直接纳入向量, 不经此处.

复用: step5_temp_regression_residual_t2.py:73-84 residualize_by_temperature.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class TempResidualizer:
    """对每个特征拟合 feature ~ intercept + 温度协变量, 用残差替代原值.

    回归系数只在基线训练集上拟合 (避免把退化泄漏进温度模型),
    再对所有样本应用. 残差加回基线均值, 保持量纲与符号可比 (同 step5).
    """

    coef: np.ndarray = None          # (1+n_temp, n_feat)
    baseline_center: np.ndarray = None  # (n_feat,)
    n_temp: int = 0

    def fit(self, X_train: np.ndarray, T_train: np.ndarray) -> "TempResidualizer":
        """X_train: (n, p) 特征; T_train: (n, q) 混淆温度协变量."""
        T_train = np.atleast_2d(T_train)
        if T_train.shape[0] != X_train.shape[0]:
            T_train = T_train.T
        A = np.column_stack([np.ones(len(T_train)), T_train])
        coef, *_ = np.linalg.lstsq(A, X_train, rcond=None)
        self.coef = coef
        self.baseline_center = X_train.mean(axis=0)
        self.n_temp = T_train.shape[1]
        return self

    def transform(self, X: np.ndarray, T: np.ndarray) -> np.ndarray:
        if self.coef is None:
            return X
        T = np.atleast_2d(T)
        if T.shape[0] != X.shape[0]:
            T = T.T
        A = np.column_stack([np.ones(len(T)), T])
        residual = X - A @ self.coef
        residual += self.baseline_center
        return residual

    def to_dict(self) -> dict:
        return {
            "coef": None if self.coef is None else self.coef.tolist(),
            "baseline_center": None if self.baseline_center is None
            else self.baseline_center.tolist(),
            "n_temp": self.n_temp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TempResidualizer":
        obj = cls()
        obj.coef = None if d["coef"] is None else np.array(d["coef"])
        obj.baseline_center = (None if d["baseline_center"] is None
                               else np.array(d["baseline_center"]))
        obj.n_temp = d.get("n_temp", 0)
        return obj
