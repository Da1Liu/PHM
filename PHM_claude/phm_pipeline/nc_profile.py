"""空跑 NC 程序框架 (idle-run profile): regime 工况分层的单一定义源.

动机: C2 的 regime 阈值不该凭空设, 而应由"机床暖机/空跑时跑的标准 NC 动作程序"定义.
程序里每个"设定转速/进给 -> 待稳 -> 驻留测量"的节点, 就是一个 regime 的采样点.
故 idle-run profile 是一份声明式规格, 同时驱动三件事:

  1. 生成空跑 NC 程序 (按数控系统方言: FANUC / SINUMERIK(西门子840D) / HNC(华中)...);
  2. 派生 C2 配置 (baseline_by + regime_bins): 档边界 = 设定点中点 -> 工况无歧义,
     且用"设定值"(程序已知精确)而非"实测转速"(带噪)做分箱键;
  3. 标注稳态窗: 程序在每个驻留段起止发标记(M码/输出位), 采集端据此知道
     "此刻是 regime=X 的稳态测量". 稳态由"程序标记"权威给定, 信号 CV 仅作核验.

机床类型 (车/铣/镗) 只是参数不同 (转速范围/进给轴/进给范围), 框架一致:
同类机床共用一套 profile 默认值, 具体台份可覆写 -> 保证"同类机床采集分层一致".

稳态门控两层 (回答"阈值是否=程序里转速达成节点": 是):
  - 程序标记 (权威): settle_s 后进入 dwell_s 驻留, 此段即稳态测量窗, regime 由设定值给定;
  - 信号门控 (核验/兜底, regime.SteadyGate): 实测转速 vs 设定在容差内 + CV/漂移达标,
    否则弃 (如负载扰动没真正达成设定). 无程序标记的有机运行只靠信号门控.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# ---- 扫掠定义 ----
@dataclass
class SpindleSweep:
    rpm_setpoints: Tuple[int, ...]            # 转速档 (机型相关); 升序
    settle_s: float = 8.0                     # 达成+动态/热稳定时间 (测量前等待)
    dwell_s: float = 12.0                     # 稳态驻留 (要够切出 2-3 个独立窗)
    cw: bool = True                           # M03 顺时针; 可扩展双向


@dataclass
class FeedSweep:
    axes: Tuple[str, ...]                     # 进给轴 (车: X,Z; 铣: X,Y,Z; 镗: W,Z)
    feed_setpoints: Tuple[int, ...]           # 进给速度档 mm/min; 升序
    travel_mm: float = 100.0                  # 安全空走行程
    directions: Tuple[str, ...] = ("+", "-")
    settle_s: float = 2.0


@dataclass
class IdleRunProfile:
    machine_type: str                         # "mill" | "lathe" | "boring"
    spindle: Optional[SpindleSweep] = None
    feed: Optional[FeedSweep] = None
    rpm_tol_frac: float = 0.03                # 实测 vs 设定容差 -> 信号门控核验用
    name: str = "idle_run_v1"

    # ---- 派生 C2 配置 ----
    @staticmethod
    def bin_edges(setpoints: Tuple[int, ...]) -> Tuple[float, ...]:
        """相邻设定点中点作为档边界 (n 个设定点 -> n-1 个边界 -> np.digitize 得 n 档)."""
        s = sorted(float(x) for x in setpoints)
        return tuple((s[i] + s[i + 1]) / 2.0 for i in range(len(s) - 1))

    def to_c2_regime(self, system: str) -> Dict[str, object]:
        """产出可并入 SystemConfig 的 regime 字段 (dataclasses.replace(cfg, **此)).

        system="spindle": 按 rpm 档分层; system="feed": 按 轴×方向×进给档分层.
        steady_channels 给信号门控核验用的通道名 (现场实际信号名经 RegimeLabeler 归一为此).
        """
        if system == "spindle" and self.spindle:
            return {
                "baseline_by": ("rpm_bin",),
                "regime_bins": {"rpm": self.bin_edges(self.spindle.rpm_setpoints)},
                "steady_channels": ("rpm",),
            }
        if system == "feed" and self.feed:
            return {
                "baseline_by": ("axis", "direction", "feed_bin"),
                "regime_bins": {"feed": self.bin_edges(self.feed.feed_setpoints)},
                "steady_channels": ("feed",),
            }
        return {}

    def regime_grid(self, system: str) -> List[Dict[str, object]]:
        """枚举该程序会产生的全部 regime (供前端展示/校验覆盖度)."""
        out: List[Dict[str, object]] = []
        if system == "spindle" and self.spindle:
            for b, rpm in enumerate(sorted(self.spindle.rpm_setpoints)):
                out.append({"rpm_bin": b, "rpm_setpoint": rpm})
        if system == "feed" and self.feed:
            for ax in self.feed.axes:
                for d in self.feed.directions:
                    for b, fr in enumerate(sorted(self.feed.feed_setpoints)):
                        out.append({"axis": ax, "direction": d, "feed_bin": b, "feed_setpoint": fr})
        return out

    # ---- 生成 NC 程序 ----
    def to_gcode(self, dialect: "GcodeDialect") -> str:
        D = dialect
        L: List[str] = [D.comment.format(text=f"IDLE-RUN {self.name} type={self.machine_type} "
                                              f"dialect={D.name}")]
        L.append(D.comment.format(text="markers M_MARK_ON/OFF 为占位; 现场换真实 M码/输出位 "
                                        "并与采集时间戳同步"))
        if self.spindle:
            sp = self.spindle
            L.append(D.comment.format(text="== spindle sweep =="))
            for b, rpm in enumerate(sorted(sp.rpm_setpoints)):
                L.append(D.comment.format(text=f"rpm_bin={b} setpoint={rpm}"))
                L.append(D.set_rpm.format(rpm=rpm))
                L.append(D.spindle_on_cw if sp.cw else D.spindle_on_ccw)
                L.append(D.dwell.format(sec=sp.settle_s))               # 待稳
                L.append(f"{D.marker_on}  " + D.comment.format(text=f"regime rpm_bin={b} steady begin"))
                L.append(D.dwell.format(sec=sp.dwell_s))                # 稳态测量
                L.append(f"{D.marker_off}  " + D.comment.format(text="steady end"))
            L.append(D.spindle_off)
        if self.feed:
            fd = self.feed
            L.append(D.comment.format(text="== feed sweep =="))
            for ax in fd.axes:
                for d in fd.directions:
                    pos = fd.travel_mm if d == "+" else -fd.travel_mm
                    for b, fr in enumerate(sorted(fd.feed_setpoints)):
                        L.append(D.comment.format(text=f"axis={ax} dir={d} feed_bin={b} f={fr}"))
                        L.append(D.rapid.format(axis=ax, pos=0))
                        L.append(f"{D.marker_on}  " + D.comment.format(
                            text=f"regime axis={ax} dir={d} feed_bin={b} steady begin"))
                        L.append(D.linear.format(axis=ax, pos=pos, feed=fr))
                        L.append(f"{D.marker_off}  " + D.comment.format(text="steady end"))
                        L.append(D.rapid.format(axis=ax, pos=0))
        return "\n".join(L)


# ---- 数控方言 (占位骨架, 精确码/驻留单位待现场验证) ----
@dataclass
class GcodeDialect:
    name: str
    spindle_on_cw: str = "M03"
    spindle_on_ccw: str = "M04"
    spindle_off: str = "M05"
    set_rpm: str = "S{rpm}"
    dwell: str = "G04 P{sec}"              # 注意: FANUC P 常为毫秒, X 为秒; 西门子 G4 F<秒>
    linear: str = "G01 {axis}{pos} F{feed}"
    rapid: str = "G00 {axis}{pos}"
    marker_on: str = "M_MARK_ON"           # 占位 -> 现场真实 M码/PLC 输出位
    marker_off: str = "M_MARK_OFF"
    comment: str = "({text})"


FANUC = GcodeDialect(name="FANUC", dwell="G04 X{sec}", comment="({text})")
SINUMERIK = GcodeDialect(name="SINUMERIK_840D", dwell="G4 F{sec}", comment=";{text}")
HNC = GcodeDialect(name="HNC_华中", dwell="G04 P{sec}", comment="({text})")
DIALECTS = {"fanuc": FANUC, "sinumerik": SINUMERIK, "hnc": HNC}


# ---- 机型预设 (同类机床共用默认; 具体台份覆写) ----
def mill_v1() -> IdleRunProfile:
    """立/卧加工中心: 主轴中高转速, 三轴进给."""
    return IdleRunProfile(
        machine_type="mill",
        spindle=SpindleSweep(rpm_setpoints=(800, 1500, 3000, 6000, 10000)),
        feed=FeedSweep(axes=("X", "Y", "Z"), feed_setpoints=(500, 2000, 5000)),
        name="mill_idle_v1",
    )


def lathe_v1() -> IdleRunProfile:
    """车床: 主轴=工件高转速, X/Z 两轴进给."""
    return IdleRunProfile(
        machine_type="lathe",
        spindle=SpindleSweep(rpm_setpoints=(500, 1200, 2500, 4000)),
        feed=FeedSweep(axes=("X", "Z"), feed_setpoints=(300, 1500, 4000)),
        name="lathe_idle_v1",
    )


def boring_v1() -> IdleRunProfile:
    """镗床: 主轴低转速高扭矩, W/Z 进给."""
    return IdleRunProfile(
        machine_type="boring",
        spindle=SpindleSweep(rpm_setpoints=(150, 400, 800, 1500), dwell_s=15.0),
        feed=FeedSweep(axes=("W", "Z"), feed_setpoints=(200, 800, 2000)),
        name="boring_idle_v1",
    )


PROFILES = {"mill": mill_v1, "lathe": lathe_v1, "boring": boring_v1}
