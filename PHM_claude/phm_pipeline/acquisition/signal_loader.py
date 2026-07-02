"""signal 维表 -> 采集映射 / signal_id 索引: 连接 phm_v2 与采集, 消除双真相源.

phm_v2.signal 是"哪台机床有哪些信号、什么协议、什么地址、什么角色"的**权威登记**.
本模块把它转成 acquisition 的 ChannelMapping (供 Collector 轮询), 使采集映射不再手填、
与 DB 维表一致. 纯函数 (signals_to_mapping/parse_address/entry_role) 与 DB 取数 (fetch_*)
分离, 便于离线单测.

角色映射 (signal 行 -> ChannelEntry.role):
  regime_role=TRUE                 -> condition       (转速/档位等工况分层键)
  temp_role='confound'             -> confounder_temp (混淆温, 回归剔除)
  temp_role='coupled'              -> channel         (耦合温, 进特征向量)
  signal_kind='bool'               -> condition       (液压 bool 状态位, 不进 PCA 向量)
  其余(current/speed/position/pressure/coupled温) -> channel
  is_high_freq=TRUE (振动)         -> **跳过** (由 NI/C# 采集器就地算特征直写 telemetry, 不轮询)
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .channel_map import ChannelEntry, ChannelMapping

# phm_v2.signal 列序 (与 SELECT 一致)
SIGNAL_COLS = ["signal_id", "code", "display_name", "unit", "protocol", "source_addr",
               "phm_system", "signal_kind", "temp_role", "regime_role", "is_high_freq"]


def parse_address(protocol: str, source_addr: Optional[str]) -> Tuple[str, Optional[int]]:
    """把 signal.source_addr 解析成 ChannelEntry 的 (path, index).

    nclink/hnc: 约定 "path@index" (index 为整数下标); 无 '@' 或后缀非整数则 (整串, None).
    opcua(NodeId) / ni_daq(通道): 整串作地址, 无 index.
    """
    addr = (source_addr or "").strip()
    if (protocol or "").lower() in ("nclink", "hnc") and "@" in addr:
        path, _, idx = addr.rpartition("@")
        idx = idx.strip()
        if re.fullmatch(r"-?\d+", idx):
            return path, int(idx)
    return addr, None


def entry_role(row: Dict[str, object]) -> str:
    if row.get("regime_role"):
        return "condition"
    tr = row.get("temp_role")
    if tr == "confound":
        return "confounder_temp"
    if tr == "coupled":
        return "channel"
    if row.get("signal_kind") == "bool":
        return "condition"
    return "channel"


def signals_to_mapping(rows: List[Dict[str, object]], system: Optional[str] = None,
                       interval_ms: int = 100, n_points: int = 600,
                       program_id: str = "standard_warmup",
                       include_high_freq: bool = False) -> ChannelMapping:
    """纯函数: signal 行列表 -> ChannelMapping. 跳过高频振动 (走各自采集器)."""
    entries: List[ChannelEntry] = []
    for r in rows:
        if r.get("is_high_freq") and not include_high_freq:
            continue
        if system and r.get("phm_system") != system:
            continue
        protocol = str(r.get("protocol") or "nclink")
        path, index = parse_address(protocol, r.get("source_addr"))  # type: ignore[arg-type]
        entries.append(ChannelEntry(
            nclink_path=path, index=index, phm_name=str(r["code"]),
            role=entry_role(r), protocol=protocol,
        ))
    sysname = system or (str(rows[0].get("phm_system")) if rows else "feed") or "feed"
    return ChannelMapping(system=sysname, entries=entries, interval_ms=interval_ms,
                          n_points=n_points, program_id=program_id)


# ---- DB 取数 (惰性 psycopg2; 算法核不依赖) ----
def fetch_signals(conn_params: dict, machine_id: str, protocol: Optional[str] = None,
                  system: Optional[str] = None) -> List[Dict[str, object]]:
    import psycopg2
    q = f"SELECT {', '.join(SIGNAL_COLS)} FROM phm_v2.signal WHERE machine_id=%s"
    args: List[object] = [machine_id]
    if protocol:
        q += " AND protocol=%s"; args.append(protocol)
    if system:
        q += " AND phm_system=%s"; args.append(system)
    q += " ORDER BY signal_id"
    conn = psycopg2.connect(**conn_params)
    try:
        cur = conn.cursor()
        cur.execute(q, args)
        return [dict(zip(SIGNAL_COLS, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def load_mapping(conn_params: dict, machine_id: str, protocol: str,
                 system: Optional[str] = None, **kw) -> ChannelMapping:
    """从 phm_v2.signal 直接构建某协议的采集映射 (按机床+协议[+系统]筛)."""
    rows = fetch_signals(conn_params, machine_id, protocol=protocol, system=system)
    return signals_to_mapping(rows, system=system, **kw)


def load_signal_ids(conn_params: dict, machine_id: str,
                    protocol: Optional[str] = None) -> Dict[str, int]:
    """code -> signal_id 索引, 供 TelemetryWriter 写库时定位 signal_id."""
    rows = fetch_signals(conn_params, machine_id, protocol=protocol)
    return {str(r["code"]): int(r["signal_id"]) for r in rows}  # type: ignore[arg-type]
