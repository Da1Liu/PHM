"""
特征层: 一条 CollectionRecord -> 一条标量特征向量.

逐通道在稳态段上做 reducer (mean/std/rms/kurtosis/...), 再加派生特征 (q_over_p 等).
特征集由 config 的 FeatureSpec 列表驱动, 不同系统配置不同向量.

复用: step1 extract_features (RMS/峭度/峰峰), step7 reduce_sensor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .datasource import CollectionRecord
from .segment import steady_segment


# ---- 标量 reducer (在已截好的段上计算) ----
def _rms(x):
    return float(np.sqrt(np.mean(x ** 2)))


def _kurtosis(x):
    mu = np.mean(x)
    sd = np.std(x) + 1e-12
    return float(np.mean(((x - mu) / sd) ** 4))


def _crest(x):
    r = _rms(x)
    return float(np.max(np.abs(x)) / (r + 1e-12))


def _p2p(x):
    return float(np.max(x) - np.min(x))


REDUCERS: Dict[str, Callable[[np.ndarray], float]] = {
    "mean": lambda x: float(np.mean(x)),
    "std": lambda x: float(np.std(x)),
    "min": lambda x: float(np.min(x)),
    "max": lambda x: float(np.max(x)),
    "p95": lambda x: float(np.quantile(x, 0.95)),
    "p05": lambda x: float(np.quantile(x, 0.05)),
    "rms": _rms,
    "kurtosis": _kurtosis,
    "crest": _crest,
    "p2p": _p2p,
    "slope": lambda x: float(np.polyfit(np.arange(len(x)), x, 1)[0]) if len(x) > 1 else 0.0,
}


@dataclass
class FeatureSpec:
    """单个特征定义: 在 channel 的稳态段上做 reducer, 命名为 name."""

    channel: str
    name: str
    reducer: str
    seg_start: float = 0.20
    seg_end: float = 0.90


# 派生特征: name -> 由已算出的标量特征字典计算
DerivedFn = Callable[[Dict[str, float]], float]


def _segment_for(rec: CollectionRecord, spec: FeatureSpec) -> np.ndarray:
    arr, _rate = rec.channels[spec.channel]
    return steady_segment(arr, spec.seg_start, spec.seg_end)


def extract_vector(
    rec: CollectionRecord,
    specs: List[FeatureSpec],
    derived: Optional[Dict[str, DerivedFn]] = None,
) -> Tuple[np.ndarray, List[str]]:
    """提取一条特征向量. 返回 (values, names), 顺序 = specs 顺序 + derived 顺序."""
    feats: Dict[str, float] = {}
    for spec in specs:
        # 高频振动: 采集端已算好窗特征 (无原始波形可 reduce), 命中则直接用.
        if spec.name in rec.precomputed:
            feats[spec.name] = float(rec.precomputed[spec.name])
        else:
            seg = _segment_for(rec, spec)
            feats[spec.name] = REDUCERS[spec.reducer](seg)
    names = [s.name for s in specs]
    if derived:
        for dname, fn in derived.items():
            feats[dname] = float(fn(feats))
            names.append(dname)
    values = np.array([feats[n] for n in names], dtype=float)
    return values, names


def extract_temps(
    rec: CollectionRecord,
    temp_reducers: Tuple[str, ...] = ("mean",),
) -> Tuple[np.ndarray, List[str]]:
    """从温度通道提取协变量标量 (默认每通道取均值)."""
    vals, names = [], []
    for tname, arr in rec.temps.items():
        for red in temp_reducers:
            vals.append(REDUCERS[red](np.asarray(arr, dtype=float)))
            names.append(f"{tname}_{red}")
    return np.array(vals, dtype=float), names


# 常用派生特征
def q_over_p(flow_key: str = "fs1_mean", pressure_key: str = "ps1_mean") -> DerivedFn:
    """流量压力比 Q/P: 工况无关的泵容积效率代理 (落地文档 5.3)."""
    return lambda f: f[flow_key] / (f[pressure_key] + 1e-12)
