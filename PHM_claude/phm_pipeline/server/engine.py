"""
健康度引擎: 把"一条 CollectionRecord"走完 特征->生命周期->告警->健康度 全链路.

- 由 ChannelMapping 自动构造 SystemConfig (每个 channel 按其 reducers 生成 FeatureSpec),
  使进给/主轴这类无预置 config 的系统也能即配即用.
- 复用 phm_pipeline 的 LifecycleManager (三阶段 + 准入门控) 与 AlarmState (双层去抖).
- 引擎状态可由 store 里历史采集"回放重建", 故重启后健康曲线连续.

注意: v1 引擎暂不在线做混淆温度回归剔除 (TempResidualizer 需基线拟合, 见 covariate.py);
温度若标为 confounder_temp, 仅作协变量存档, 不进向量. 耦合温度请用 role=channel.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from ..acquisition.channel_map import ChannelMapping
from ..alarm import AlarmState
from ..config import SystemConfig
from ..datasource import CollectionRecord
from ..features import FeatureSpec, extract_temps, extract_vector
from ..lifecycle import LifecycleManager
from ..score import explain


def mapping_to_config(mapping: ChannelMapping) -> SystemConfig:
    """从通道映射构造 SystemConfig (每通道按选定 reducers 展开特征)."""
    specs: List[FeatureSpec] = []
    for e in mapping.channel_entries():
        reducers = e.reducers or ["mean"]
        for red in reducers:
            specs.append(FeatureSpec(channel=e.phm_name,
                                     name=f"{e.phm_name}_{red}", reducer=red))
    confounder = [e.phm_name for e in mapping.entries if e.role == "confounder_temp"]
    return SystemConfig(
        name=mapping.system,
        feature_specs=specs,
        derived={},                 # v1 不从 UI 配派生特征; 可用 formula 通道替代
        confounder_temps=confounder,
        physical_limits={},         # 现场标定后填 (铭牌/规格书)
        baseline_by=(),             # v1 单基线; 分层后续按 condition 键开启
    )


@dataclass
class HealthEngine:
    """单系统在线健康引擎."""

    config: SystemConfig
    manager: LifecycleManager = None
    alarm: AlarmState = None
    model_version: str = "v1"

    def __post_init__(self):
        if self.manager is None:
            self.manager = LifecycleManager(cfg=self.config)
        if self.alarm is None:
            self.alarm = AlarmState(
                ucl_score=1.0, lam=self.config.ewma_lambda,
                k_consecutive=self.config.k_consecutive,
                limits=self.config.physical_limits)

    def feature_vector(self, rec: CollectionRecord):
        return extract_vector(rec, self.config.feature_specs, self.config.derived)

    def process(self, rec: CollectionRecord, day: int) -> Dict[str, object]:
        """处理一条记录 -> 健康度结果 dict (含告警/贡献), 同时推进生命周期状态."""
        x, names = self.feature_vector(rec)
        lr = self.manager.observe(x, day)

        feat_map = {n: float(v) for n, v in zip(names, x)}
        alarm = self.alarm.update(lr.score, feat_map)

        result: Dict[str, object] = {
            "health": lr.health, "score": lr.score, "stage": lr.stage,
            "n": lr.n, "n_days": lr.n_days, "blended": lr.blended,
            "admitted": bool(lr.info.get("admitted", True)),
            "t2": None, "spe": None,
            "alarm_l1": alarm["l1_alarm"], "alarm_l2": alarm["l2_alarm"],
            "alarm": alarm["alarm"], "alarm_source": alarm["source"],
            "alarm_ewma": alarm["ewma"], "l1_violations": alarm["l1_violations"],
            "model_version": self.model_version,
            "feature_names": names, "feature_values": [float(v) for v in x],
            "detail": {},
        }
        # 成熟期有模型时补 T2/SPE 与贡献分解.
        if self.manager.model is not None and lr.stage == 3:
            try:
                ex = explain(self.manager.model, x, top=3)
                result["t2"], result["spe"] = ex["t2"], ex["spe"]
                result["detail"] = {
                    "dominant_space": ex["dominant_space"],
                    "top_t2": ex["top_t2"], "top_spe": ex["top_spe"],
                }
            except Exception:  # noqa: BLE001
                pass
        return result

    def model_params(self) -> Optional[dict]:
        if self.manager.model is None:
            return None
        return self.manager.model.to_dict()
