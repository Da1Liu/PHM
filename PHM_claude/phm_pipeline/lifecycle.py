"""
生命周期层: 冷启动 -> 过渡 -> 成熟 的渐进式健康度 (全新, 验证脚本里不存在).

三阶段 (落地文档 6.1):
- 阶段一 n<30 (工程先验期): 物理限 + CUSUM 相对漂移检测 (<warmup 条池子太小, 健康度中性).
- 阶段二 30<=n<mature (分位评分期): 各特征两侧分位带评分, 加权平均.
- 阶段三 n>=mature 且跨日>=14 (成熟期): PCA + T2 + SPE (BaselineModel).
成熟门槛起到 blend_hi 区间内阶段二/三健康度线性混合 (w3 由 0 升满), 避免切换跳变 (落地文档 6.2).

在线设定: 对每条新样本, 用"截至上一条"的池子拟合的模型打分 (不看未来),
再把该样本并入池子, 按 cadence 重训. 这是真机的真实时序, 也是自检要检验的对象.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .config import SystemConfig
from .model import BaselineModel
from .score import health_from_score


def stage_for(n: int, n_days: int, cfg: SystemConfig) -> int:
    """根据样本数与跨日天数决定阶段. 跨日/样本不足时不进成熟期 (落地文档 6.1).

    成熟期门槛 = max(stage2_max_n, 10*特征数) 且 跨日>=stage3_min_days,
    其中 n>=10p 经验规则由自检发现的小样本 FAR 失稳问题驱动加入.
    """
    if n < cfg.stage1_max_n:
        return 1
    if n < cfg.mature_min_n() or n_days < cfg.stage3_min_days:
        return 2
    return 3


# ---- 阶段一: CUSUM 相对漂移 ----
def cusum_health(z_dev: np.ndarray, k: float = 0.5, h: float = 5.0) -> float:
    """对一条样本的标准化偏差向量做单侧 CUSUM 截断式健康度.

    z_dev: 当前样本各特征相对基线的标准化偏差 (无累积历史时即瞬时偏差).
    简化为瞬时版本: 取最大绝对偏差, 超过 h 视为漂移. 返回 [0,1].
    """
    drift = float(np.max(np.abs(z_dev))) if len(z_dev) else 0.0
    excess = max(0.0, drift - k)
    return float(np.exp(-excess / max(h, 1e-6)))


# ---- 阶段二: 两侧分位带评分 ----
def percentile_band_score(x: np.ndarray, pool: np.ndarray,
                          weights: Optional[np.ndarray] = None) -> float:
    """各特征两侧分位带评分加权平均.

    带内 [P05,P95] 评分 1.0; 超出后按 (P95-P50) 为尺度线性降到 0 (两侧对称).
    比 .md 的单侧 P80->P95 更稳, 同时能抓特征值下降型退化 (如泄漏致流量下降).
    """
    p05 = np.quantile(pool, 0.05, axis=0)
    p50 = np.quantile(pool, 0.50, axis=0)
    p95 = np.quantile(pool, 0.95, axis=0)
    half = np.maximum(p95 - p50, p50 - p05) + 1e-12
    dev = np.maximum(x - p95, p05 - x)          # 超出带的距离 (带内为负)
    over = np.maximum(dev, 0.0) / half          # 归一化超出量
    s = np.clip(1.0 - over, 0.0, 1.0)
    if weights is None:
        return float(np.mean(s))
    w = weights / (weights.sum() + 1e-12)
    return float(np.sum(s * w))


@dataclass
class LifecycleResult:
    health: float
    stage: int
    score: float
    n: int
    n_days: int
    blended: bool = False
    info: Dict[str, object] = field(default_factory=dict)
    # 成熟期分解 (stage<3 或无模型时为 None), 供 diagnose 页
    t2: Optional[float] = None
    spe: Optional[float] = None
    ucl_t2: Optional[float] = None
    ucl_spe: Optional[float] = None
    contributions: Optional[List[dict]] = None


@dataclass
class LifecycleManager:
    """渐进式健康度引擎. 在线逐样本喂入, 自动选阶段/混合/重训."""

    cfg: SystemConfig
    refit_every: int = 10
    admit_max_score: float = 1.0   # 成熟期超过此分数的样本不并入基线 (防污染)

    pool: List[np.ndarray] = field(default_factory=list)
    days: List[int] = field(default_factory=list)
    model: Optional[BaselineModel] = None
    _last_fit_n: int = 0
    version: str = "v1"

    @property
    def n(self) -> int:
        return len(self.pool)

    @property
    def n_days(self) -> int:
        return len(set(self.days))

    def _ucl_method_for(self, n: int) -> str:
        """按样本量选 UCL 标定法. auto: 小样本用参数化(解析限稳), 大样本用经验分位(已收敛)."""
        m = getattr(self.cfg, "ucl_method", "empirical")
        if m == "auto":
            return "empirical" if n >= getattr(self.cfg, "empirical_min_n", 150) else "parametric"
        return m

    def _maybe_refit_stage3(self):
        """成熟期: 按 cadence 在当前池子上重训 BaselineModel.

        池子按时间 70/30 切分: 前段拟合 PCA, 后段(近期健康样本)样本外标定 UCL.
        样本外标定避免样本内 UCL 偏乐观导致在线 FAR 偏高 (自检发现).
        UCL 标定法由 cfg.ucl_method 决定 (parametric/auto 可在更低样本量稳定进成熟期).
        """
        if self.n < self.cfg.mature_min_n():
            return
        if self.model is None or (self.n - self._last_fit_n) >= self.refit_every:
            X = np.array(self.pool)
            fit_n = int(round(0.7 * len(X)))
            X_fit, X_calib = X[:fit_n], X[fit_n:]
            self.model = BaselineModel(
                feature_names=self.cfg.feature_names,
                keep=self.cfg.pca_keep, ucl_quantile=self.cfg.ucl_quantile,
                ucl_method=self._ucl_method_for(self.n),
            ).fit(X_fit, X_calib)
            self._last_fit_n = self.n

    def _health_stage2(self, x: np.ndarray) -> float:
        pool = np.array(self.pool) if self.pool else x[None, :]
        return percentile_band_score(x, pool)

    def _health_stage3(self, x: np.ndarray):
        ex = self.model.explain(x)
        return float(health_from_score(ex["score"], self.cfg.health_alpha)), ex

    def observe(self, x: np.ndarray, day: int) -> LifecycleResult:
        """喂入一条新样本 (已是最终特征向量), 返回健康度判定. 不看未来."""
        x = np.asarray(x, dtype=float)
        n_before, days_before = self.n, self.n_days
        stage = stage_for(n_before, days_before, self.cfg)

        score = 0.0
        blended = False
        ex = None                          # 成熟期分解 (有模型评分时填)

        if n_before == 0:
            health = 1.0  # 第一条无参照, 默认健康
        elif stage == 1:
            if n_before < self.cfg.stage1_warmup:
                # 池子太小 (std≈0): 估不出基线散布, 给中性健康度, 不被噪声拖到 0.
                # 否则 n=1 时 sd=1e-12 -> |z|~1e12 -> cusum_health=0, 新机头几条假性红灯.
                health = 1.0
            else:
                pool = np.array(self.pool)
                mu = pool.mean(axis=0)
                sd = pool.std(axis=0) + 1e-12
                health = cusum_health((x - mu) / sd)
        else:
            # 阶段二健康度 (始终可算)
            h2 = self._health_stage2(x)
            # 成熟期模型 (若样本/跨日满足且已拟合)
            h3 = None
            if n_before >= self.cfg.mature_min_n() and days_before >= self.cfg.stage3_min_days \
                    and self.model is not None:
                h3, ex = self._health_stage3(x)
                score = ex["score"]
            if h3 is None:
                health = h2
            else:
                # 混合过渡: 从"模型激活点"(成熟门槛)起 w3 由 0 线性升满, 避免切换跳变.
                # 锚 lo=max(blend_lo, mature_min_n): blend_lo 早于成熟门槛时(液压 50<140),
                # h3 在门槛前根本不存在, 若仍从 blend_lo 起算则首条 stage3 样本 w3 已≈0.6 ->
                # 健康度台阶 (实测 0.94->0.47); 从门槛起算则首条 w3=0, h2 连续过渡. (P3 修复)
                lo = max(self.cfg.blend_lo, self.cfg.mature_min_n())
                hi = max(self.cfg.blend_hi, lo + 1)
                w3 = np.clip((n_before - lo) / (hi - lo), 0.0, 1.0)
                health = (1 - w3) * h2 + w3 * h3
                blended = 0.0 < w3 < 1.0

        # 基线准入门控: 成熟期一旦该样本明显超限 (score>admit_max_score),
        # 不并入基线池, 避免退化样本污染基线导致"基线随故障漂移、健康度虚假回升".
        # 这是 v1 的轻量污染控制; 完整稳定性加权/IsolationForest 见 contamination.py (留接口).
        admitted = True
        if self.model is not None and score > self.admit_max_score:
            admitted = False

        if admitted:
            self.pool.append(x)
            self.days.append(day)
            self._maybe_refit_stage3()

        return LifecycleResult(
            health=float(np.clip(health, 0.0, 1.0)),
            stage=stage, score=float(score),
            n=n_before, n_days=days_before, blended=blended,
            info={"version": self.version, "admitted": admitted},
            t2=(ex["t2"] if ex else None), spe=(ex["spe"] if ex else None),
            ucl_t2=(ex["ucl_t2"] if ex else None), ucl_spe=(ex["ucl_spe"] if ex else None),
            contributions=(ex["contributions"] if ex else None),
        )
