"""C2 工况层: 稳态门控 + regime 工况标注 (集中 Python, 跨源).

设计 (INTEGRATION_PLAN §2 "第2层"): 采集器只管写原始读数, 稳态判定/工况标注上移
到统一 Python 层, 因为 regime 是跨源逻辑 (工况来自标量通道, 要按时间戳给振动打标).

- 稳态门控: 现场振动高度非平稳 (RMS 0.5g->25g 含瞬态), 只有稳态窗能进基线池;
  非稳态样本不准入基线 (但可照常对既有模型打分供显示, 由 engine 决定).
- regime 标注: 工况标量 (rpm/进给速度) 按配置边界分箱 -> regime 键; rpm 强非线性
  做分层键, 热态平滑做协变量 (不在此处, 见 covariate.py).

均为瘦逻辑, 阈值/边界由 SystemConfig 驱动; 缺省 (空通道/空 bins) 即不门控/不分箱,
现有单基线配置 (液压) 行为不变.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .datasource import CollectionRecord
from .segment import steady_segment


@dataclass
class SteadyResult:
    ok: bool
    reasons: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class SteadyGate:
    """判定一条采集记录是否落在稳态工作点.

    依据按可得性降级:
      1. 原始标量通道在稳态窗内的变异系数 CV 与归一化漂移 (工况是否恒定);
      2. 采集端预算的平稳性特征 (precomputed 里的 '<ch>_cv', 高频振动无原始波形时用);
      3. 都不可得 -> 通过但标 'unjudged' (不武断拒, 也不假装判过).
    """

    channels: Tuple[str, ...] = ()
    max_cv: float = 0.05
    max_slope_frac: float = 0.10
    seg_start: float = 0.20
    seg_end: float = 0.90

    def is_steady(self, rec: CollectionRecord) -> SteadyResult:
        if not self.channels:
            return SteadyResult(ok=True, reasons=["gate_disabled"])
        reasons: List[str] = []
        metrics: Dict[str, float] = {}
        ok = True
        judged = 0
        for ch in self.channels:
            if ch in rec.channels:
                seg = np.asarray(steady_segment(rec.channels[ch][0],
                                                self.seg_start, self.seg_end), dtype=float)
                if seg.size < 2:
                    reasons.append(f"{ch}_too_short"); ok = False; judged += 1; continue
                mu = float(np.mean(seg))
                cv = float(np.std(seg)) / (abs(mu) + 1e-12)
                slope = float(np.polyfit(np.arange(len(seg)), seg, 1)[0])
                slope_frac = abs(slope) * len(seg) / (abs(mu) + 1e-12)
                metrics[f"{ch}_cv"] = cv
                metrics[f"{ch}_slopefrac"] = slope_frac
                judged += 1
                if cv > self.max_cv:
                    reasons.append(f"{ch}_cv_high"); ok = False
                if slope_frac > self.max_slope_frac:
                    reasons.append(f"{ch}_drift"); ok = False
            elif f"{ch}_cv" in rec.precomputed:
                cv = float(rec.precomputed[f"{ch}_cv"])
                metrics[f"{ch}_cv"] = cv
                judged += 1
                if cv > self.max_cv:
                    reasons.append(f"{ch}_cv_high"); ok = False
            else:
                reasons.append(f"{ch}_unjudged")
        if judged == 0:                       # 全无从判定: 通过但标记
            return SteadyResult(ok=True, reasons=reasons or ["unjudged"], metrics=metrics)
        return SteadyResult(ok=ok, reasons=reasons or ["steady"], metrics=metrics)


@dataclass
class RegimeLabeler:
    """把 condition 里的连续标量按配置边界分箱, 写回 condition['<src>_bin'].

    bins: 源键 -> 升序边界. 例 {"rpm": (1500, 3500, 6000)} -> 用 np.digitize 给档号 0..3.
    标量取值优先级: condition[src] > 该名通道稳态段均值 > precomputed[src].
    缺源键则不写 (该档为 None -> baseline_key 落到统一桶).
    """

    bins: Dict[str, Tuple[float, ...]] = field(default_factory=dict)

    def _scalar(self, rec: CollectionRecord, src: str) -> Optional[float]:
        v = rec.condition.get(src)
        if v is None and src in rec.channels:
            seg = steady_segment(rec.channels[src][0])
            v = float(np.mean(seg)) if len(seg) else None
        if v is None and src in rec.precomputed:
            v = rec.precomputed[src]
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    def label(self, rec: CollectionRecord) -> CollectionRecord:
        for src, edges in self.bins.items():
            v = self._scalar(rec, src)
            if v is None:
                continue
            rec.condition[f"{src}_bin"] = int(np.digitize([v], np.asarray(edges, float))[0])
        return rec
