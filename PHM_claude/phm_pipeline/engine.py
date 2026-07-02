"""C2 健康引擎: 多 regime 在线消费 (稳态门控 + 工况分层 + 混淆温残差化 + 生命周期).

INTEGRATION_PLAN §2 "第2层 健康引擎" 的产品骨架. 把任意 DataSource
(FileSource/PostgresSource/RealSource) 来的 CollectionRecord 流, 逐条变成 HealthResult:

  record -> [工况标注] -> [稳态门控] -> 特征向量 -> [混淆温残差化(冻结)]
         -> 该 regime 的 LifecycleManager (评分 + 基线准入) -> HealthResult

要点:
- **每个 regime 一套独立基线** (LifecycleManager, 懒创建). regime 键 = cfg.baseline_by
  在 condition 上取值 (rpm_bin 等, 由 RegimeLabeler 写入).
- **热态等混淆温作协变量残差化, 不分层** (covariate.TempResidualizer). 按其"基线集拟合
  后冻结"语义: 某 regime 攒够 cfg.confounder_fit_n 条后, 用前 fit_n 条拟合并冻结, 然后
  重建该 regime 的 manager (用残差化后的历史回放), 使池子全程一致. confounder_temps 为空
  (液压 / 主轴未接温度前) 则全程不残差化 -> 退化为单 manager 循环, 复现 run_selfcheck.
- **非稳态样本不准入基线**, 但若该 regime 已有模型则照常打分供显示 (admitted=False).

骨架边界 (待真实数据/决策再实): 稳态门控阈值、rpm 档边界、低频原始序列窗聚合、
残差化冻结后是否随大修 reset 重拟合. 见 INTEGRATION_PLAN 阶段 C2/E.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .config import SystemConfig
from .covariate import TempResidualizer
from .datasource import CollectionRecord
from .features import extract_vector
from .lifecycle import LifecycleManager, LifecycleResult, stage_for
from .regime import RegimeLabeler, SteadyGate
from .score import health_from_score


@dataclass
class HealthResult:
    regime: Tuple                 # baseline_key, 该样本所属基线
    steady: bool                  # 是否判为稳态
    admitted: bool                # 是否并入该 regime 基线池
    health: float
    stage: int
    score: float
    n: int                        # 该 regime 当前样本数
    n_days: int
    reasons: List[str] = field(default_factory=list)
    info: Dict[str, object] = field(default_factory=dict)
    # 成熟期分解 (stage<3 或无模型时为 None), 供 diagnose 页
    t2: Optional[float] = None
    spe: Optional[float] = None
    ucl_t2: Optional[float] = None
    ucl_spe: Optional[float] = None
    contributions: Optional[List[dict]] = None


@dataclass
class _RegimeState:
    manager: LifecycleManager
    raw_X: List[np.ndarray] = field(default_factory=list)   # 残差化前历史 (供冻结时重建)
    raw_T: List[Optional[np.ndarray]] = field(default_factory=list)
    days: List[int] = field(default_factory=list)
    residualizer: Optional[TempResidualizer] = None
    resid_frozen: bool = False


@dataclass
class HealthEngine:
    """多 regime 在线健康引擎. 逐条喂 CollectionRecord, 不看未来."""

    cfg: SystemConfig
    refit_every: int = 10

    labeler: RegimeLabeler = field(init=False)
    gate: SteadyGate = field(init=False)
    states: Dict[Tuple, _RegimeState] = field(default_factory=dict)

    def __post_init__(self):
        self.labeler = RegimeLabeler(bins=dict(getattr(self.cfg, "regime_bins", {})))
        self.gate = SteadyGate(
            channels=tuple(getattr(self.cfg, "steady_channels", ())),
            max_cv=getattr(self.cfg, "steady_max_cv", 0.05),
            max_slope_frac=getattr(self.cfg, "steady_max_slope_frac", 0.10),
        )

    # ---- 内部 ----
    def _state(self, key: Tuple) -> _RegimeState:
        st = self.states.get(key)
        if st is None:
            st = _RegimeState(manager=LifecycleManager(cfg=self.cfg, refit_every=self.refit_every))
            self.states[key] = st
        return st

    def _use_confounder(self) -> bool:
        return bool(self.cfg.confounder_temps)

    def _confounder_vec(self, rec: CollectionRecord) -> Optional[np.ndarray]:
        if not self._use_confounder():
            return None
        vals = []
        for t in self.cfg.confounder_temps:
            arr = rec.temps.get(t)
            if arr is None:
                return None                   # 缺协变量 -> 本条不残差化
            vals.append(float(np.mean(np.asarray(arr, dtype=float))))
        return np.array(vals, dtype=float)

    def _fit_freeze_rebuild(self, st: _RegimeState) -> LifecycleResult:
        """攒够样本: 用前 fit_n 条拟合并冻结残差化器, 重建 manager (残差化历史回放)."""
        fit_n = int(self.cfg.confounder_fit_n)
        X = np.array(st.raw_X)
        T = np.array(st.raw_T)
        st.residualizer = TempResidualizer().fit(X[:fit_n], T[:fit_n])
        st.resid_frozen = True
        Xr = st.residualizer.transform(X, T)
        st.manager = LifecycleManager(cfg=self.cfg, refit_every=self.refit_every)
        last = None
        for xr, d in zip(Xr, st.days):
            last = st.manager.observe(xr, d)
        return last

    def _score_only(self, st: _RegimeState, vec: np.ndarray):
        """非稳态: 不准入. 有模型则打分+分解供显示, 否则给中性健康度.

        返回 (health, stage, score, ex); ex 为 model.explain 结果或 None.
        """
        m = st.manager
        if m.model is not None:
            x = vec
            if st.resid_frozen and st.residualizer is not None:
                pass  # 残差化需协变量, 非稳态路径从简用原始向量打分 (仅供显示)
            ex = m.model.explain(x.reshape(1, -1))
            score = ex["score"]
            health = float(health_from_score(score, self.cfg.health_alpha))
        else:
            score, health, ex = 0.0, 1.0, None
        return health, stage_for(m.n, m.n_days, self.cfg), score, ex

    # ---- 主入口 ----
    def observe(self, rec: CollectionRecord, day: int) -> HealthResult:
        rec = self.labeler.label(rec)
        steady = self.gate.is_steady(rec)
        vec, _names = extract_vector(rec, self.cfg.feature_specs, self.cfg.derived)
        key = rec.baseline_key(self.cfg.baseline_by)
        st = self._state(key)

        if not steady.ok:
            health, stage, score, ex = self._score_only(st, vec)
            return HealthResult(regime=key, steady=False, admitted=False, health=health,
                                stage=stage, score=score, n=st.manager.n,
                                n_days=st.manager.n_days, reasons=steady.reasons,
                                info={"engine": "score_only"},
                                t2=(ex["t2"] if ex else None), spe=(ex["spe"] if ex else None),
                                ucl_t2=(ex["ucl_t2"] if ex else None),
                                ucl_spe=(ex["ucl_spe"] if ex else None),
                                contributions=(ex["contributions"] if ex else None))

        tvec = self._confounder_vec(rec)
        st.raw_X.append(vec)
        st.raw_T.append(tvec)
        st.days.append(day)

        if self._use_confounder() and tvec is not None and not st.resid_frozen \
                and len(st.raw_X) >= self.cfg.confounder_fit_n:
            res = self._fit_freeze_rebuild(st)      # 一次性: 冻结残差化 + 重建一致池子
        else:
            xr = vec
            if st.resid_frozen and tvec is not None and st.residualizer is not None:
                xr = st.residualizer.transform(vec.reshape(1, -1), tvec.reshape(1, -1))[0]
            res = st.manager.observe(xr, day)

        return HealthResult(regime=key, steady=True, admitted=bool(res.info.get("admitted", True)),
                            health=res.health, stage=res.stage, score=res.score,
                            n=res.n, n_days=res.n_days, reasons=steady.reasons,
                            info={"engine": "lifecycle", "resid_frozen": st.resid_frozen},
                            t2=res.t2, spe=res.spe, ucl_t2=res.ucl_t2, ucl_spe=res.ucl_spe,
                            contributions=res.contributions)

    @property
    def regimes(self) -> List[Tuple]:
        return list(self.states.keys())
