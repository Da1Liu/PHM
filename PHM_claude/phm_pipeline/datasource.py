"""
数据源接口 (解耦点).

CollectionRecord 是整条 pipeline 的输入契约: 一次标准采集窗口产出一条记录.
各通道按自身采样率保存原始序列, 不逐点对齐 (窗口级/阶段级对齐, 见落地文档 2.2).

真实采集协议未知时, 上层全部对着 FileSource / MockSource 开发.
真实通道到位后只实现 RealSource, 上层零改动.

注意: 这是 v1 临时契约, 待用户提供采集协议文档后校准字段.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Iterator, Optional, Tuple

import numpy as np


@dataclass
class CollectionRecord:
    """一次标准采集窗口的原始数据 + 元信息.

    channels: 名称 -> (原始一维序列, 采样率Hz). 例如 {"PS1": (arr, 100.0)}.
    temps:    名称 -> 原始一维序列 (温度通道单列, 用于协变量处理).
    condition: 工况标签, 决定基线分层键. 常见键见下方说明.
    """

    timestamp: float
    condition: Dict[str, object] = field(default_factory=dict)
    channels: Dict[str, Tuple[np.ndarray, float]] = field(default_factory=dict)
    temps: Dict[str, np.ndarray] = field(default_factory=dict)
    # 采集端预算好的标量特征 (特征名 -> 值). 用于高频振动: 原始波形不落库,
    # 由采集器就地算窗特征; extract_vector 命中此处则直接用, 不再 reduce 原始通道.
    # 默认空 -> 现有"原始通道 reduce"路径行为不变 (向后兼容).
    precomputed: Dict[str, float] = field(default_factory=dict)
    # 透传标签, 供调试/标注 (真实健康标签上线后通常没有).
    meta: Dict[str, object] = field(default_factory=dict)

    # ---- 常见 condition 键 (非强制, 缺省即不分层) ----
    # system:        "hydraulic" / "feed" / "spindle"
    # program_id:    标准热机/采集程序 ID, 用于质检
    # shift_hours:   上班时长 (h), 用于班次分箱
    # rpm_bin:       主轴转速档
    # feed_bin:      进给速度档
    # axis:          进给轴 X/Y/Z
    # direction:     进给方向 +/-

    def baseline_key(self, by: Tuple[str, ...]) -> Tuple:
        """按给定字段组合出基线分层键. by 为空则所有样本同一基线."""
        return tuple(self.condition.get(k) for k in by)


class DataSource(ABC):
    """抽象数据源: 产出 CollectionRecord 流."""

    @abstractmethod
    def records(self) -> Iterator[CollectionRecord]:
        ...


class MockSource(DataSource):
    """合成单条/多条记录, 供单元测试每层跑通."""

    def __init__(self, records_list):
        self._records = list(records_list)

    def records(self) -> Iterator[CollectionRecord]:
        yield from self._records

    @staticmethod
    def synth(n_channels: int = 3, length: int = 600, seed: int = 0,
              condition: Optional[dict] = None) -> "CollectionRecord":
        """生成一条平稳随机记录, 用于冒烟测试."""
        rng = np.random.default_rng(seed)
        channels = {
            f"CH{i}": (rng.normal(10.0 + i, 0.5, length), 100.0)
            for i in range(n_channels)
        }
        temps = {"T_oil": rng.normal(45.0, 0.3, length)}
        return CollectionRecord(
            timestamp=float(seed),
            condition=condition or {"system": "mock"},
            channels=channels,
            temps=temps,
        )


class FileSource(DataSource):
    """从已录制文件回放. v1 内置 UCI Hydraulic 适配器.

    UCI Hydraulic: 每个传感器一个 .txt, 行=cycle, 列=该 cycle 内采样点.
    每个 cycle 是一条 CollectionRecord. profile.txt 提供工况/状态标签.
    """

    # UCI 各传感器采样率 (Hz): 压力/EPS 100Hz, 流量 10Hz, 温度/VS/SE 1Hz.
    UCI_RATES = {
        "PS1": 100.0, "PS2": 100.0, "PS3": 100.0, "PS4": 100.0,
        "PS5": 100.0, "PS6": 100.0, "EPS1": 100.0,
        "FS1": 10.0, "FS2": 10.0,
        "TS1": 1.0, "TS2": 1.0, "TS3": 1.0, "TS4": 1.0,
        "VS1": 1.0, "SE": 1.0, "CE": 1.0, "CP": 1.0,
    }
    UCI_TEMP_SENSORS = ("TS1", "TS2", "TS3", "TS4")

    def __init__(self, data_dir: str, channels=None, temps=None,
                 row_filter=None, order=None):
        """
        data_dir: UCI hydraulic 目录.
        channels: 要加载的信号通道名列表 (默认压力/流量/功率/振动/效率).
        temps:    温度通道名列表 (默认 TS1-TS4).
        row_filter: callable(profile_row_dict)->bool, 选 cycle 子集.
        order:    callable(profile_dict)->index array, 控制回放顺序 (模拟逐日到货).
        """
        self.data_dir = data_dir
        self.channels = list(channels) if channels else [
            "PS1", "PS2", "PS3", "FS1", "FS2", "EPS1", "VS1", "SE",
        ]
        self.temps = list(temps) if temps else list(self.UCI_TEMP_SENSORS)
        self.row_filter = row_filter
        self.order = order

    def _load(self, sensor: str) -> np.ndarray:
        return np.loadtxt(os.path.join(self.data_dir, f"{sensor}.txt"))

    def records(self) -> Iterator[CollectionRecord]:
        profile = np.loadtxt(os.path.join(self.data_dir, "profile.txt"), dtype=int)
        prof_cols = ["cooler", "valve", "pump", "accumulator", "stable"]
        prof = {c: profile[:, i] for i, c in enumerate(prof_cols)}

        cache = {s: self._load(s) for s in self.channels}
        temp_cache = {s: self._load(s) for s in self.temps}

        idx_all = np.arange(len(profile))
        if self.order is not None:
            idx_all = self.order(prof)

        for i in idx_all:
            row = {c: int(prof[c][i]) for c in prof_cols}
            if self.row_filter is not None and not self.row_filter(row):
                continue
            channels = {
                s: (cache[s][i].astype(float), self.UCI_RATES.get(s, 1.0))
                for s in self.channels
            }
            temps = {s: temp_cache[s][i].astype(float) for s in self.temps}
            condition = {
                "system": "hydraulic",
                "program_id": "uci_standard_cycle",
                **row,
            }
            yield CollectionRecord(
                timestamp=float(i),
                condition=condition,
                channels=channels,
                temps=temps,
                meta={"cycle": int(i), "pump": row["pump"]},
            )


class RealSource(DataSource):
    """真实采集通道: NC-Link 寄存器轮询 -> CollectionRecord.

    把一个 acquisition.Collector (内含 NclinkClient + ChannelMapping) 包成 DataSource.
    每调用一次采集窗口产出一条 record. records() 用于"连续按窗口采集"的流式场景;
    server 端通常直接用 collect_one() 触发单次采集.

    condition_provider: 可选 callable()->dict, 在每条 record 上动态注入工况标签
    (例如从外部读取当前主轴转速档/进给档), 覆盖映射里的静态 condition.
    """

    def __init__(self, collector, condition_provider=None, max_windows: Optional[int] = None):
        self.collector = collector
        self.condition_provider = condition_provider
        self.max_windows = max_windows

    def collect_one(self, progress_cb=None, stop_flag=None) -> CollectionRecord:
        overrides = self.condition_provider() if self.condition_provider else None
        return self.collector.collect_window(
            condition_overrides=overrides, progress_cb=progress_cb, stop_flag=stop_flag)

    def records(self) -> Iterator[CollectionRecord]:
        count = 0
        while self.max_windows is None or count < self.max_windows:
            yield self.collect_one()
            count += 1


class PostgresSource(DataSource):
    """从 phm_v2.telemetry 读 CollectionRecord 流 (整合采集系统的统一数据契约).

    telemetry 长表: (machine_id, signal_id, ts, value, feature, epoch, regime).
    按 signal.is_high_freq 分流 (整合设计 §2):
      - 高频振动 (is_high_freq=TRUE): 采集端已算好窗特征 (feature=rms/std/...),
        同一 ts 即一个采集窗 -> 直接进 rec.precomputed, 命名 "{code}_{feature}".
      - 低频标量 (is_high_freq=FALSE, feature=NULL): 原始读数, 按 window_seconds
        分窗聚成原始序列进 rec.channels, 交由 features.py 现场 reduce.

    驱动 psycopg2 仅在此处惰性导入, 不影响纯 numpy 算法核的导入.
    """

    def __init__(self, conn_params: dict, machine_id: str, epoch: Optional[int] = None,
                 window_seconds: float = 1.0, condition_extra: Optional[dict] = None):
        self.conn_params = conn_params
        self.machine_id = machine_id
        self.epoch = epoch
        self.window_seconds = window_seconds
        self.condition_extra = condition_extra or {}

    def _signals(self, cur):
        cur.execute(
            "SELECT signal_id, code, phm_system, is_high_freq "
            "FROM phm_v2.signal WHERE machine_id=%s", (self.machine_id,))
        return {r[0]: {"code": r[1], "system": r[2], "high": r[3]} for r in cur.fetchall()}

    def records(self) -> Iterator[CollectionRecord]:
        import psycopg2  # 惰性导入: 算法核不依赖
        conn = psycopg2.connect(**self.conn_params)
        try:
            cur = conn.cursor()
            sig = self._signals(cur)
            where = "machine_id=%s" + ("" if self.epoch is None else " AND epoch=%s")
            args = (self.machine_id,) if self.epoch is None else (self.machine_id, self.epoch)
            cur.execute(
                f"SELECT signal_id, ts, value, feature, regime FROM phm_v2.telemetry "
                f"WHERE {where} ORDER BY ts", args)
            rows = cur.fetchall()
        finally:
            conn.close()

        # 高频: 按 ts 分组成窗 (一个 ts = 一个采集窗)
        from collections import OrderedDict
        windows: "OrderedDict" = OrderedDict()
        low_buf: list = []
        for signal_id, ts, value, feature, regime in rows:
            meta = sig.get(signal_id)
            if meta is None:
                continue
            if meta["high"]:
                w = windows.setdefault(ts, {"precomputed": {}, "system": meta["system"],
                                            "regime": regime})
                w["precomputed"][f"{meta['code']}_{feature}"] = float(value)
            else:
                low_buf.append((ts, meta, value, regime))
        # 低频原始序列: 按 window_seconds 分窗 (无低频数据时此分支不产出)
        # (v1 先支持高频预算特征流; 低频窗聚合待 OPC UA telemetry 到位后启用)
        for i, (ts, w) in enumerate(windows.items()):
            cond = {"system": w["system"], **self.condition_extra}
            if w["regime"] is not None:
                cond["regime"] = w["regime"]
            yield CollectionRecord(
                timestamp=ts.timestamp() if hasattr(ts, "timestamp") else float(i),
                condition=cond,
                precomputed=w["precomputed"],
                meta={"ts": str(ts)},
            )
