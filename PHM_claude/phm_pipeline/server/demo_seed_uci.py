"""
用公开数据集 (UCI Hydraulic) 把控制台数据库 seed 满, 便于直接在前端看效果.

回放与 run_selfcheck 一致: 子集 cooler=100 & stable=0, 顺序 健康(pump0)->pump1->pump2,
每级内部打乱消除工况扫描排序, 合成"天". 但这里**走控制台自己的 Store + HealthEngine 路径**
(engine = HealthEngine(mapping_to_config(mapping))), 因此 DB 落地后用
`python -m phm_pipeline.server.app --db <该db> --mock` 启动, 前端打开即见真实数据的健康曲线/告警/历史.

用法:
    python -m phm_pipeline.server.demo_seed_uci --db outputs/console/demo_uci.db
"""
import argparse
import os

import numpy as np

from ..acquisition.channel_map import ChannelEntry, ChannelMapping
from ..datasource import FileSource
from ..store.db import Store
from .app import _day_of  # noqa: F401  (保持与 app 同一 day 语义可用)
from .engine import HealthEngine, mapping_to_config

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data", "uci_hydraulic")
SAMPLES_PER_DAY = 3


def build_mapping() -> ChannelMapping:
    """液压系统映射: 压力(均值/方差) + 流量/电功率/效率(均值) + 油温(混淆温度存档).

    特征数控制在 ~10, 使 mature_min_n=max(100,10p)=100, 健康样本(169)足以进成熟期并留出平台.
    nclink_path 为占位 (本 demo 不连真机, 数据来自 UCI 回放).
    """
    e = []
    for s in ("PS1", "PS2", "PS3"):
        e.append(ChannelEntry(f"@REG_{s}", None, s, "channel", ["mean", "std"]))
    for s in ("FS1", "FS2"):
        e.append(ChannelEntry(f"@REG_{s}", None, s, "channel", ["mean"]))
    e.append(ChannelEntry("@REG_EPS1", None, "EPS1", "channel", ["mean"]))
    e.append(ChannelEntry("@REG_SE", None, "SE", "channel", ["mean"]))
    for s in ("TS1", "TS2"):
        e.append(ChannelEntry(f"@REG_{s}", None, s, "confounder_temp", []))
    return ChannelMapping(system="hydraulic", entries=e, interval_ms=100,
                          n_points=600, program_id="uci_standard_cycle")


def build_stream(mapping: ChannelMapping):
    chans = [e.phm_name for e in mapping.channel_entries()]
    temps = [e.phm_name for e in mapping.entries if e.role == "confounder_temp"]
    src = FileSource(DATA_DIR, channels=chans, temps=temps,
                     row_filter=lambda r: r["cooler"] == 100 and r["stable"] == 0)
    recs = list(src.records())
    pumps = np.array([r.meta["pump"] for r in recs])
    rng = np.random.default_rng(20260615)
    order = []
    for p in (0, 1, 2):
        idx = np.where(pumps == p)[0]
        rng.shuffle(idx)
        order.append(idx)
    order = np.concatenate(order)
    recs = [recs[i] for i in order]
    days = (np.arange(len(order)) // SAMPLES_PER_DAY).tolist()
    return recs, days


def run(db_path: str):
    if os.path.exists(db_path):
        os.remove(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    store = Store(db_path)
    mapping = build_mapping()
    store.set_config("connection", {"host": "mock", "port": 0,
                                    "sn": "UCI-HYDRAULIC-DEMO", "mock": True})
    store.set_config("mapping", mapping.to_dict())

    engine = HealthEngine(config=mapping_to_config(mapping))
    recs, days = build_stream(mapping)
    print(f"seed: n={len(recs)} 条窗口, 特征数={len(engine.config.feature_specs)}, "
          f"天数={days[-1] + 1}")

    stage_hist = {1: 0, 2: 0, 3: 0}
    n_alarm = 0
    base_day = 739000  # 任意基准日序数, 仅用于显示
    for rec, d in zip(recs, days):
        rec.condition["pump"] = int(rec.meta["pump"])
        day = base_day + int(d)
        cid = store.insert_collection(rec, day)
        result = engine.process(rec, day)
        x = result.pop("feature_values")
        names = result.pop("feature_names")
        store.insert_features(cid, names, x,
                              {k: float(v.mean()) for k, v in rec.temps.items()})
        store.insert_health(cid, result)
        stage_hist[result["stage"]] = stage_hist.get(result["stage"], 0) + 1
        n_alarm += int(result["alarm_l1"] or result["alarm_l2"])
        params = engine.model_params()
        if params is not None:
            store.save_model("v1", mapping.system, engine.manager.n, params)

    print(f"阶段分布: stage1={stage_hist.get(1,0)} stage2={stage_hist.get(2,0)} "
          f"stage3={stage_hist.get(3,0)}; 触发告警窗口={n_alarm}")
    print(f"DB -> {db_path}")
    print("启动: python -m phm_pipeline.server.app --db "
          f"\"{db_path}\" --mock --port 9000")


def main():
    ap = argparse.ArgumentParser(description="UCI 液压数据 seed 控制台 DB")
    ap.add_argument("--db", default=os.path.join("outputs", "console", "demo_uci.db"))
    args = ap.parse_args()
    run(args.db)


if __name__ == "__main__":
    main()
