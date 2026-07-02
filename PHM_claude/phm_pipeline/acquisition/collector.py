"""
采集器: 按映射轮询一个采集窗口, 组装成一条 CollectionRecord.

一个"采集窗口"= 以 interval_ms 为周期轮询 n_points 次, 每路寄存器得到一段序列.
序列采样率 = 1000/interval_ms Hz (寄存器轮询通常 ~10Hz, 故只适合标量遥测类特征,
高频振动 RMS/峭度需要 kHz 波形, 本协议版本拿不到).

不阻塞主线程: 由 server 在后台线程里调用, 通过 progress_cb 回传实时值, stop_flag 中断.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

import numpy as np

from ..datasource import CollectionRecord
from .channel_map import ChannelMapping, apply_formula


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _agg_condition(series: List[object], how: str):
    """把一路工况寄存器的窗口序列聚成单个标签值."""
    if not series:
        return None
    if how == "mean":
        arr = np.array([_to_float(v) for v in series], dtype=float)
        return float(np.nanmean(arr))
    if how == "mode":
        vals, counts = np.unique([str(v) for v in series], return_counts=True)
        return vals[int(np.argmax(counts))]
    return series[-1]  # last


class Collector:
    """把 NclinkClient + ChannelMapping 组合成"采一窗 -> 一条 record"."""

    def __init__(self, client, mapping: ChannelMapping):
        self.client = client
        self.mapping = mapping

    def collect_window(
        self,
        condition_overrides: Optional[Dict[str, object]] = None,
        progress_cb: Optional[Callable[[int, int, Dict[str, float]], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
    ) -> CollectionRecord:
        m = self.mapping
        keys = m.poll_keys()
        n = m.n_points
        interval = m.interval_ms / 1000.0

        # 每个 entry 一条原始序列 (按 entry 顺序; 不同 entry 可共享同一 key).
        raw: List[List[object]] = [[] for _ in m.entries]
        actual = 0
        t_start = time.time()

        for i in range(n):
            if stop_flag is not None and stop_flag():
                break
            t0 = time.time()
            r = self.client.get_value(keys)
            vmap = r.as_map()
            scope: Dict[str, float] = {}
            for ei, e in enumerate(m.entries):
                v = vmap.get(e.key())
                raw[ei].append(v)
                scope[e.phm_name] = _to_float(v)
            actual += 1
            if progress_cb is not None:
                progress_cb(i + 1, n, dict(scope))
            # 按周期补眠 (扣除请求耗时), 与 app.py 的节奏一致.
            if i < n - 1:
                dt = interval - (time.time() - t0)
                if dt > 0:
                    time.sleep(dt)

        # ---- 应用公式, 拆角色, 组装 record ----
        # 逐 entry 生成最终序列; 公式 entry 用同一时刻各 entry 原始值做 scope.
        per_entry_series: List[np.ndarray] = []
        for ei, e in enumerate(m.entries):
            if e.formula.strip():
                vals = []
                for t in range(actual):
                    scope_t = {ee.phm_name: _to_float(raw[eei][t])
                               for eei, ee in enumerate(m.entries)}
                    vals.append(apply_formula(e.formula, scope_t))
                per_entry_series.append(np.array(vals, dtype=float))
            else:
                per_entry_series.append(
                    np.array([_to_float(v) for v in raw[ei]], dtype=float))

        channels: Dict[str, tuple] = {}
        temps: Dict[str, np.ndarray] = {}
        condition: Dict[str, object] = {
            "system": m.system, "program_id": m.program_id,
            **m.static_condition,
        }
        rate = m.rate_hz
        for ei, e in enumerate(m.entries):
            if e.role == "channel":
                channels[e.phm_name] = (per_entry_series[ei], rate)
            elif e.role == "confounder_temp":
                temps[e.phm_name] = per_entry_series[ei]
            elif e.role == "condition":
                condition[e.phm_name] = _agg_condition(raw[ei], e.condition_agg)
        if condition_overrides:
            condition.update(condition_overrides)

        return CollectionRecord(
            timestamp=t_start,
            condition=condition,
            channels=channels,
            temps=temps,
            meta={"n_points": actual, "requested": n,
                  "interval_ms": m.interval_ms, "rate_hz": rate,
                  "duration_s": round(time.time() - t_start, 2)},
        )
