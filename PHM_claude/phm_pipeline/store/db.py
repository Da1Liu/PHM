"""
SQLite 存储 (stdlib sqlite3, 单文件, 零外部依赖).

表:
  collections  采集窗口元信息 + 原始序列(压缩JSON)
  features     每个窗口的特征向量 (名+值) 与协变量温度
  health       每个窗口的健康度评分结果 (生命周期产出)
  models       基线模型版本 (BaselineModel.to_dict 序列化)
  config       前端配置键值 (连接参数 / 通道映射), 以 JSON 存

原始序列存为 gzip+base64 的 JSON 字符串放在 collections.raw_b64, 避免额外文件;
寄存器轮询窗口体量小 (~万级浮点), 这样足够且便于整体迁移.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

import numpy as np

from ..datasource import CollectionRecord


def _pack(obj) -> str:
    return base64.b64encode(gzip.compress(json.dumps(obj).encode("utf-8"))).decode("ascii")


def _unpack(s: str):
    return json.loads(gzip.decompress(base64.b64decode(s.encode("ascii"))).decode("utf-8"))


def _record_to_raw(rec: CollectionRecord) -> dict:
    return {
        "channels": {k: {"data": np.asarray(v[0], dtype=float).tolist(), "rate": float(v[1])}
                     for k, v in rec.channels.items()},
        "temps": {k: np.asarray(v, dtype=float).tolist() for k, v in rec.temps.items()},
        "meta": rec.meta,
    }


class Store:
    """线程安全的轻量存储 (server 多线程访问, 用一把锁串行化写)."""

    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS collections(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL, system TEXT, program_id TEXT,
                    day INTEGER, condition TEXT, meta TEXT, raw_b64 TEXT,
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS features(
                    collection_id INTEGER PRIMARY KEY,
                    names TEXT, vals TEXT, temps TEXT
                );
                CREATE TABLE IF NOT EXISTS health(
                    collection_id INTEGER PRIMARY KEY,
                    health REAL, score REAL, stage INTEGER,
                    t2 REAL, spe REAL, alarm_l1 INTEGER, alarm_l2 INTEGER,
                    admitted INTEGER, detail TEXT, model_version TEXT
                );
                CREATE TABLE IF NOT EXISTS models(
                    version TEXT PRIMARY KEY, system TEXT,
                    n_train INTEGER, created_at REAL, params TEXT
                );
                CREATE TABLE IF NOT EXISTS config(
                    key TEXT PRIMARY KEY, value TEXT, updated_at REAL
                );
                """
            )

    # ---------- config ----------
    def set_config(self, key: str, value: dict):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO config(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value), time.time()))

    def get_config(self, key: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    # ---------- collections ----------
    def insert_collection(self, rec: CollectionRecord, day: int) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO collections(ts,system,program_id,day,condition,meta,raw_b64,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (rec.timestamp, str(rec.condition.get("system", "")),
                 str(rec.condition.get("program_id", "")), int(day),
                 json.dumps(rec.condition, default=str), json.dumps(rec.meta, default=str),
                 _pack(_record_to_raw(rec)), time.time()))
            return int(cur.lastrowid)

    def insert_features(self, collection_id: int, names: List[str],
                        values: np.ndarray, temps: Optional[dict] = None):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO features(collection_id,names,vals,temps) VALUES(?,?,?,?)",
                (collection_id, json.dumps(names),
                 json.dumps(np.asarray(values, dtype=float).tolist()),
                 json.dumps(temps or {})))

    def insert_health(self, collection_id: int, result: dict):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO health(collection_id,health,score,stage,t2,spe,"
                "alarm_l1,alarm_l2,admitted,detail,model_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (collection_id, result.get("health"), result.get("score"),
                 result.get("stage"), result.get("t2"), result.get("spe"),
                 int(bool(result.get("alarm_l1"))), int(bool(result.get("alarm_l2"))),
                 int(bool(result.get("admitted", True))),
                 json.dumps(result.get("detail", {}), default=str),
                 result.get("model_version", "")))

    def load_record(self, collection_id: int) -> Optional[CollectionRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
        if not row:
            return None
        raw = _unpack(row["raw_b64"])
        channels = {k: (np.array(v["data"], dtype=float), float(v["rate"]))
                    for k, v in raw["channels"].items()}
        temps = {k: np.array(v, dtype=float) for k, v in raw["temps"].items()}
        return CollectionRecord(
            timestamp=row["ts"], condition=json.loads(row["condition"]),
            channels=channels, temps=temps, meta=raw.get("meta", {}))

    def iter_collections(self, system: Optional[str] = None) -> List[sqlite3.Row]:
        q = "SELECT * FROM collections"
        args = ()
        if system:
            q += " WHERE system=?"
            args = (system,)
        q += " ORDER BY id ASC"
        with self._lock:
            return self._conn.execute(q, args).fetchall()

    def list_collections(self, system: Optional[str] = None, limit: int = 500) -> List[dict]:
        """采集历史 + 健康度 (供前端列表/趋势)."""
        q = ("SELECT c.id, c.ts, c.system, c.program_id, c.day, c.condition, c.meta, "
             "h.health, h.score, h.stage, h.t2, h.spe, h.alarm_l1, h.alarm_l2, h.admitted "
             "FROM collections c LEFT JOIN health h ON h.collection_id=c.id ")
        args = ()
        if system:
            q += "WHERE c.system=? "
            args = (system,)
        q += "ORDER BY c.id ASC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, args + (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["condition"] = json.loads(r["condition"]) if r["condition"] else {}
            d["meta"] = json.loads(r["meta"]) if r["meta"] else {}
            out.append(d)
        return out

    def collection_count(self, system: Optional[str] = None) -> int:
        with self._lock:
            if system:
                row = self._conn.execute(
                    "SELECT COUNT(*) n FROM collections WHERE system=?", (system,)).fetchone()
            else:
                row = self._conn.execute("SELECT COUNT(*) n FROM collections").fetchone()
        return int(row["n"])

    # ---------- models ----------
    def save_model(self, version: str, system: str, n_train: int, params: dict):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO models(version,system,n_train,created_at,params) "
                "VALUES(?,?,?,?,?)",
                (version, system, int(n_train), time.time(), json.dumps(params)))

    def latest_model(self, system: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM models WHERE system=? ORDER BY created_at DESC LIMIT 1",
                (system,)).fetchone()
        if not row:
            return None
        return {"version": row["version"], "system": row["system"],
                "n_train": row["n_train"], "params": json.loads(row["params"])}

    def close(self):
        with self._lock:
            self._conn.close()
