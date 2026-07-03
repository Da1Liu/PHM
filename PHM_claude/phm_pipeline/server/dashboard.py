# -*- coding: utf-8 -*-
"""
中心健康看板 (只读富前端后端) — 整合产品中心侧.

区别于 server/app.py (NC-Link 采集控制台 = 边缘侧，连接/采集/评分/本地SQLite):
本服务局于内网中心 **只读** phm_v2 (machine/signal/telemetry/health_result),
服务响应式富前端 (手机/平板/办公/大屏) + 数控HMI状态投影 + 边缘 store-and-forward 入口.

数据流 (目标): 边缘网关 评分 → push 到本服务的 /api/sync → 写 phm_v2 → 富前端只读展示

两种运行模式 (2026-06-30 收口):
- **生产模式** (连库): 只读真实 phm_v2/health_result. **DB 故障不静默回退 mock**, 而是
  把 DBError → /api 返回 503 degraded, 前端显示降级红条 (健康监测产品不能假报正常).
  某系统暂时 health_result 表 -> 显示"建立期 无数据", 同样不编造绿灯.
- **demo 模式** (--no-db): 全 mock 占位, 供无库演示, mock 仅此模式可达.

运行:
    cd PHM_claude
    python -m phm_pipeline.server.dashboard --port 8080           # 生产 (需 PHM_PGPASSWORD)
    python -m phm_pipeline.server.dashboard --port 8080 --no-db   # demo, 全 mock 不连库
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import time
from contextlib import contextmanager
from typing import Dict, List, Optional

from flask import Flask, jsonify, redirect, request, send_from_directory
from flask_cors import CORS

from ..domain.shared.boundary import Domain, tag_api
from ..domain.shared.ownership import DATA_OWNERSHIP
from ..db_config import default_db

try:
    from flask_sock import Sock
except ImportError:
    Sock = None

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static", "dashboard")        # v1 已废弃 (2026-06-29), 仅 /v1/ 参照
STATIC_DIR_V2 = os.path.join(HERE, "static", "dashboard_v2")  # v2 正式前端 (方案B master-detail), 复用同一套 /api

logger = logging.getLogger("phm.dashboard")

# 滚动窗口特征后缀 (贡献度键 = <signal_code>_<feature>); 解析原始波形时剥离
_FEATURE_SUFFIXES = ("_rms", "_std", "_kurtosis", "_crest", "_p2p", "_mean", "_max", "_min")

# Ownership metadata lives under phm_pipeline.domain. Importing it here makes
# the center dashboard's DB boundary explicit without changing any query path.
_DATA_OWNERSHIP = DATA_OWNERSHIP

# phm_v2.signal upsert (按 UNIQUE(machine_id, code)); 在线编辑/导入/克隆共用
_SIGNAL_UPSERT_SQL = (
    "INSERT INTO phm_v2.signal "
    "(machine_id, code, display_name, unit, protocol, source_addr, phm_system, "
    " signal_kind, temp_role, regime_role, is_high_freq) "
    "VALUES (%(m)s,%(code)s,%(display_name)s,%(unit)s,%(protocol)s,%(source_addr)s,"
    "%(phm_system)s,%(signal_kind)s,%(temp_role)s,%(regime_role)s,%(is_high_freq)s) "
    "ON CONFLICT (machine_id, code) DO UPDATE SET "
    " display_name=EXCLUDED.display_name, unit=EXCLUDED.unit, protocol=EXCLUDED.protocol, "
    " source_addr=EXCLUDED.source_addr, phm_system=EXCLUDED.phm_system, "
    " signal_kind=EXCLUDED.signal_kind, temp_role=EXCLUDED.temp_role, "
    " regime_role=EXCLUDED.regime_role, is_high_freq=EXCLUDED.is_high_freq")


class DBError(Exception):
    """DB 访问失败. 生产模式下 *不* 静默回退 mock, 而是上抛 -> Flask 转 503 degraded."""


def _decode_f32(data: bytes, n_out: int) -> List[float]:
    """vib_raw_blocks.data (小端 float32 块) -> 抽稀后的样本列表 (供前端折线显示).

    块由 C#/NI (x86 小端) 写入; 大端机上读取需翻转。超过 n_out 等距抽稀。
    """
    import array
    import sys as _sys
    a = array.array("f")
    a.frombytes(bytes(data))
    if _sys.byteorder == "big":
        a.byteswap()
    vals = a.tolist()
    if len(vals) > n_out > 0:
        step = len(vals) / n_out
        vals = [vals[int(i * step)] for i in range(n_out)]
    return [round(float(v), 4) for v in vals]


# ---------------- 数据访问 (生产=读 phm_v2 经连接池; demo=全 mock) ----------------
class DataProvider:
    SYSTEM_CN = {"spindle": "主轴系统", "feed": "进给系统", "hydraulic": "液压系统"}

    def __init__(self, db: Optional[dict]):
        self.db = db
        self.demo = db is None
        self._pool = None
        if db:
            from psycopg2 import pool as pgpool
            # 看板低并发只读，0..16 连接池 (给 waitress 8 线程留余量，防 PoolError).
            # minconn=0 -> 不在构造期预连，库暂不可达时服务仍能启动并显示降级
            # (监测产品须保持在线以报告"DB 故障")，首个请求再惰性建连。
            self._pool = pgpool.ThreadedConnectionPool(0, 16, **db)

    @contextmanager
    def _cursor(self, write: bool = False):
        """从池借连接 -> yield cursor -> write 则 commit/否则 rollback -> 归还连接.

        任一步失败 (建连/查询/提交) -> rollback + 记日志 + 抛 DBError (生产模式不静默吞掉转 mock),
        Flask errorhandler 转 503 degraded. 仅生产模式可用; demo 模式调用即逻辑错.
        """
        if self._pool is None:
            raise DBError("demo 模式下无 DB 连接 (不应到达此处)")
        try:
            conn = self._pool.getconn()
        except Exception as e:  # noqa: BLE001  连库失败 (库不可达)
            logger.exception("获取 DB 连接失败")
            raise DBError(str(e)) from e
        try:
            cur = conn.cursor()
            yield cur
            conn.commit() if write else conn.rollback()
        except DBError:
            raise                          # 业务侧主动抛的 DBError (如 机床不存在) 直传，不再包裹/重复记
        except Exception as e:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            logger.exception("DB 操作失败")
            raise DBError(str(e)) from e
        finally:
            self._pool.putconn(conn)

    def closeall(self):
        if self._pool is not None:
            self._pool.closeall()

    def ping(self) -> dict:
        """就绪检查: demo 直接 ok; 生产 SELECT 1 探活。不抛 (供 /healthz 自报健康)."""
        if self.demo:
            return {"ok": True, "mode": "demo", "db_reachable": None}
        try:
            with self._cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return {"ok": True, "mode": "db", "db_reachable": True}
        except DBError as e:
            return {"ok": False, "mode": "db", "db_reachable": False, "error": str(e)}

    # ---- 机床 / 系统维表 ----
    def machines(self) -> List[dict]:
        """机床 + 其拥有的系统。demo -> 占位; 生产 -> 读真实 signal 维表 (空库返回空列表)."""
        if self.demo:
            return [{"id": "FIELD_2026_06_18", "cnc": "siemens_840d", "epoch": 1,
                     "systems": ["spindle", "feed", "hydraulic"]}]
        with self._cursor() as cur:
            cur.execute("SELECT machine_id, cnc_system, current_epoch FROM phm_v2.machine ORDER BY 1")
            mrows = cur.fetchall()
            cur.execute("SELECT DISTINCT machine_id, phm_system FROM phm_v2.signal "
                        "WHERE phm_system IS NOT NULL")
            srows = cur.fetchall()
        bym: Dict[str, list] = {}
        for mid, sysn in srows:
            bym.setdefault(mid, []).append(sysn)
        machines = [{"id": r[0], "cnc": r[1], "epoch": r[2]} for r in mrows]
        for m in machines:
            m["systems"] = sorted(bym.get(m["id"], []))
        return machines

    def create_machine(self, machine_id: str, cnc_system: str = "") -> dict:
        if self.demo:
            return {"ok": False, "error": "demo 模式不可写 (未连库)"}
        if not machine_id:
            return {"ok": False, "error": "缺 machine_id"}
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "INSERT INTO phm_v2.machine (machine_id, cnc_system, current_epoch) "
                    "VALUES (%s,%s,1) ON CONFLICT (machine_id) DO NOTHING", (machine_id, cnc_system))
                created = cur.rowcount > 0
            return {"ok": True, "created": created,
                    "msg": "created" if created else "already_exists"}
        except DBError as e:
            return {"ok": False, "error": str(e)}

    def delete_machine(self, machine_id: str) -> dict:
        """彻底删除机床: 事务内连带清空 phm_v2 子表再删 machine 表 (不可逆).

        删除顺序遵守外键: telemetry/vib_raw_blocks(→signal) 与 health_result/acq_config 先删,
        再删 signal(→machine), 最后 machine. 任一步失败整体回滚.
        """
        if self.demo:
            return {"ok": False, "error": "demo 模式不可写 (未连库)"}
        if not machine_id:
            return {"ok": False, "error": "缺 machine_id"}
        try:
            with self._cursor(write=True) as cur:
                counts = {}
                for tbl in ("health_result", "vib_raw_blocks", "telemetry", "acq_config", "signal"):
                    cur.execute(f"DELETE FROM phm_v2.{tbl} WHERE machine_id=%s", (machine_id,))
                    counts[tbl] = cur.rowcount
                cur.execute("DELETE FROM phm_v2.machine WHERE machine_id=%s", (machine_id,))
                counts["machine"] = cur.rowcount
                if counts["machine"] == 0:
                    raise DBError("machine_not_found")
            return {"ok": True, "deleted": counts}
        except DBError as e:
            return {"ok": False, "error": str(e)}

    def signals(self, machine_id: str) -> List[dict]:
        if self.demo:
            base = [
                (1, "SP_VIB_X", "主轴X振动", "spindle", "vibration", None, False, True, "g", "Dev1/ai0", "ni_daq"),
                (2, "SP_VIB_Y", "主轴Y振动", "spindle", "vibration", None, False, True, "g", "Dev1/ai1", "ni_daq"),
                (3, "SP_RPM", "主轴转速", "spindle", "speed", None, True, False, "rpm", "ns=2;s=Spindle.Speed", "opcua"),
                (4, "SP_CUR", "主轴电流", "spindle", "current", None, False, False, "A", "ns=2;s=Spindle.Current", "opcua"),
                (5, "FD_TMP_MOT", "进给电机温", "feed", "temperature", "confound", False, False, "degC", "ns=2;s=Feed.MotorTemp", "opcua"),
                (6, "HY_OIL_T", "液压油温", "hydraulic", "temperature", "coupled", False, False, "degC", "ns=2;s=Hyd.OilTemp", "opcua"),
            ]
            cols = ["id", "code", "name", "system", "kind", "temp_role", "regime", "high_freq", "unit", "addr", "protocol"]
            return [dict(zip(cols, r)) for r in base]
        with self._cursor() as cur:
            cur.execute(
                "SELECT signal_id, code, display_name, phm_system, signal_kind, temp_role, "
                "regime_role, is_high_freq, unit, source_addr, protocol "
                "FROM phm_v2.signal WHERE machine_id=%s ORDER BY is_high_freq DESC, phm_system, code",
                (machine_id,))
            cols = ["id", "code", "name", "system", "kind", "temp_role", "regime", "high_freq",
                    "unit", "addr", "protocol"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ---- 信号映射在线编辑 (改 phm_v2.signal; 多协议 各台地址各异, 供工程页编辑) ----
    _SIGNAL_COLS = ("code", "display_name", "unit", "protocol", "source_addr",
                    "phm_system", "signal_kind", "temp_role", "regime_role", "is_high_freq")

    @staticmethod
    def _norm_signal(d: dict) -> dict:
        """前端/导入 dict -> 规范 signal 字段 (容错显示态键名 name/system/kind/addr/regime/high_freq)."""
        def pick(*keys):
            for k in keys:
                if d.get(k) is not None:
                    return d[k]
            return None

        def as_bool(*keys):
            v = pick(*keys)
            return bool(v) and str(v).lower() not in ("false", "0", "")
        sysv = pick("phm_system", "system")
        sysv = str(sysv).strip() or None if sysv not in (None, "") else None
        temp = pick("temp_role")
        temp = str(temp).strip() or None if str(temp).strip() not in ("None", "", "none", "none") else None
        return {
            "code": (pick("code") or "").strip(),
            "display_name": pick("display_name", "name") or "",
            "unit": pick("unit") or "",
            "protocol": (pick("protocol") or "opcua").strip(),
            "source_addr": pick("source_addr", "addr") or "",
            "phm_system": sysv,
            "signal_kind": (pick("signal_kind", "kind") or "").strip(),
            "temp_role": temp,
            "regime_role": as_bool("regime_role", "regime"),
            "is_high_freq": as_bool("is_high_freq", "high_freq"),
        }

    def upsert_signal(self, machine_id: str, d: dict) -> dict:
        """新增/改一条信号；中心侧普通保存不覆盖边缘维护的 source_addr。"""
        if self.demo:
            return {"ok": False, "error": "demo 模式不可写 (未连库)"}
        s = self._norm_signal(d)
        if not s["code"] or not s["signal_kind"]:
            return {"ok": False, "error": "code 与 signal_kind(类型) 必填"}
        try:
            with self._cursor(write=True) as cur:
                cur.execute("SELECT signal_id FROM phm_v2.signal WHERE machine_id=%s AND code=%s",
                            (machine_id, s["code"]))
                row = cur.fetchone()
                if row:
                    s["sid"] = row[0]
                    cur.execute(
                        "UPDATE phm_v2.signal SET code=%(code)s, display_name=%(display_name)s, "
                        "unit=%(unit)s, protocol=%(protocol)s, "
                        "phm_system=%(phm_system)s, signal_kind=%(signal_kind)s, temp_role=%(temp_role)s, "
                        "regime_role=%(regime_role)s, is_high_freq=%(is_high_freq)s "
                        "WHERE machine_id=%(m)s AND signal_id=%(sid)s",
                        dict(m=machine_id, **s))
                    sid = row[0]
                else:
                    cur.execute(_SIGNAL_UPSERT_SQL + " RETURNING signal_id", dict(m=machine_id, **s))
                    sid = cur.fetchone()[0]
            return {"ok": True, "signal_id": sid}
        except DBError as e:
            return {"ok": False, "error": str(e)}

    def update_signal(self, machine_id: str, signal_id: int, d: dict) -> dict:
        if self.demo:
            return {"ok": False, "error": "demo 模式不可写 (未连库)"}
        s = self._norm_signal(d)
        if not s["code"] or not s["signal_kind"]:
            return {"ok": False, "error": "code 与 signal_kind(类型) 必填"}
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "UPDATE phm_v2.signal SET code=%(code)s, display_name=%(display_name)s, "
                    "unit=%(unit)s, protocol=%(protocol)s, "
                    "phm_system=%(phm_system)s, signal_kind=%(signal_kind)s, temp_role=%(temp_role)s, "
                    "regime_role=%(regime_role)s, is_high_freq=%(is_high_freq)s "
                    "WHERE machine_id=%(m)s AND signal_id=%(sid)s",
                    dict(m=machine_id, sid=signal_id, **s))
                n = cur.rowcount
            return {"ok": n > 0, "error": None if n > 0 else "未找到该信号"}
        except DBError as e:
            return {"ok": False, "error": str(e)}

    def delete_signal(self, machine_id: str, signal_id: int) -> dict:
        if self.demo:
            return {"ok": False, "error": "demo 模式不可写 (未连库)"}
        try:
            with self._cursor(write=True) as cur:
                cur.execute("DELETE FROM phm_v2.signal WHERE machine_id=%s AND signal_id=%s",
                            (machine_id, signal_id))
                n = cur.rowcount
            return {"ok": n > 0, "error": None if n > 0 else "未找到该信号"}
        except DBError as e:
            return {"ok": False, "error": str(e)}

    def export_signals(self, machine_id: str) -> List[dict]:
        """导出规范态信号列表 (供下载 / 克隆 / 导入往复)."""
        if self.demo:
            return []
        with self._cursor() as cur:
            cur.execute(f"SELECT {', '.join(self._SIGNAL_COLS)} FROM phm_v2.signal "
                        "WHERE machine_id=%s ORDER BY is_high_freq DESC, phm_system, code",
                        (machine_id,))
            return [dict(zip(self._SIGNAL_COLS, r)) for r in cur.fetchall()]

    def import_signals(self, machine_id: str, signals: list, mode: str = "merge") -> dict:
        """批量导入. mode=merge: 逐条 upsert; replace: 先清空该机床信号再插入"""
        if self.demo:
            return {"ok": False, "error": "demo 模式不可写 (未连库)"}
        if not isinstance(signals, list):
            return {"ok": False, "error": "signals must be a list"}
        try:
            with self._cursor(write=True) as cur:
                if mode == "replace":
                    cur.execute("DELETE FROM phm_v2.signal WHERE machine_id=%s", (machine_id,))
                cnt = 0
                for raw in signals:
                    s = self._norm_signal(raw)
                    if not s["code"] or not s["signal_kind"]:
                        continue                  # 跳过缺关键字段的脏行
                    cur.execute(_SIGNAL_UPSERT_SQL, dict(m=machine_id, **s))
                    cnt += 1
            return {"ok": True, "count": cnt, "mode": mode}
        except DBError as e:
            return {"ok": False, "error": str(e)}

    def clone_signals(self, machine_id: str, from_machine: str, keep_addr: bool = False) -> dict:
        """从另一台克隆整套信号结构 (默认清空 source_addr 供逐台改地址)."""
        if self.demo:
            return {"ok": False, "error": "demo 模式不可写 (未连库)"}
        if not from_machine or machine_id == from_machine:
            return {"ok": False, "error": "需选不同于本机的源机床"}
        try:
            src = self.export_signals(from_machine)
        except DBError as e:
            return {"ok": False, "error": str(e)}
        if not src:
            return {"ok": False, "error": f"source machine {from_machine} has no signals"}
        if not keep_addr:
            for s in src:
                s["source_addr"] = ""
        return self.import_signals(machine_id, src, mode="merge")

    def latest_values(self, machine_id: str) -> dict:
        """中心数据巡检: 从 phm_v2.telemetry 取每个 signal/feature 最新值。"""
        if self.demo:
            rows = []
            now = int(time.time())
            for i, s in enumerate(self.signals(machine_id)):
                rows.append({**s, "feature": "rms" if s.get("high_freq") else None,
                             "value": round(10 * abs(math.sin(i + 1)), 3), "ts": now - i * 3,
                             "regime": None, "fresh_sec": i * 3, "source": "mock"})
            return {"ok": True, "machine": machine_id, "values": rows, "source": "mock"}
        with self._cursor() as cur:
            cur.execute(
                "WITH latest AS ("
                " SELECT DISTINCT ON (t.signal_id, COALESCE(t.feature, '')) "
                "        t.signal_id, t.ts, t.value, t.feature, t.regime "
                " FROM phm_v2.telemetry t "
                " WHERE t.machine_id=%s "
                " ORDER BY t.signal_id, COALESCE(t.feature, ''), t.ts DESC"
                ") "
                "SELECT s.signal_id, s.code, s.display_name, s.unit, s.protocol, s.phm_system, "
                "       s.signal_kind, s.is_high_freq, l.feature, l.value, l.ts, l.regime "
                "FROM phm_v2.signal s LEFT JOIN latest l ON l.signal_id=s.signal_id "
                "WHERE s.machine_id=%s "
                "ORDER BY s.is_high_freq DESC, s.phm_system, s.code, l.feature",
                (machine_id, machine_id))
            rows = cur.fetchall()
        now = time.time()
        vals = []
        for sid, code, name, unit, proto, system, kind, high, feat, val, ts, regime in rows:
            epoch = int(ts.timestamp()) if ts else None
            vals.append({"id": sid, "code": code, "name": name, "unit": unit, "protocol": proto,
                         "system": system, "kind": kind, "high_freq": bool(high), "feature": feat,
                         "value": float(val) if val is not None else None, "ts": epoch,
                         "regime": regime, "fresh_sec": round(now - epoch) if epoch else None, "source": "real" if ts else "empty"})
        return {"ok": True, "machine": machine_id, "values": vals, "source": "real"}


    # ---- 健康状态 (生产=读 health_result; 无行=建立期 无数据非 mock; demo=mock) ----
    @staticmethod
    def _empty_health_state(system: str) -> dict:
        """生产模式某系统暂时 health_result 表, 显示"建立期 无数据", **不编造绿灯**."""
        return {"mode": "building", "n": 0, "N": 1, "health": None, "light": "building",
                "message": "暂无评分数据 (待采集评分)", "source": "empty"}

    def _mock_health_state(self, machine_id: str, system: str) -> dict:
        """确定性 mock (于 demo 模式): 主轴=建立期 x/N; 进给=成熟健康; 液压=仅状态 bool)."""
        if system == "spindle":
            N = 120; n = 37
            return {"mode": "building", "n": n, "N": N, "health": None,
                    "light": "building", "message": f"基线建立中 {n}/{N}", "source": "mock"}
        if system == "feed":
            h = 0.82
            return {"mode": "scoring", "n": 156, "N": 120, "health": h,
                    "light": "green" if h > 0.6 else ("yellow" if h > 0.3 else "red"),
                    "message": "正常", "t2": 2.1, "spe": 1.3, "source": "mock"}
        return {"mode": "status_only", "health": None, "light": "green",
                "message": "油压状态正常 (以 bool 监测)", "source": "mock"}

    def overview(self, machines: Optional[List[dict]] = None) -> List[dict]:
        """全集群各 (机床,系统) 最新健康态

        生产模式: **一条** DISTINCT ON 查询取各组当前 epoch 最新 health_result 行
        (消除原 per-(机床,系统) 建连 + _epoch_of 重复查的 N+1); 无行 -> 建立期 无数据
        
        demo 模式: 逐组 mock.
        """
        ms = machines if machines is not None else self.machines()
        if self.demo:
            out = []
            for m in ms:
                for sysn in m["systems"]:
                    st = self._mock_health_state(m["id"], sysn)
                    out.append({"machine": m["id"], "system": sysn,
                                "system_cn": self.SYSTEM_CN.get(sysn, sysn), **st})
            return out
        latest: Dict[tuple, dict] = {}
        with self._cursor() as cur:
            cur.execute(
                "SELECT DISTINCT ON (h.machine_id, h.phm_system) "
                " h.machine_id, h.phm_system, h.mode, h.light, h.message, h.health, "
                " h.n, h.target_n, h.stage, h.score, h.t2, h.spe "
                "FROM phm_v2.health_result h JOIN phm_v2.machine m ON m.machine_id=h.machine_id "
                "WHERE h.epoch = m.current_epoch "
                "ORDER BY h.machine_id, h.phm_system, h.ts DESC")
            for r in cur.fetchall():
                latest[(r[0], r[1])] = {
                    "mode": r[2], "light": r[3], "message": r[4], "health": r[5],
                    "n": r[6], "N": r[7], "stage": r[8], "score": r[9],
                    "t2": r[10], "spe": r[11], "source": "real"}
        out = []
        for m in ms:
            for sysn in m["systems"]:
                st = latest.get((m["id"], sysn)) or self._empty_health_state(sysn)
                out.append({"machine": m["id"], "system": sysn,
                            "system_cn": self.SYSTEM_CN.get(sysn, sysn), **st})
        return out

    def _mock_trend(self, machine_id: str, system: str, days: int) -> dict:
        """事件性健康趋势 mock (于 demo 模式), 每天约 1 点"""
        st = self._mock_health_state(machine_id, system)
        if st["mode"] == "status_only":
            return {"mode": "status_only", "points": [], "source": "mock"}
        now = time.time()
        pts = []
        for i in range(days):
            t = now - (days - i) * 86400
            if st["mode"] == "building" and i >= st["n"]:
                break
            base = 0.85 if st["mode"] == "scoring" else 0.9
            h = max(0.0, min(1.0, base - 0.0015 * i + 0.03 * math.sin(i / 5.0)))
            pts.append({"t": int(t), "health": round(h, 3)})
        return {"mode": st["mode"], "n": st.get("n"), "N": st.get("N"), "points": pts, "source": "mock"}

    def health_trend(self, machine_id: str, system: str, days: int = 90) -> dict:
        """健康趋势曲线. 生产=读 health_result 全程 (无行->空); demo=mock."""
        if self.demo:
            return self._mock_trend(machine_id, system, days)
        with self._cursor() as cur:
            cur.execute(
                "SELECT h.ts, h.health, h.stage, h.mode FROM phm_v2.health_result h "
                "JOIN phm_v2.machine m ON m.machine_id=h.machine_id "
                "WHERE h.machine_id=%s AND h.phm_system=%s AND h.epoch=m.current_epoch ORDER BY h.ts",
                (machine_id, system))
            rows = cur.fetchall()
        if not rows:
            return {"mode": "no_data", "n": 0, "N": None, "points": [], "source": "empty"}
        pts = [{"t": int(ts.timestamp()), "health": round(float(h), 3) if h is not None else None,
                "stage": stg} for ts, h, stg, _ in rows]
        return {"mode": rows[-1][3], "n": len(pts), "N": None, "points": pts, "source": "real"}

    def _mock_diagnose(self, machine_id: str, system: str) -> dict:
        """T²/SPE 贡献 mock (于 demo 模式), 由该系统信号合成确定性占位"""
        sigs = [s for s in self.signals(machine_id) if s["system"] == system]
        feats = []
        for s in sigs[:8]:
            feats.append({"name": s["name"] or s["code"],
                          "t2": round(abs(math.sin(len(feats) + 1)) * 1.5, 2),
                          "spe": round(abs(math.cos(len(feats) + 1)) * 1.2, 2)})
        st = self._mock_health_state(machine_id, system)
        return {"mode": st["mode"], "t2": st.get("t2"), "spe": st.get("spe"),
                "ucl_t2": 4.7, "ucl_spe": 2.2, "contributions": feats, "source": "mock"}

    def diagnose(self, machine_id: str, system: str) -> dict:
        """T²/SPE 贡献分解. 生产=读 health_result 最新行 (无行->空); demo=mock."""
        if self.demo:
            return self._mock_diagnose(machine_id, system)
        with self._cursor() as cur:
            cur.execute(
                "SELECT h.mode, h.t2, h.spe, h.ucl_t2, h.ucl_spe, h.contributions "
                "FROM phm_v2.health_result h JOIN phm_v2.machine m ON m.machine_id=h.machine_id "
                "WHERE h.machine_id=%s AND h.phm_system=%s AND h.epoch=m.current_epoch "
                "ORDER BY h.ts DESC LIMIT 1", (machine_id, system))
            row = cur.fetchone()
        if not row:
            return {"mode": "no_data", "t2": None, "spe": None, "ucl_t2": None,
                    "ucl_spe": None, "contributions": [], "source": "empty"}
        mode, t2, spe, ucl_t2, ucl_spe, contribs = row

        def _r2(v):
            return None if v is None else round(float(v), 2)
        return {"mode": mode, "t2": _r2(t2), "spe": _r2(spe),
                "ucl_t2": _r2(ucl_t2), "ucl_spe": _r2(ucl_spe),
                "contributions": contribs or [], "source": "real"}

    # ---- 采集配置/控制 (结构对齐线B app_config: configStore.js DEFAULTS) ----
    _DEFAULT_ACQ = {
        "edge": {"mode": "edge_gateway", "gatewayId": "FIELD_2026_06_18", "baseUrl": "http://localhost:4000"},
        "acquisition": {
            "source": "simulated", "rate": 25600, "samplesPerChannel": 1600,
            "inputBufferSize": 300000, "tableBaseName": "tb_dev",
            "featureWindowSamples": 0, "eventEnabled": False, "eventRmsThresholdG": 0,
            "channels": [{"physicalChannel": f"cDAQ1Mod4/ai{i}", "sensitivityMvPerG": 98.94}
                         for i in range(4)],
        },
        "opcua": {"enabled": False, "profile": "kepserver", "endpoint": "opc.tcp://localhost:49320",
                  "anonymous": False, "username": "CHANGE_ME", "password": "CHANGE_ME", "pollIntervalMs": 1000},
        "nclink": {"host": "", "port": 8080, "sn": ""},
        "control": {"ni_run": False, "opcua_run": False, "capture_seq": 0, "capture_done": 0,
                    "ni_state": "idle", "ni_message": "", "ni_heartbeat": None,
                    "ni_rows": 0, "ni_sps": 0, "session": None},
    }

    @classmethod
    def _merge_acq(cls, data: Optional[dict]) -> dict:
        cfg = json.loads(json.dumps(cls._DEFAULT_ACQ))
        for k, v in (data or {}).items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
        return cfg

    def get_acq_config(self, machine_id: str) -> dict:
        if self.demo:
            return self._merge_acq(None)
        with self._cursor() as cur:
            cur.execute("SELECT data FROM phm_v2.acq_config WHERE machine_id=%s", (machine_id,))
            row = cur.fetchone()
        return self._merge_acq(row[0] if row else None)

    def save_acq_config(self, machine_id: str, patch: dict) -> dict:
        """Shallow-merge and save acquisition config."""
        if self.demo:
            return {"ok": False, "error": "demo 模式不可写 (未连库)"}
        try:
            cur_cfg = self.get_acq_config(machine_id)
            for k, v in (patch or {}).items():
                if isinstance(v, dict) and isinstance(cur_cfg.get(k), dict):
                    cur_cfg[k] = {**cur_cfg[k], **v}
                else:
                    cur_cfg[k] = v
            with self._cursor(write=True) as cur:
                cur.execute(
                    "INSERT INTO phm_v2.acq_config (machine_id, data, updated_at) VALUES (%s,%s,now()) "
                    "ON CONFLICT (machine_id) DO UPDATE SET data=EXCLUDED.data, updated_at=now()",
                    (machine_id, json.dumps(cur_cfg)))
            return {"ok": True}
        except DBError as e:
            return {"ok": False, "error": str(e)}

    def set_control(self, machine_id: str, target: str, action: str,
                    signal: Optional[str] = None) -> dict:
        """Write acquisition control intent into phm_v2.acq_config.data.control."""
        cfg = self.get_acq_config(machine_id)
        ctrl = cfg.setdefault("control", {})
        if action in ("start", "stop"):
            on = (action == "start")
            for t in (("ni", "opcua") if target == "all" else (target,)):
                ctrl[f"{t}_run"] = on
        elif action == "capture":
            ctrl["capture_seq"] = int(ctrl.get("capture_seq", 0)) + 1
            if signal:
                ctrl["capture_signal"] = signal
        self.save_acq_config(machine_id, cfg)
        return ctrl

    def collector_status(self, machine_id: str) -> dict:
        """Read collector status from phm_v2.acq_config.data.control."""
        cfg = self.get_acq_config(machine_id)
        ctrl = cfg.get("control", {})
        hb = ctrl.get("ni_heartbeat")
        alive = False
        if hb:
            try:
                from datetime import datetime, timezone
                text = str(hb).replace("Z", "+00:00")
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                alive = (datetime.now(timezone.utc) - dt).total_seconds() < 10
            except Exception:
                alive = False
        ni_run = bool(ctrl.get("ni_run"))
        opcua_run = bool(ctrl.get("opcua_run"))
        edge = cfg.get("edge", {})
        return {"ni": {"run": ni_run, "daemonAlive": alive,
                       "state": ctrl.get("ni_state") or ("running" if ni_run else "idle"),
                       "message": ctrl.get("ni_message") or "",
                       "rows": int(ctrl.get("ni_rows") or 0), "sps": float(ctrl.get("ni_sps") or 0),
                       "heartbeat": hb, "session": ctrl.get("session"),
                       "capture_seq": int(ctrl.get("capture_seq") or 0),
                       "capture_done": int(ctrl.get("capture_done") or 0)},
                "opcua": {"run": opcua_run, "daemonAlive": opcua_run,
                          "state": "running" if opcua_run else "idle"},
                "edge_online": alive or opcua_run,
                "last_sync": hb,
                "edge": edge,
                "note": "status comes from phm_v2.acq_config.data.control"}

    def _resolve_signal(self, machine_id: str, name: str):
        """Resolve a feature or signal name to (signal_id, code)."""
        if self.demo or not name:
            return None
        with self._cursor() as cur:
            cur.execute("SELECT signal_id, code FROM phm_v2.signal WHERE machine_id=%s", (machine_id,))
            rows = cur.fetchall()
        best = None
        for sid, code in rows:
            if name == code or name.startswith(code + "_") or name.startswith(code):
                if best is None or len(code) > len(best[1]):
                    best = (sid, code)
        # 容错：剥离已知特征后缀后再精确匹配
        if best is None:
            base = name
            for suf in _FEATURE_SUFFIXES:
                if base.endswith(suf):
                    base = base[: -len(suf)]; break
            for sid, code in rows:
                if code == base:
                    best = (sid, code); break
        return best

    def waveform(self, machine_id: str, signal_code: str, n: int = 600) -> dict:
        """Return latest raw waveform block or an empty result."""
        if self.demo:
            rate = self.get_acq_config(machine_id).get("acquisition", {}).get("rate", 25600)
            xs = [round(math.sin(i / 7.0) + 0.4 * math.sin(i / 2.3) + 0.1 * math.sin(i / 0.9), 3)
                  for i in range(n)]
            return {"signal": signal_code, "rate": rate, "samples": xs, "mock": True, "source": "mock"}
        sig = self._resolve_signal(machine_id, signal_code)
        if sig is None:
            return {"signal": signal_code, "samples": [], "mock": False, "source": "empty",
                    "message": "信号未登记或无原始波形块"}
        signal_id, code = sig
        with self._cursor() as cur:
            cur.execute(
                "SELECT data, rate, n_samples, time_start FROM phm_v2.vib_raw_blocks "
                "WHERE machine_id=%s AND signal_id=%s ORDER BY time_start DESC LIMIT 1",
                (machine_id, signal_id))
            row = cur.fetchone()
        if not row:
            return {"signal": code, "samples": [], "mock": False, "source": "empty",
                    "message": "暂无原始波形块 (待事件/手动抓取)"}
        data, rate, n_samples, time_start = row
        return {"signal": code, "rate": int(rate), "n_samples": int(n_samples),
                "time_start": int(time_start.timestamp()), "samples": _decode_f32(data, n),
                "mock": False, "source": "real"}

    def alarms(self, machine_id: str) -> List[dict]:
        """Return alarms."""
        if self.demo:
            return [{"ts": int(time.time()) - 3600, "system": "feed", "level": 1,
                     "message": "feed EWMA near attention threshold", "ack": False, "mock": True}]
        return []


# ---------------- Flask ----------------
def create_app(db: Optional[dict]) -> Flask:
    app = Flask(__name__, static_folder=None)
    CORS(app)
    dp = DataProvider(db)
    app.data_provider = dp
    sock = Sock(app) if Sock is not None else None
    ws_clients: List[object] = []

    @app.errorhandler(DBError)
    def _on_db_error(e):  # 生产模式 DB 故障: 503 degraded, 前端据此显示降级红条 (不渲染假绿灯)
        return jsonify({"ok": False, "degraded": True, "error": str(e)}), 503

    # 就绪/存活探测 (服务管理器/负载均衡用): 健康 200, DB 不可达 503.
    @app.route("/healthz")
    @tag_api(Domain.SHARED, "service readiness probe")
    def healthz():
        h = dp.ping()
        return jsonify(h), (200 if h["ok"] else 503)

    # 前端正式架构 = v2 (方案B master-detail); 根路径默认进 v2. v1 已废弃 (2026-06-29),
    # 仅 /v1/ 保留供设计参照, 勿再扩展.
    @app.route("/")
    @tag_api(Domain.CLOUD, "legacy cloud dashboard entry, redirects to v2")
    def index():
        return redirect("/v2/")

    @app.route("/v1/")
    @tag_api(Domain.CLOUD, "deprecated cloud dashboard v1 reference")
    def index_v1():
        return send_from_directory(STATIC_DIR, "index.html")   # 废弃: 旧五页平级看板, 仅参照
    @app.route("/static/dashboard/<path:fn>")
    @tag_api(Domain.CLOUD, "deprecated cloud dashboard v1 static assets")
    def static_files(fn):
        return send_from_directory(STATIC_DIR, fn)

    # v2 正式前端 (方案B: 集群→机床详情标签 + 设置建模); 复用下方同一套 /api.
    @app.route("/v2/")
    @tag_api(Domain.CLOUD, "cloud dashboard v2 entry")
    def index_v2():
        return send_from_directory(STATIC_DIR_V2, "index.html")

    @app.route("/v2/<path:fn>")
    @tag_api(Domain.CLOUD, "cloud dashboard v2 static assets")
    def static_files_v2(fn):
        return send_from_directory(STATIC_DIR_V2, fn)

    @app.route("/cloud/")
    @tag_api(Domain.CLOUD, "explicit cloud dashboard entry alias")
    def index_cloud():
        return send_from_directory(STATIC_DIR_V2, "index.html")

    @app.route("/cloud/<path:fn>")
    @tag_api(Domain.CLOUD, "explicit cloud dashboard static alias")
    def static_files_cloud(fn):
        return send_from_directory(STATIC_DIR_V2, fn)
    @app.route("/api/machines")
    @tag_api(Domain.CLOUD, "cloud fleet machine catalog")
    def machines():
        return jsonify({"ok": True, "machines": dp.machines()})

    @app.route("/api/machines", methods=["POST"])
    @tag_api(Domain.CLOUD, "cloud machine asset creation")
    def create_machine():
        d = request.json or {}
        return jsonify(dp.create_machine(d.get("machine_id", ""), d.get("cnc_system", "")))


    @app.route("/api/overview")
    @tag_api(Domain.CLOUD, "cloud fleet health overview")
    def overview():
        return jsonify({"ok": True, "items": dp.overview()})

    # 集群视图聚合端点: 一次返回 machines + overview (收掉前端 boot 的两请求 + 后端 N+1).
    @app.route("/api/fleet")
    @tag_api(Domain.CLOUD, "cloud fleet bootstrap aggregate")
    def fleet():
        ms = dp.machines()
        return jsonify({"ok": True, "demo": dp.demo,
                        "machines": ms, "items": dp.overview(machines=ms)})

    @app.route("/api/machine/<mid>/signals")
    @tag_api(Domain.SHARED, "shared signal catalog; Cloud owns PHM semantics, Edge owns source_addr")
    def signals(mid):
        return jsonify({"ok": True, "signals": dp.signals(mid)})

    @app.route("/api/machine/<mid>/trend")
    @tag_api(Domain.CLOUD, "cloud health trend")
    def trend(mid):
        system = request.args.get("system", "spindle")
        return jsonify({"ok": True, **dp.health_trend(mid, system)})

    @app.route("/api/machine/<mid>/diagnose")
    @tag_api(Domain.CLOUD, "cloud PHM diagnosis")
    def diagnose(mid):
        system = request.args.get("system", "spindle")
        return jsonify({"ok": True, **dp.diagnose(mid, system)})

    @app.route("/api/machine/<mid>/latest-values")
    @tag_api(Domain.CLOUD, "cloud data inspection over synced telemetry")
    def latest_values(mid):
        return jsonify(dp.latest_values(mid))


    @app.route("/api/machine/<mid>/acq-config")
    @tag_api(Domain.SHARED, "Cloud read-only view of Edge-owned acquisition config")
    def acq_config(mid):
        return jsonify({"ok": True, "config": dp.get_acq_config(mid)})

    @app.route("/api/machine/<mid>/control", methods=["POST"])
    @tag_api(Domain.EDGE, "legacy remote acquisition control; retained for compatibility")
    def control(mid):
        d = request.json or {}
        ctrl = dp.set_control(mid, d.get("target", "ni"), d.get("action", "stop"), d.get("signal"))
        return jsonify({"ok": True, "control": ctrl})

    @app.route("/api/machine/<mid>/collector-status")
    @tag_api(Domain.SHARED, "Cloud read-only view of Edge collector status")
    def collector_status(mid):
        return jsonify({"ok": True, **dp.collector_status(mid)})

    @app.route("/api/machine/<mid>/waveform")
    @tag_api(Domain.SHARED, "diagnostic waveform read; Edge owns raw blocks")
    def waveform(mid):
        return jsonify({"ok": True, **dp.waveform(mid, request.args.get("signal", ""))})

    @app.route("/api/machine/<mid>/alarms")
    @tag_api(Domain.CLOUD, "cloud alarm list")
    def alarms(mid):
        return jsonify({"ok": True, "alarms": dp.alarms(mid)})

    # 数控 HMI 状态投影 (极简, HMI 侧轮询画灯)
    @app.route("/api/status/<mid>")
    @tag_api(Domain.CLOUD, "cloud-to-HMI health status projection")
    def status(mid):
        items = [o for o in dp.overview() if o["machine"] == mid]
        order = {"red": 3, "yellow": 2, "building": 1, "green": 0}
        worst = max(items, key=lambda o: order.get(o["light"], 0)) if items else None
        return jsonify({"ok": True, "machine": mid,
                        "light": worst["light"] if worst else "green",
                        "message": worst["message"] if worst else "no_data",
                        "systems": items})

    # 边缘 store-and-forward 同步入口 (契约占位: 边缘联网后 push 未同步样本)
    @app.route("/api/sync", methods=["POST"])
    @tag_api(Domain.SHARED, "Edge-to-Cloud sync contract placeholder")
    def sync():
        payload = request.json or {}
        rows = payload.get("samples", [])
        # TODO(B/C阶段): UPSERT 到 phm_v2.telemetry + health_result, 按 (machine_id, signal_id, ts) 去重屏等.
        return jsonify({"ok": True, "received": len(rows), "note": "契约占位, 入库逻辑待 B/C 阶段"})

    if sock is not None:
        @sock.route("/ws")
        def ws_route(ws):
            ws_clients.append(ws)
            try:
                while True:
                    ws.receive(timeout=30)
            except Exception:  # noqa: BLE001
                pass
            finally:
                if ws in ws_clients:
                    ws_clients.remove(ws)

    return app


def _serve(app, host: str, port: int, dev: bool, threads: int = 8):
    """Serve with waitress when available, otherwise Flask dev server."""
    if not dev:
        try:
            from waitress import serve
        except ImportError:
            logger.warning("未安装 waitress, 退回 Flask 开发服务器 (生产请 pip install waitress 或显式 --dev)")
        else:
            logger.info("waitress 生产服务器启动 threads=%d", threads)
            serve(app, host=host, port=port, threads=threads)
            return
    logger.warning("Flask 开发服务器 (仅开发调试, 勿用于生产)")
    app.run(host=host, port=port, threaded=True)


def main():
    ap = argparse.ArgumentParser(description="机床健康中心看板 (只读富前端)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--no-db", "--demo", dest="no_db", action="store_true",
                    help="demo 模式: 不连库, 全 mock 占位 (无需 PHM_PGPASSWORD)")
    ap.add_argument("--dev", action="store_true",
                    help="用 Flask 开发服务器 (默认优先 waitress 生产 WSGI)")
    ap.add_argument("--threads", type=int, default=8, help="waitress 线程数 (≤ 连接池上限 16)")
    args = ap.parse_args()

    logging.basicConfig(
        level=os.environ.get("PHM_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db = None if args.no_db else default_db()   # 生产模式缺 PHM_PGPASSWORD 即报错退出
    app = create_app(db)
    mode = "demo/mock" if db is None else "db:" + db["dbname"]
    print(f"中心看板启动: http://127.0.0.1:{args.port}/v2/  (mode={mode}, 探测 /healthz)")
    _serve(app, args.host, args.port, dev=args.dev, threads=args.threads)


if __name__ == "__main__":
    main()







