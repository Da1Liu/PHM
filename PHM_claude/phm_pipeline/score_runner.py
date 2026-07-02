"""评分回写 runner: telemetry -> HealthEngine -> phm_v2.health_result (闭环最后一环).

把 PostgresSource 从 telemetry 拉到的 CollectionRecord 流, 逐条过 HealthEngine 评分,
把 HealthResult + 看板显示字段(mode/light/message/target_n) UPSERT 进 health_result.
中心只读看板直接读该表渲染 (评分侧算好显示字段, 看板不依赖 config).

数据节奏说明: 当前 telemetry 是一段连续标定数据 (159 窗/~2.5min). 本 runner 把每个窗
当作一个"事件样本"按窗序回放 (day=窗序号), 驱动生命周期走完 建立期->成熟期. 这证明
"telemetry->评分->health_result->看板" 管路通且数值真实; 分期的运营意义需真实事件节奏
数据 (阶段 E). 写入行的 regime/health 为真实计算值, 非 mock.

运行 (在 PHM_claude/ 下):
    python -m phm_pipeline.score_runner --machine FIELD_2026_06_18 --system spindle
    python -m phm_pipeline.score_runner --machine FIELD_2026_06_18 --system spindle --dry
"""
from __future__ import annotations

import argparse
from typing import Optional, Tuple

from .config import CONFIGS, SystemConfig
from .datasource import PostgresSource
from .db_config import default_db
from .engine import HealthEngine, HealthResult

_LIGHT_MSG = {"green": "正常", "yellow": "关注", "red": "告警"}


def _calendar_day(rec) -> int:
    """记录的日历日序数 (UTC 整日, 自 1970). 用于 lifecycle 的跨日(n_days)统计.

    PostgresSource 的 rec.timestamp = ts.timestamp() (epoch 秒), 故 floor(/86400)
    得到按真实日历日去重的序数. 真实事件节奏下 stage3_min_days(跨14天) 据此生效;
    replay 模式则不用此函数, 仍以窗序号当 day (见 run_machine_system)."""
    return int(float(rec.timestamp) // 86400)


def serialize_regime(key: Tuple) -> str:
    """baseline_key 元组 -> 文本. 单基线/全 None -> 'default'."""
    if not key or all(v is None for v in key):
        return "default"
    return "|".join("" if v is None else str(v) for v in key)


def display_fields(hr: HealthResult, cfg: SystemConfig):
    """评分侧算好看板显示字段 (中心只读). 返回 (mode, light, message, target_n, n_now)."""
    target_n = cfg.mature_min_n()
    n_now = hr.n + (1 if hr.admitted else 0)   # hr.n 是并入前计数, 修正为当前基线样本数
    if hr.stage >= 3:
        light = "green" if hr.health > 0.6 else ("yellow" if hr.health > 0.3 else "red")
        return "scoring", light, _LIGHT_MSG[light], target_n, n_now
    return "building", "building", f"基线建立中 {n_now}/{target_n}", target_n, n_now


_UPSERT = """
INSERT INTO phm_v2.health_result
 (machine_id, phm_system, epoch, regime, ts, health, score, t2, spe, ucl_t2, ucl_spe,
  stage, n, n_days, target_n, admitted, steady, mode, light, message, contributions)
VALUES (%(machine)s,%(system)s,%(epoch)s,%(regime)s,%(ts)s,%(health)s,%(score)s,
        %(t2)s,%(spe)s,%(ucl_t2)s,%(ucl_spe)s,
        %(stage)s,%(n)s,%(n_days)s,%(target_n)s,%(admitted)s,%(steady)s,
        %(mode)s,%(light)s,%(message)s,%(contributions)s)
ON CONFLICT (machine_id, phm_system, epoch, regime, ts) DO UPDATE SET
 health=EXCLUDED.health, score=EXCLUDED.score, t2=EXCLUDED.t2, spe=EXCLUDED.spe,
 ucl_t2=EXCLUDED.ucl_t2, ucl_spe=EXCLUDED.ucl_spe, stage=EXCLUDED.stage, n=EXCLUDED.n,
 n_days=EXCLUDED.n_days, target_n=EXCLUDED.target_n, admitted=EXCLUDED.admitted,
 steady=EXCLUDED.steady, mode=EXCLUDED.mode, light=EXCLUDED.light,
 message=EXCLUDED.message, contributions=EXCLUDED.contributions, created_at=now()
"""


def _r6(v):
    """可选浮点四舍五入 6 位; None 透传."""
    return None if v is None else round(float(v), 6)


def run_machine_system(conn_params: dict, machine_id: str, system: str,
                       epoch: Optional[int] = None, dry: bool = False,
                       day_mode: str = "calendar") -> dict:
    """跑一个 (机床, 系统) 的评分回写. 返回汇总统计.

    day_mode 决定喂给 lifecycle 的 day (影响 stage3_min_days 跨日成熟门槛):
      - "calendar" (默认, 诚实/生产): day=记录日历日序数, n_days 计真实跨日.
      - "replay": day=窗序号, 把一段连续标定 burst 当逐日事件回放 (复现 FIELD 演示),
        否则同日 burst 的 n_days=1 永不进成熟期.
    """
    if system not in CONFIGS:
        raise ValueError(f"未知系统 {system!r}, 可选: {list(CONFIGS)}")
    if day_mode not in ("calendar", "replay"):
        raise ValueError(f"未知 day_mode {day_mode!r}, 可选: calendar / replay")
    cfg = CONFIGS[system]()
    src = PostgresSource(conn_params, machine_id, epoch=epoch)
    engine = HealthEngine(cfg=cfg)

    rows = []
    seq = 0                               # 窗序号 (replay 模式的 day)
    stages = {1: 0, 2: 0, 3: 0}
    for rec in src.records():
        if rec.condition.get("system") != system:
            continue                      # PostgresSource 不按系统过滤, 这里收口
        day = seq if day_mode == "replay" else _calendar_day(rec)
        hr = engine.observe(rec, day)
        mode, light, message, target_n, n_now = display_fields(hr, cfg)
        stages[hr.stage] = stages.get(hr.stage, 0) + 1
        rows.append({
            "machine": machine_id, "system": system,
            "epoch": epoch if epoch is not None else 1,
            "regime": serialize_regime(hr.regime),
            "ts": rec.meta.get("ts"),
            "health": round(float(hr.health), 6), "score": round(float(hr.score), 6),
            "t2": _r6(hr.t2), "spe": _r6(hr.spe),
            "ucl_t2": _r6(hr.ucl_t2), "ucl_spe": _r6(hr.ucl_spe),
            "stage": int(hr.stage), "n": int(n_now), "n_days": int(hr.n_days),
            "target_n": int(target_n), "admitted": bool(hr.admitted),
            "steady": bool(hr.steady), "mode": mode, "light": light, "message": message,
            "contributions": hr.contributions,   # list[dict] 或 None, 写库时包 Json
        })
        seq += 1

    summary = {
        "machine": machine_id, "system": system,
        "epoch": epoch if epoch is not None else 1, "n_records": len(rows),
        "stages": stages, "target_n": cfg.mature_min_n(),
        "reached_mature": stages.get(3, 0) > 0,
        "final": rows[-1] if rows else None,
        "health_min": min((r["health"] for r in rows), default=None),
        "health_max": max((r["health"] for r in rows), default=None),
    }
    if dry or not rows:
        return summary

    import psycopg2
    import psycopg2.extras
    # contributions(list[dict]/None) -> JSONB; 不改 summary 引用的原 rows
    wrows = [{**r, "contributions": psycopg2.extras.Json(r["contributions"])
              if r["contributions"] is not None else None} for r in rows]
    conn = psycopg2.connect(**conn_params)
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_batch(cur, _UPSERT, wrows, page_size=200)
        conn.commit()
        summary["written"] = len(wrows)
    finally:
        conn.close()
    return summary


def discover_targets(conn_params: dict, machines: Optional[list] = None):
    """发现待评分目标 [(machine_id, current_epoch, system)].

    系统 = 该机床 signal 维表里出现的 phm_system ∩ CONFIGS (仅有评分配置的系统).
    仅 bool 监测/无配置的系统 (如本台液压) 不在内或评分时 0 记录 no-op.
    machines=None -> 所有机床; 否则限定列表.
    """
    import psycopg2
    conn = psycopg2.connect(**conn_params)
    try:
        cur = conn.cursor()
        if machines:
            cur.execute("SELECT machine_id, current_epoch FROM phm_v2.machine "
                        "WHERE machine_id = ANY(%s) ORDER BY machine_id", (list(machines),))
        else:
            cur.execute("SELECT machine_id, current_epoch FROM phm_v2.machine ORDER BY machine_id")
        machine_rows = cur.fetchall()
        targets = []
        for mid, cur_epoch in machine_rows:
            cur.execute("SELECT DISTINCT phm_system FROM phm_v2.signal "
                        "WHERE machine_id=%s AND phm_system IS NOT NULL", (mid,))
            for s in sorted(s for (s,) in cur.fetchall() if s in CONFIGS):
                targets.append((mid, int(cur_epoch), s))
        return targets
    finally:
        conn.close()


def run_all(conn_params: dict, machines: Optional[list] = None,
            epoch_override: Optional[int] = None, dry: bool = False,
            day_mode: str = "calendar") -> list:
    """多机床×多系统批量评分回写 (C3 调度). 单 (机床,系统) 失败隔离, 不拖垮整批.

    epoch 默认取各机床 current_epoch; epoch_override 强制覆盖 (跨 reset 不可比, 慎用).
    day_mode 透传给 run_machine_system (calendar/replay, 见其 docstring).
    """
    results = []
    for mid, cur_epoch, system in discover_targets(conn_params, machines):
        ep = epoch_override if epoch_override is not None else cur_epoch
        try:
            summary = run_machine_system(conn_params, mid, system, epoch=ep, dry=dry,
                                         day_mode=day_mode)
        except Exception as e:  # noqa: BLE001  单台/单系统失败隔离
            summary = {"machine": mid, "system": system, "epoch": ep, "error": repr(e)}
        results.append(summary)
    return results


def main():
    ap = argparse.ArgumentParser(description="PHM 评分回写 health_result")
    ap.add_argument("--machine", default=None,
                    help="单台机床 (默认 FIELD_2026_06_18); 配 --all 时限定单台所有系统")
    ap.add_argument("--system", default="spindle", choices=list(CONFIGS))
    ap.add_argument("--epoch", type=int, default=None)
    ap.add_argument("--all", action="store_true",
                    help="批量: 机床×各自系统 (忽略 --system); 无 --machine 则全部机床")
    ap.add_argument("--dry", action="store_true", help="只评分打印汇总, 不写库")
    ap.add_argument("--day-mode", default="calendar", choices=["calendar", "replay"],
                    help="calendar(默认,诚实跨日)/replay(窗序号当日,复现 FIELD burst 演示)")
    args = ap.parse_args()
    db = default_db()

    if args.all:
        machines = [args.machine] if args.machine else None
        results = run_all(db, machines=machines, epoch_override=args.epoch,
                          dry=args.dry, day_mode=args.day_mode)
        print(f"== 批量评分回写 ({len(results)} 个 机床×系统{' · dry' if args.dry else ''}) ==")
        tot = 0
        for r in results:
            if "error" in r:
                print(f"  [ERR] {r['machine']}/{r['system']}: {r['error']}")
                continue
            w = r.get("written", 0); tot += w
            light = (r.get("final") or {}).get("light")
            print(f"  {r['machine']}/{r['system']} epoch={r['epoch']} n={r['n_records']} "
                  f"stage3={r['stages'].get(3, 0)} written={w} final_light={light}")
        print(f"  -- 合计写入 {tot} 行 --")
        return

    machine = args.machine or "FIELD_2026_06_18"
    summary = run_machine_system(db, machine, args.system,
                                 epoch=args.epoch, dry=args.dry, day_mode=args.day_mode)
    print("== 评分回写汇总 ==")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
