"""
机床健康基线控制台 (Flask 单服务).

工作流: 连接 NC-Link API Server -> 映射寄存器到 PHM 通道(可 probe 验证)
        -> 按窗口采集 -> 入库 -> 生命周期健康评分 -> 趋势/告警/贡献看板.

运行:
    cd PHM_claude
    python -m phm_pipeline.server.app                # 连真实 API Server
    python -m phm_pipeline.server.app --mock         # 无硬件, 合成数据演示
    python -m phm_pipeline.server.app --port 9000 --db outputs/console/health.db

设计取舍见各模块文档; 采集只走寄存器轮询 (当前 NC-Link 版本无波形订阅).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import threading
import time
from typing import Dict, List, Optional

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

try:
    from flask_sock import Sock
except ImportError:  # WebSocket 可选, 缺失则降级为轮询
    Sock = None

from ..acquisition.channel_map import ChannelMapping
from ..acquisition.collector import Collector
from ..acquisition.model_file import candidates_from_file, extract_candidates
from ..acquisition.nclink_client import MockNclinkClient, NclinkClient
from ..datasource import RealSource
from ..lifecycle import stage_for
from ..store import Store
from .engine import HealthEngine, mapping_to_config

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
# 现场 model.json 的本地回退位置 (拉不到在线 model 时用).
LOCAL_MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))),
                           "CNCDataGet", "model.json")


def _day_of(ts: float) -> int:
    return _dt.date.fromtimestamp(ts).toordinal()


class Console:
    """控制台共享状态 (单实例, 线程安全靠粗粒度锁)."""

    def __init__(self, db_path: str, mock: bool = False):
        self.store = Store(db_path)
        self.mock = mock
        self.lock = threading.Lock()
        self.client = None
        self.mapping: Optional[ChannelMapping] = None
        self.engine: Optional[HealthEngine] = None
        # 采集线程状态
        self._collect_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.collecting = False
        self.live: Dict[str, object] = {}
        self.ws_clients: List[object] = []
        self.mock_drift = 0.0
        self._restore()

    # ---------- 恢复 ----------
    def _restore(self):
        conn = self.store.get_config("connection")
        if conn and not self.mock:
            try:
                self.client = NclinkClient(conn["host"], conn["port"], conn["sn"])
            except Exception:  # noqa: BLE001
                self.client = None
        if self.mock and self.client is None:
            self.client = MockNclinkClient(sn=(conn or {}).get("sn", "MOCK-SN"))
        m = self.store.get_config("mapping")
        if m:
            self.mapping = ChannelMapping.from_dict(m)
            self._rebuild_engine()

    def _rebuild_engine(self):
        """用映射重建引擎, 并回放历史采集恢复生命周期状态."""
        if self.mapping is None:
            self.engine = None
            return
        cfg = mapping_to_config(self.mapping)
        self.engine = HealthEngine(config=cfg)
        need = {s.channel for s in cfg.feature_specs}
        for row in self.store.iter_collections(system=self.mapping.system):
            rec = self.store.load_record(row["id"])
            if rec is None or not need.issubset(rec.channels.keys()):
                continue
            try:
                self.engine.process(rec, int(row["day"]))
            except Exception:  # noqa: BLE001
                continue
        # 若历史里已训出模型, 持久化最新一版.
        params = self.engine.model_params()
        if params is not None:
            self.store.save_model("v1", self.mapping.system,
                                  self.engine.manager.n, params)

    # ---------- 采集 ----------
    def _broadcast(self, msg: dict):
        dead = []
        for ws in self.ws_clients:
            try:
                if getattr(ws, "connected", True):
                    ws.send(json.dumps(msg, default=str))
                else:
                    dead.append(ws)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            if ws in self.ws_clients:
                self.ws_clients.remove(ws)

    def start_collection(self, overrides: dict, sim_day: Optional[int]) -> dict:
        with self.lock:
            if self.collecting:
                return {"ok": False, "error": "正在采集中"}
            if self.client is None or self.mapping is None or self.engine is None:
                return {"ok": False, "error": "请先完成连接与通道映射"}
            self._stop.clear()
            self.collecting = True
            self._collect_thread = threading.Thread(
                target=self._run_collection, args=(overrides, sim_day), daemon=True)
            self._collect_thread.start()
        return {"ok": True}

    def stop_collection(self):
        self._stop.set()
        return {"ok": True}

    def _run_collection(self, overrides: dict, sim_day: Optional[int]):
        try:
            if self.mock and isinstance(self.client, MockNclinkClient):
                self.client.drift = float(self.mock_drift)
            collector = Collector(self.client, self.mapping)
            source = RealSource(collector)

            def progress(i, n, scope):
                self.live = {"i": i, "n": n, "values": scope}
                if i % max(1, n // 50) == 0 or i == n:
                    self._broadcast({"type": "progress", "i": i, "n": n, "values": scope})

            rec = source.collect_one(progress_cb=progress, stop_flag=self._stop.is_set)
            if overrides:
                rec.condition.update(overrides)

            day = sim_day if sim_day is not None else _day_of(rec.timestamp)
            cid = self.store.insert_collection(rec, day)
            result = self.engine.process(rec, day)

            x = result.pop("feature_values")
            names = result.pop("feature_names")
            self.store.insert_features(cid, names, x,
                                       {k: float(v.mean()) for k, v in rec.temps.items()})
            self.store.insert_health(cid, result)
            params = self.engine.model_params()
            if params is not None:
                self.store.save_model("v1", self.mapping.system,
                                      self.engine.manager.n, params)

            payload = {"type": "done", "collection_id": cid, "day": day, **result}
            self._broadcast(payload)
        except Exception as e:  # noqa: BLE001
            self._broadcast({"type": "error", "error": str(e)})
        finally:
            self.collecting = False


# ---------------- Flask 应用 ----------------
def create_app(db_path: str, mock: bool = False) -> Flask:
    app = Flask(__name__, static_folder=None)
    CORS(app)
    console = Console(db_path, mock=mock)
    app.console = console
    sock = Sock(app) if Sock is not None else None

    @app.route("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.route("/static/<path:fn>")
    def static_files(fn):
        return send_from_directory(STATIC_DIR, fn)

    @app.route("/api/state")
    def state():
        c = console
        return jsonify({
            "mock": c.mock,
            "connected": c.client is not None,
            "connection": c.store.get_config("connection"),
            "mapping": c.mapping.to_dict() if c.mapping else None,
            "system": c.mapping.system if c.mapping else None,
            "collecting": c.collecting,
            "n_collections": c.store.collection_count(c.mapping.system if c.mapping else None),
            "n_pool": c.engine.manager.n if c.engine else 0,
            "n_days": c.engine.manager.n_days if c.engine else 0,
            "stage": stage_for(c.engine.manager.n, c.engine.manager.n_days,
                               c.engine.config) if (c.engine and c.engine.manager.n) else 0,
            "has_model": bool(c.engine and c.engine.manager.model is not None),
            "mock_drift": c.mock_drift,
        })

    @app.route("/api/connect", methods=["POST"])
    def connect():
        d = request.json or {}
        if d.get("mock") or console.mock:
            console.mock = True
            console.client = MockNclinkClient(sn=d.get("sn", "MOCK-SN"))
            console.store.set_config("connection",
                                     {"host": "mock", "port": 0, "sn": d.get("sn", "MOCK-SN"), "mock": True})
            return jsonify({"ok": True, "msg": "mock 演示模式已就绪"})
        try:
            client = NclinkClient(d["host"], int(d["port"]), d["sn"])
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(e)}), 400
        ok, msg = client.ping()
        console.client = client
        console.store.set_config("connection",
                                 {"host": d["host"], "port": int(d["port"]), "sn": d["sn"]})
        return jsonify({"ok": ok, "msg": msg})

    @app.route("/api/model")
    def model_candidates():
        cands, source = [], "local"
        if console.client is not None:
            try:
                m = console.client.get_model()
                if m:
                    cands, source = extract_candidates(m), "live"
            except Exception:  # noqa: BLE001
                cands = []
        if not cands:
            cands, source = candidates_from_file(LOCAL_MODEL), "local"
        return jsonify({"ok": True, "candidates": cands, "source": source})

    @app.route("/api/probe", methods=["POST"])
    def probe():
        if console.client is None:
            return jsonify({"ok": False, "error": "未连接"}), 400
        keys = [(k["path"], k.get("index")) for k in (request.json or {}).get("keys", [])]
        if not keys:
            return jsonify({"ok": False, "error": "无 keys"}), 400
        return jsonify(console.client.probe(keys))

    @app.route("/api/mapping", methods=["GET", "POST"])
    def mapping():
        if request.method == "GET":
            return jsonify(console.mapping.to_dict() if console.mapping else None)
        d = request.json or {}
        mp = ChannelMapping.from_dict(d)
        problems = mp.validate()
        if problems:
            return jsonify({"ok": False, "error": "; ".join(problems)}), 400
        console.mapping = mp
        console.store.set_config("mapping", mp.to_dict())
        console._rebuild_engine()
        return jsonify({"ok": True, "n_features": len(mapping_to_config(mp).feature_specs)})

    @app.route("/api/collect/start", methods=["POST"])
    def collect_start():
        d = request.json or {}
        if "n_points" in d and console.mapping:
            console.mapping.n_points = int(d["n_points"])
        if "interval_ms" in d and console.mapping:
            console.mapping.interval_ms = int(d["interval_ms"])
        if console.mapping:
            console.store.set_config("mapping", console.mapping.to_dict())
        return jsonify(console.start_collection(d.get("condition", {}), d.get("sim_day")))

    @app.route("/api/collect/stop", methods=["POST"])
    def collect_stop():
        return jsonify(console.stop_collection())

    @app.route("/api/collections")
    def collections():
        sys = console.mapping.system if console.mapping else None
        return jsonify({"ok": True, "rows": console.store.list_collections(sys)})

    @app.route("/api/collection/<int:cid>")
    def collection_detail(cid):
        rec = console.store.load_record(cid)
        if rec is None:
            return jsonify({"ok": False, "error": "未找到"}), 404
        return jsonify({"ok": True,
                        "channels": {k: {"data": v[0].tolist(), "rate": v[1]}
                                     for k, v in rec.channels.items()},
                        "temps": {k: v.tolist() for k, v in rec.temps.items()},
                        "condition": rec.condition, "meta": rec.meta})

    @app.route("/api/mock/drift", methods=["POST"])
    def mock_drift():
        console.mock_drift = float((request.json or {}).get("drift", 0.0))
        return jsonify({"ok": True, "drift": console.mock_drift})

    if sock is not None:
        @sock.route("/ws")
        def ws_route(ws):
            console.ws_clients.append(ws)
            try:
                while True:
                    ws.receive(timeout=30)  # 保活, 客户端不必发内容
            except Exception:  # noqa: BLE001
                pass
            finally:
                if ws in console.ws_clients:
                    console.ws_clients.remove(ws)

    return app


def main():
    ap = argparse.ArgumentParser(description="机床健康基线控制台")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--db", default=os.path.join("outputs", "console", "health.db"))
    ap.add_argument("--mock", action="store_true", help="无硬件演示模式")
    args = ap.parse_args()
    app = create_app(args.db, mock=args.mock)
    print(f"控制台启动: http://127.0.0.1:{args.port}  (db={args.db}, mock={args.mock})")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
