"""瘦采集器 -> phm_v2.telemetry 的参考写入器 (把"采集->落库"契约变成代码而非散文).

任意协议/语言的瘦采集器都按此行形状写 telemetry, PHM 用 PostgresSource 统一消费:
  telemetry(machine_id, signal_id, ts, value, feature, epoch, regime)
    - 低频标量轮询: 每个采样点一行, feature=NULL (原生读数), PostgresSource 现场 reduce;
    - 高频振动: 采集端就地算窗特征, 每特征一行, feature=rms/std/kurtosis/...

纯函数 (record_to_rows 等把 CollectionRecord 转成行) 与 DB 写入 (TelemetryWriter.insert)
分离, 便于离线测. 此模块是 Python 侧瘦采集器(如 NC-Link Collector)的落库出口, 也是
非 Python 采集器(C# NI / Node OPC UA)应遵循的**行格式范本**.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..datasource import CollectionRecord
from ..features import REDUCERS

TELEMETRY_COLS = ("machine_id", "signal_id", "ts", "value", "feature", "epoch", "regime")
Row = Tuple[str, int, datetime, float, Optional[str], int, Optional[str]]


def _ts(t0: float, i: int = 0, rate: float = 1.0) -> datetime:
    return datetime.fromtimestamp(float(t0) + i / max(rate, 1e-9), tz=timezone.utc)


def _split_feature(key: str, feats) -> Tuple[str, Optional[str]]:
    """'vib_gearbox_1_rms' -> ('vib_gearbox_1', 'rms'); 用已知 reducer 后缀切, 防 code 含下划线歧义."""
    for f in sorted(feats, key=len, reverse=True):
        if key.endswith("_" + f):
            return key[: -(len(f) + 1)], f
    return key, None


def scalar_rows(rec: CollectionRecord, signal_ids: Dict[str, int], machine_id: str,
                epoch: int = 1, regime: Optional[str] = None) -> List[Row]:
    """低频标量通道 + 混淆温: 每采样点一行 (feature=NULL). 缺 signal_id 的通道跳过."""
    rows: List[Row] = []

    def emit(name: str, series, rate: float):
        sid = signal_ids.get(name)
        if sid is None:
            return
        arr = np.asarray(series, dtype=float)
        for i, v in enumerate(arr):
            rows.append((machine_id, sid, _ts(rec.timestamp, i, rate), float(v), None, epoch, regime))

    for name, (series, rate) in rec.channels.items():
        emit(name, series, rate)
    for name, series in rec.temps.items():
        emit(name, series, 1.0)            # 温度通道按 1Hz 点序 (现场实际率由 signal.unit/采集器定)
    return rows


def precomputed_rows(rec: CollectionRecord, signal_ids: Dict[str, int], machine_id: str,
                     epoch: int = 1, regime: Optional[str] = None,
                     feature_names=None) -> List[Row]:
    """高频振动窗特征 (rec.precomputed 的 '{code}_{feature}') -> 每特征一行 (feature=该 reducer)."""
    feats = set(feature_names or REDUCERS.keys())
    ts = _ts(rec.timestamp)
    rows: List[Row] = []
    for key, v in rec.precomputed.items():
        code, feature = _split_feature(key, feats)
        sid = signal_ids.get(code)
        if sid is None:
            continue
        rows.append((machine_id, sid, ts, float(v), feature, epoch, regime))
    return rows


def record_to_rows(rec: CollectionRecord, signal_ids: Dict[str, int], machine_id: str,
                   epoch: int = 1, regime: Optional[str] = None) -> List[Row]:
    """一条 CollectionRecord -> 全部 telemetry 行 (标量原值 + 振动窗特征)."""
    return (scalar_rows(rec, signal_ids, machine_id, epoch, regime)
            + precomputed_rows(rec, signal_ids, machine_id, epoch, regime))


class TelemetryWriter:
    """把 telemetry 行批量写入 phm_v2 (惰性 psycopg2). DB 不可达时由调用方处理异常."""

    def __init__(self, conn_params: dict):
        self.conn_params = conn_params

    def insert(self, rows: List[Row]) -> int:
        if not rows:
            return 0
        import psycopg2
        from psycopg2.extras import execute_values
        conn = psycopg2.connect(**self.conn_params)
        try:
            cur = conn.cursor()
            execute_values(
                cur, f"INSERT INTO phm_v2.telemetry ({', '.join(TELEMETRY_COLS)}) VALUES %s", rows)
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def write_record(self, rec: CollectionRecord, signal_ids: Dict[str, int], machine_id: str,
                     epoch: int = 1, regime: Optional[str] = None) -> int:
        return self.insert(record_to_rows(rec, signal_ids, machine_id, epoch, regime))
