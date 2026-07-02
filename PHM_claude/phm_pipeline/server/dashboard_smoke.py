"""中心看板冒烟自检 (DB-free) —— 锁住 2026-06-30 桌面硬化的行为契约.

不连真实 PostgreSQL: 用 `--no-db` demo + 坏端口降级 + 合成 day-mode 覆盖:
  1) demo 模式 API 契约: 路由 200/302, /api/fleet demo 标记, 所有健康态 source=mock, demo 不可写.
  2) 降级行为: 库不可达时 create_app 仍能起, /api 返回 503 degraded, /healthz 503, 写返回 ok:False.
  3) day-mode 语义 (P4 修复): _calendar_day 去重正确; calendar 跨日进成熟期 / 同日 burst 不进;
     replay(窗序号) 同日 burst 仍进成熟期 (复现 FIELD 演示).

跑法 (在 PHM_claude/ 下, 无需 DB / 无需 PHM_PGPASSWORD):
    python -m phm_pipeline.server.dashboard_smoke
全过打印 "DASHBOARD SMOKE OK"; 任一断言失败抛 AssertionError, 退出码非 0.
"""
from __future__ import annotations

import logging
import sys

import numpy as np

# 降级用例会故意触发连库失败 -> 静音其 ERROR 日志, 保持自检输出干净 (失败仍由断言捕获).
logging.getLogger("phm.dashboard").setLevel(logging.CRITICAL)

from ..config import spindle_field_v1
from ..datasource import CollectionRecord
from ..engine import HealthEngine
from ..score_runner import _calendar_day
from .dashboard import create_app


def _check(label: str, cond: bool):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    assert cond, label


# ---------------- 1. demo 模式 API 契约 ----------------
def test_demo_contract():
    print("[1] demo 模式 (--no-db) API 契约")
    c = create_app(None).test_client()
    _check("/ -> 302 (重定向 v2)", c.get("/").status_code == 302)
    _check("/v2/ -> 200", c.get("/v2/").status_code == 200)
    _check("/v2/app.js -> 200", c.get("/v2/app.js").status_code == 200)
    _check("/healthz -> 200 mode=demo", c.get("/healthz").get_json().get("mode") == "demo")

    fleet = c.get("/api/fleet").get_json()
    _check("/api/fleet ok & demo=True", fleet.get("ok") and fleet.get("demo") is True)
    _check("/api/fleet 有机床", len(fleet.get("machines", [])) >= 1)
    items = fleet.get("items", [])
    _check("/api/fleet 有概览项", len(items) >= 1)
    _check("demo 概览全 source=mock", all(it.get("source") == "mock" for it in items))

    ov = c.get("/api/overview").get_json()
    _check("/api/overview source=mock", all(it.get("source") == "mock" for it in ov.get("items", [])))
    mid = fleet["machines"][0]["id"]
    tr = c.get(f"/api/machine/{mid}/trend?system=spindle").get_json()
    _check("trend source=mock", tr.get("source") == "mock")
    dg = c.get(f"/api/machine/{mid}/diagnose?system=spindle").get_json()
    _check("diagnose source=mock", dg.get("source") == "mock")

    # demo 不可写 (无库)
    w = c.post("/api/machines", json={"machine_id": "ZZZ"}).get_json()
    _check("demo 写机床 -> ok:False", w.get("ok") is False)


# ---------------- 2. 降级行为 (库不可达) ----------------
def test_degraded():
    print("[2] 降级行为 (坏端口, 库不可达)")
    bad = dict(host="localhost", port=5999, user="postgres", password="x", dbname="vibration_db")
    app = create_app(bad)           # minconn=0 -> 库不可达也应构造成功
    _check("库不可达仍能 create_app", app is not None)
    c = app.test_client()
    r = c.get("/api/overview")
    _check("/api/overview -> 503", r.status_code == 503)
    _check("/api/overview degraded=True", r.get_json().get("degraded") is True)
    _check("/api/fleet -> 503", c.get("/api/fleet").status_code == 503)
    _check("/healthz -> 503", c.get("/healthz").status_code == 503)
    # 写路径降级: 返回 ok:False (给前端 toast), 不是 503
    w = c.post("/api/machines", json={"machine_id": "X"})
    _check("降级写机床 200+ok:False (非503)", w.status_code == 200 and w.get_json().get("ok") is False)


# ---------------- 3. day-mode 语义 (P4) ----------------
def _synth_records(n: int, day_of):
    """n 条主轴预算特征记录; day_of(i)->天偏移, 起始 epoch 0 日 (UTC)."""
    codes = ["vib_gearbox_1", "vib_gearbox_2", "vib_gearbox_3", "vib_spindle_front_bearing"]
    reds = ["rms", "kurtosis", "crest"]
    base = {f"{c}_{r}": (1.0 if r == "rms" else (3.0 if r == "kurtosis" else 1.4))
            for c in codes for r in reds}
    rng = np.random.default_rng(0)
    recs = []
    for i in range(n):
        ts = float(day_of(i)) * 86400.0 + 8 * 3600 + (i % 4) * 900   # 该天内分散
        pre = {k: float(v + rng.normal(0, 0.01)) for k, v in base.items()}
        recs.append(CollectionRecord(timestamp=ts, condition={"system": "spindle"},
                                     precomputed=pre, meta={"ts": str(ts)}))
    return recs


def _run_stages(recs, day_fn):
    eng = HealthEngine(cfg=spindle_field_v1())
    stages = {1: 0, 2: 0, 3: 0}
    for seq, rec in enumerate(recs):
        hr = eng.observe(rec, day_fn(seq, rec))
        stages[hr.stage] = stages.get(hr.stage, 0) + 1
    return stages


def test_day_mode():
    print("[3] day-mode 语义 (_calendar_day + 成熟门槛)")
    # _calendar_day 去重: 不同天不同, 同天相同
    r_multi = _synth_records(6, lambda i: i)        # 6 天
    r_same = _synth_records(6, lambda i: 0)         # 同 1 天
    _check("_calendar_day 6天->6个不同序数", len({_calendar_day(r) for r in r_multi}) == 6)
    _check("_calendar_day 同天->1个序数", len({_calendar_day(r) for r in r_same}) == 1)

    # calendar: 70 条跨 18 天 (每 4 条进 1 天) -> 进成熟期
    multi = _synth_records(70, lambda i: i // 4)
    st_cal_multi = _run_stages(multi, lambda seq, rec: _calendar_day(rec))
    _check(f"calendar 跨18天 -> 进成熟期 (stage3={st_cal_multi[3]})", st_cal_multi[3] > 0)

    # calendar: 70 条全同日 (FIELD burst) -> n_days=1 -> 不进成熟期
    burst = _synth_records(70, lambda i: 0)
    st_cal_burst = _run_stages(burst, lambda seq, rec: _calendar_day(rec))
    _check(f"calendar 同日burst -> 停建立期 (stage3={st_cal_burst[3]})", st_cal_burst[3] == 0)

    # replay: 同日 burst 但 day=窗序号 -> 进成熟期 (复现 FIELD 演示)
    st_replay = _run_stages(burst, lambda seq, rec: seq)
    _check(f"replay 同日burst -> 进成熟期 (stage3={st_replay[3]})", st_replay[3] > 0)


def main():
    print("== 中心看板冒烟自检 (DB-free) ==")
    test_demo_contract()
    test_degraded()
    test_day_mode()
    print("DASHBOARD SMOKE OK")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"DASHBOARD SMOKE FAIL: {e}")
        sys.exit(1)
