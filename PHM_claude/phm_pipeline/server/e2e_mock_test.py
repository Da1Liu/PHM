"""
端到端自检 (mock 模式, 不需硬件/不开端口): 用 Flask test_client 走完控制台全流程.

连接(mock) -> 保存映射 -> 连续采集 ~130 窗口 (跨 ~18 模拟日, 后段注入退化)
-> 断言: 走到成熟期(阶段3)且训出模型, 健康样本健康度高, 退化后健康度跌+触发告警.

运行: cd PHM_claude && python -m phm_pipeline.server.e2e_mock_test
"""
from __future__ import annotations

import os
import tempfile
import time

from .app import create_app


def _wait_idle(client, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not client.get("/api/state").get_json()["collecting"]:
            return True
        time.sleep(0.01)
    return False


def run():
    db = os.path.join(tempfile.mkdtemp(), "e2e.db")
    app = create_app(db, mock=True)
    c = app.test_client()

    assert c.post("/api/connect", json={"mock": True, "sn": "E2E"}).get_json()["ok"]

    mapping = {
        "system": "feed", "interval_ms": 1, "n_points": 24,
        "entries": [
            {"nclink_path": "/MACHINE/AXIS/MOTOR/CURRENT", "index": None,
             "phm_name": "x_cur", "role": "channel", "reducers": ["mean", "std", "rms"]},
            {"nclink_path": "/MACHINE/AXIS/SCREW/SPEED", "index": None,
             "phm_name": "x_spd", "role": "channel", "reducers": ["mean", "std"]},
            {"nclink_path": "/MACHINE/CONTROLLER/VARIABLE@REG_D", "index": 100,
             "phm_name": "load", "role": "channel", "reducers": ["mean"]},
            {"nclink_path": "/MACHINE/STATUS", "index": None,
             "phm_name": "state", "role": "condition", "condition_agg": "last"},
        ],
    }
    r = c.post("/api/mapping", json=mapping).get_json()
    assert r["ok"], r
    print(f"映射保存 OK, 特征数={r['n_features']}")

    N, DEGRADE_AT = 132, 116
    healths = []
    alarms = []
    for i in range(N):
        drift = 0.0 if i < DEGRADE_AT else 0.6 * (i - DEGRADE_AT + 1)
        c.post("/api/mock/drift", json={"drift": drift})
        day = 736000 + i // 7          # ~18 个模拟日
        assert c.post("/api/collect/start", json={"sim_day": day}).get_json()["ok"]
        assert _wait_idle(c), f"采集 {i} 超时"
        rows = c.get("/api/collections").get_json()["rows"]
        last = rows[-1]
        healths.append(last["health"])
        alarms.append(bool(last["alarm_l1"] or last["alarm_l2"]))

    st = c.get("/api/state").get_json()
    print(f"\n采集 {N} 窗口完成; 池={st['n_pool']} 跨日={st['n_days']} 阶段={st['stage']} 模型={'有' if st['has_model'] else '无'}")

    # 健康段 (成熟期建成后、注入退化前) 取一段
    mature_healthy = [h for h in healths[100:DEGRADE_AT] if h is not None]
    degraded = [h for h in healths[DEGRADE_AT + 3:] if h is not None]
    deg_alarms = alarms[DEGRADE_AT + 3:]
    mh = sum(mature_healthy) / max(len(mature_healthy), 1)
    dh = sum(degraded) / max(len(degraded), 1)
    far = sum(alarms[100:DEGRADE_AT]) / max(len(alarms[100:DEGRADE_AT]), 1)
    rec_rate = sum(deg_alarms) / max(len(deg_alarms), 1)

    print(f"成熟健康段 健康度均值={mh:.3f}  误报率FAR={far:.1%}")
    print(f"退化段     健康度均值={dh:.3f}  告警率={rec_rate:.1%}")

    checks = {
        "进入成熟期(阶段3)": st["stage"] == 3,
        "训出基线模型": st["has_model"],
        "健康段健康度高(>0.6)": mh > 0.6,
        "退化段健康度明显下降": dh < mh - 0.2,
        "健康段FAR<10%": far < 0.10,
        "退化段能告警(>50%)": rec_rate > 0.5,
    }
    print("\n判据:")
    ok = True
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        ok = ok and v
    print("\n=== 端到端自检 " + ("全部通过 [OK]" if ok else "存在失败 [FAIL]") + " ===")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
