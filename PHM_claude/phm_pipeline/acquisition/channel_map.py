"""
通道映射: NC-Link {path,index} -> PHM 的通道/温度/工况.

一条 ChannelEntry 把一个被轮询的寄存器, 接到 CollectionRecord 的某个角色上:
  role="channel"          -> channels[phm_name] = (轮询序列, 采样率)  进特征向量
  role="confounder_temp"  -> temps[phm_name] = 轮询序列            回归剔除的混淆温度
  role="condition"        -> condition[phm_name] = 该窗口代表值      基线分层键(转速/进给档/轴..)
耦合温度(油温/轴承温, 要进向量) 用 role="channel" 即可.

可选 formula: 类似 CNCDataGet 的列公式, 用窗口内同一时刻的各 brief 名做标量换算
(例如把两路寄存器合成一个物理量). 留空则取原值.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

ROLES = ("channel", "confounder_temp", "condition")
CONDITION_AGG = ("last", "mean", "mode")


@dataclass
class ChannelEntry:
    nclink_path: str
    index: Optional[int]
    phm_name: str                 # 在 PHM 里的通道名 (要与 SystemConfig 的 FeatureSpec.channel 对应)
    role: str = "channel"
    # role=channel 时该通道贡献哪些标量特征 (reducer 名, 见 features.REDUCERS).
    reducers: List[str] = field(default_factory=lambda: ["mean", "std"])
    formula: str = ""             # 可选标量公式, 变量名用其他 entry 的 phm_name
    condition_agg: str = "last"   # role=condition 时如何把序列聚成一个标签值
    protocol: str = "nclink"      # 该路来源协议 (nclink/opcua/focas..); 多协议映射用, 缺省向后兼容

    def key(self) -> Tuple[str, Optional[int]]:
        # 通用地址键: 同 path/index 二元组, 各协议自解释 (nclink=path+index;
        # opcua=node_id+None; focas=addr+kind). Collector 只按此键回填读数, 与协议无关.
        return (self.nclink_path, self.index)

    def to_dict(self) -> dict:
        return {
            "nclink_path": self.nclink_path, "index": self.index,
            "phm_name": self.phm_name, "role": self.role,
            "reducers": list(self.reducers),
            "formula": self.formula, "condition_agg": self.condition_agg,
            "protocol": self.protocol,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChannelEntry":
        return cls(
            nclink_path=d["nclink_path"], index=d.get("index"),
            phm_name=d["phm_name"], role=d.get("role", "channel"),
            reducers=list(d.get("reducers") or ["mean", "std"]),
            formula=d.get("formula", ""), condition_agg=d.get("condition_agg", "last"),
            protocol=d.get("protocol", "nclink"),
        )


@dataclass
class ChannelMapping:
    """一个系统(液压/进给/主轴)的采集映射 + 窗口采集参数."""

    system: str = "feed"
    entries: List[ChannelEntry] = field(default_factory=list)
    interval_ms: int = 100              # 轮询周期
    n_points: int = 600                 # 一个采集窗口的点数 (600 @100ms = 60s)
    program_id: str = "standard_warmup" # 标准热机/采集程序标识, 用于质检
    static_condition: Dict[str, object] = field(default_factory=dict)  # 手填的固定工况标签

    @property
    def rate_hz(self) -> float:
        return 1000.0 / max(self.interval_ms, 1)

    def poll_keys(self) -> List[Tuple[str, Optional[int]]]:
        """本映射一次轮询要取的全部 (path,index)."""
        return [e.key() for e in self.entries]

    def channel_entries(self) -> List[ChannelEntry]:
        return [e for e in self.entries if e.role == "channel"]

    def validate(self) -> List[str]:
        """返回问题列表 (空=通过)."""
        problems = []
        names = [e.phm_name for e in self.entries]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            problems.append(f"phm_name 重复: {sorted(dup)}")
        for e in self.entries:
            if e.role not in ROLES:
                problems.append(f"{e.phm_name}: 非法 role={e.role}")
            if not e.phm_name:
                problems.append(f"{e.nclink_path}: phm_name 不能为空")
        if not self.channel_entries():
            problems.append("至少需要一个 role=channel 的通道")
        return problems

    def to_dict(self) -> dict:
        return {
            "system": self.system,
            "entries": [e.to_dict() for e in self.entries],
            "interval_ms": self.interval_ms, "n_points": self.n_points,
            "program_id": self.program_id, "static_condition": self.static_condition,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChannelMapping":
        return cls(
            system=d.get("system", "feed"),
            entries=[ChannelEntry.from_dict(x) for x in d.get("entries", [])],
            interval_ms=int(d.get("interval_ms", 100)),
            n_points=int(d.get("n_points", 600)),
            program_id=d.get("program_id", "standard_warmup"),
            static_condition=d.get("static_condition", {}),
        )


_FORMULA_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FORMULA_SAFE = re.compile(r"^[\sA-Za-z0-9_+\-*/().,]*$")


def apply_formula(formula: str, scope: Dict[str, float]) -> float:
    """安全求值一个标量公式 (变量=其他 entry 的 phm_name). 失败返回 NaN.

    仅允许数字/标识符/算术符号, 禁止任何属性访问/调用, 比 app.py 的 eval 更收紧.
    """
    formula = (formula or "").strip()
    if not formula:
        return float("nan")
    if not _FORMULA_SAFE.match(formula):
        return float("nan")
    expr = formula
    # 用单词边界替换, 避免 'ps1' 命中 'ps12'.
    for name in sorted({m.group(0) for m in _FORMULA_TOKEN.finditer(formula)}, key=len, reverse=True):
        if name in scope:
            v = scope[name]
            expr = re.sub(rf"\b{re.escape(name)}\b", f"({v})", expr)
    try:
        return float(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - 已白名单过滤
    except Exception:  # noqa: BLE001
        return float("nan")
