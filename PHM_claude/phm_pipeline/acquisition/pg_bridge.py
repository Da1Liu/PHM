"""public(采集器实时落盘) -> phm_v2.telemetry 振动特征桥 (整合 Phase 1).

把 WebDashboard 采集器写入 `public.vib_features` 的振动窗特征, 实时增量搬进
`phm_v2.telemetry` (高频特征流, feature=rms/std/kurtosis/crest/p2p), 使"现场采一窗"
直接成为算法核 `PostgresSource` 的输入 —— 取代 CSV 回放, 闭合 采集->评分。

口径与已验证的干跑 (`_integration_probe/dryrun_build_load.py`) 一致:
  - channel 1..4 -> signal_id: 按 `signal.source_addr` 的 NI ai 序号派生 (ai0->通道1);
  - 5 个 reducer rms/std/kurtosis/crest/p2p (非 mean/peak);
  - epoch = machine.current_epoch; regime = NULL (rpm 工况分层端到端接通后再补, 见 CURRENT_STATE P1)。

单机假设: WebDashboard 一套采集器 = 一台机床, 故**整张 `public.vib_features` 归到配置的
machine_id** (不按 session/机床二次过滤)。多机部署需改造 (按 session 绑定或加 machine 列)。

增量靠 watermark 表 `phm_v2.bridge_state(last_ts)`, 幂等 (只导 time > last_ts);
watermark 更新与 telemetry 写入在**同一事务**, 避免半成功导致重复或丢窗。

纯函数 (`derive_channel_map` / `vib_rows_to_telemetry`) 与 DB IO 分离, 便于离线单测。
psycopg2 惰性导入, 不污染纯 numpy 算法核。

运行 (在 PHM_claude/ 下):
    python -m phm_pipeline.acquisition.pg_bridge --machine FIELD_2026_06_18
    python -m phm_pipeline.acquisition.pg_bridge --machine FIELD_2026_06_18 --dry-run
    python -m phm_pipeline.acquisition.pg_bridge --machine FIELD_2026_06_18 --reset-watermark
随后照常 `python -m phm_pipeline.score_runner --machine FIELD_2026_06_18 --system spindle`。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from ..db_config import default_db
from .signal_loader import fetch_signals
from .telemetry_writer import TELEMETRY_COLS, Row

# 与 dryrun_build_load 一致的 5 reducer (非 mean/peak)
DEFAULT_REDUCERS: Tuple[str, ...] = ("rms", "std", "kurtosis", "crest", "p2p")
VIB_SOURCE = "vib_features"
EPOCH0 = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------- 纯函数 (离线可测) ----------------
def parse_ai_index(source_addr: Optional[str]) -> Optional[int]:
    """从 NI 通道地址解析 ai 序号: 'cDAQ1Mod4/ai3' -> 3。"""
    m = re.search(r"ai(\d+)", str(source_addr or ""), re.I)
    return int(m.group(1)) if m else None


def derive_channel_map(ni_signals: List[Dict[str, object]]) -> Dict[int, int]:
    """ni_daq 振动 signal 行 -> {采集通道号(1-based): signal_id}。

    通道号 = ai 序号 + 1 (ai0->1, 与采集器 channel 1..N 对齐, 同 dryrun vib{c+1}->c+1)。
    任一行解析不出 ai 时退化为按 signal_id 升序枚举 1..N (并由调用方决定是否告警)。
    """
    parsed = [(parse_ai_index(r.get("source_addr")), int(r["signal_id"])) for r in ni_signals]
    if parsed and all(ai is not None for ai, _ in parsed):
        return {ai + 1: sid for ai, sid in parsed}
    return {i + 1: sid for i, (_, sid) in enumerate(sorted(parsed, key=lambda t: t[1]))}


def vib_rows_to_telemetry(vib_rows: Sequence[Dict[str, object]], channel_map: Dict[int, int],
                          machine_id: str, epoch: int = 1,
                          reducers: Sequence[str] = DEFAULT_REDUCERS,
                          regime: Optional[str] = None
                          ) -> Tuple[List[Row], Optional[datetime], List[int]]:
    """纯函数: public.vib_features 行 -> (telemetry Row 列表, 本批最大 ts, 被跳过的通道)。

    每行 dict 至少含 time / channel / <reducers>。缺 channel_map 的通道整行跳过 (记入 skipped)。
    最大 ts 覆盖**全部**读到的行 (含被跳过的), 使 watermark 不在已读区间回退。
    """
    out: List[Row] = []
    max_ts: Optional[datetime] = None
    skipped: set = set()
    for r in vib_rows:
        ts = r["time"]
        if max_ts is None or ts > max_ts:
            max_ts = ts  # type: ignore[assignment]
        ch = int(r["channel"])  # type: ignore[arg-type]
        sid = channel_map.get(ch)
        if sid is None:
            skipped.add(ch)
            continue
        for red in reducers:
            v = r.get(red)
            if v is None:
                continue
            out.append((machine_id, sid, ts, float(v), red, epoch, regime))  # type: ignore[arg-type]
    return out, max_ts, sorted(skipped)


# ---------------- DB IO ----------------
def _ensure_state_table(cur) -> None:
    cur.execute("""CREATE TABLE IF NOT EXISTS phm_v2.bridge_state (
        machine_id TEXT NOT NULL,
        source     TEXT NOT NULL,
        last_ts    TIMESTAMPTZ,
        updated_at TIMESTAMPTZ DEFAULT now(),
        PRIMARY KEY (machine_id, source)
    )""")


def _get_watermark(cur, machine_id: str, source: str) -> Optional[datetime]:
    cur.execute("SELECT last_ts FROM phm_v2.bridge_state WHERE machine_id=%s AND source=%s",
                (machine_id, source))
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def _set_watermark(cur, machine_id: str, source: str, ts: datetime) -> None:
    cur.execute("""INSERT INTO phm_v2.bridge_state (machine_id, source, last_ts, updated_at)
                   VALUES (%s,%s,%s, now())
                   ON CONFLICT (machine_id, source)
                   DO UPDATE SET last_ts=EXCLUDED.last_ts, updated_at=now()""",
                (machine_id, source, ts))


def _machine_epoch(cur, machine_id: str) -> int:
    cur.execute("SELECT current_epoch FROM phm_v2.machine WHERE machine_id=%s", (machine_id,))
    row = cur.fetchone()
    return int(row[0]) if row else 1


def _ensure_partitions(cur, ts_values: Sequence[datetime]) -> List[str]:
    """据待写 ts 自动建缺失的月分区 (telemetry 按 RANGE(ts) 月分区, 见 data-contract A3)。

    长跑桥每月都会遇到新月份, 不自动建分区会 'no partition found' 失败。幂等 IF NOT EXISTS。
    """
    created: List[str] = []
    months = {(t.year, t.month) for t in ts_values}
    for y, m in sorted(months):
        start = datetime(y, m, 1).date().isoformat()
        end = (datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)).date().isoformat()
        name = f"telemetry_{y:04d}_{m:02d}"
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS phm_v2."{name}" PARTITION OF phm_v2.telemetry '
            f"FOR VALUES FROM ('{start}') TO ('{end}')")
        created.append(name)
    return created


def run_bridge(conn_params: dict, machine_id: str,
               reducers: Sequence[str] = DEFAULT_REDUCERS,
               batch_limit: Optional[int] = None, dry_run: bool = False,
               reset_watermark: bool = False) -> dict:
    """读 public.vib_features 增量 -> 写 phm_v2.telemetry, 推进 watermark。返回统计 dict。"""
    import psycopg2
    from psycopg2.extras import RealDictCursor, execute_values

    # 通道映射来自 signal 维表 (单一真相源); 空则报错, 不静默丢数据。
    ni = [r for r in fetch_signals(conn_params, machine_id, protocol="ni_daq")
          if r.get("is_high_freq")]
    channel_map = derive_channel_map(ni)
    if not channel_map:
        raise ValueError(
            f"机床 {machine_id} 无 ni_daq 高频振动 signal 登记, 无法建立 channel->signal_id 映射。"
            " 请先在 phm_v2.signal 登记振动测点 (protocol=ni_daq, is_high_freq=TRUE)。")

    conn = psycopg2.connect(**conn_params)
    try:
        cur = conn.cursor()
        _ensure_state_table(cur)
        epoch = _machine_epoch(cur, machine_id)
        wm = EPOCH0 if reset_watermark else (_get_watermark(cur, machine_id, VIB_SOURCE) or EPOCH0)

        dcur = conn.cursor(cursor_factory=RealDictCursor)
        q = ("SELECT time, channel, " + ", ".join(reducers) +
             " FROM public.vib_features WHERE time > %s ORDER BY time, channel")
        args: List[object] = [wm]
        if batch_limit:
            q += " LIMIT %s"
            args.append(int(batch_limit))
        dcur.execute(q, args)
        vib_rows = dcur.fetchall()

        rows, max_ts, skipped = vib_rows_to_telemetry(
            vib_rows, channel_map, machine_id, epoch, reducers)
        n_windows = len({r["time"] for r in vib_rows})

        stats = {
            "machine_id": machine_id, "epoch": epoch, "source": VIB_SOURCE,
            "channel_map": channel_map, "watermark_from": wm,
            "windows_read": n_windows, "telemetry_rows": len(rows),
            "skipped_channels": skipped, "new_watermark": max_ts,
            "written": 0, "dry_run": dry_run,
        }
        if dry_run:
            return stats

        if rows:
            _ensure_partitions(cur, [r[2] for r in rows])  # ts 在 Row[2]
            execute_values(
                cur, f"INSERT INTO phm_v2.telemetry ({', '.join(TELEMETRY_COLS)}) VALUES %s", rows)
            stats["written"] = len(rows)
        if max_ts is not None:
            _set_watermark(cur, machine_id, VIB_SOURCE, max_ts)
        conn.commit()  # 写入 + watermark 同事务提交
        return stats
    finally:
        conn.close()


def _main() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="public.vib_features -> phm_v2.telemetry 振动桥 (Phase 1)")
    ap.add_argument("--machine", default="FIELD_2026_06_18", help="目标机床 (phm_v2.machine_id)")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写入")
    ap.add_argument("--reset-watermark", action="store_true", help="忽略 watermark 全量重导 (慎用, 会重复)")
    ap.add_argument("--limit", type=int, default=None, help="本次最多读多少行 (调试)")
    args = ap.parse_args()

    stats = run_bridge(default_db(), args.machine, batch_limit=args.limit,
                       dry_run=args.dry_run, reset_watermark=args.reset_watermark)
    print(json.dumps(stats, default=str, ensure_ascii=False, indent=2))
    if stats["skipped_channels"]:
        print(f"⚠ 警告: 通道 {stats['skipped_channels']} 在 signal 维表无对应振动测点, 已跳过 (检查登记/ai 序号)。")


if __name__ == "__main__":
    _main()
