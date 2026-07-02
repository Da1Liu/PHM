"""
自检层 (全新, 重点交付物): 在真机/回放流上跑整条 pipeline, 输出可信度诊断.

四类检查:
1. FAR 跟踪: 成熟期健康样本误报率 (期望 < 5%).
2. 基线稳定性: 早期冻结基线 vs 持续重训, FAR 是否失控.
3. 阶段切换连续性: 阶段边界/混合区健康度是否有可见跳变.
4. 数据质检: 程序ID/班次时长/信号饱和/断线.

这是上真机前唯一能在桌面排掉的系统性风险: step1-9 从未把
"冷启动->过渡->成熟" 整条链路端到端跑通过.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from .datasource import CollectionRecord


# ---- 数据质检 ----
def check_record(rec: CollectionRecord,
                 expected_program: Optional[str] = None,
                 min_shift_hours: float = 4.0) -> Dict[str, object]:
    """对一条采集记录做质检, 返回问题列表 (空=通过)."""
    issues = []
    if expected_program is not None:
        if rec.condition.get("program_id") != expected_program:
            issues.append("program_id_mismatch")
    sh = rec.condition.get("shift_hours")
    if sh is None:
        issues.append("shift_hours_missing")
    elif sh < min_shift_hours:
        issues.append("shift_too_short")
    for name, (arr, _rate) in rec.channels.items():
        a = np.asarray(arr, dtype=float)
        if a.size == 0 or np.any(~np.isfinite(a)):
            issues.append(f"{name}_invalid")
        elif np.std(a) < 1e-9:
            issues.append(f"{name}_flatline")  # 饱和/断线
    return {"timestamp": rec.timestamp, "issues": issues, "ok": len(issues) == 0}


# ---- FAR ----
def far(scores: np.ndarray, ucl: float = 1.0) -> float:
    if len(scores) == 0:
        return float("nan")
    return float(np.mean(np.asarray(scores) > ucl) * 100)


# ---- 阶段切换连续性 ----
def continuity(health: np.ndarray, stage: np.ndarray) -> Dict[str, float]:
    """量化阶段边界处健康度跳变, 与同段内典型波动对比."""
    health = np.asarray(health, dtype=float)
    stage = np.asarray(stage, dtype=int)
    diffs = np.abs(np.diff(health))
    boundary = np.where(np.diff(stage) != 0)[0]
    boundary_jump = float(np.max(diffs[boundary])) if len(boundary) else 0.0
    typical = float(np.median(diffs)) if len(diffs) else 0.0
    p95 = float(np.quantile(diffs, 0.95)) if len(diffs) else 0.0
    return {
        "boundary_max_jump": boundary_jump,
        "typical_step": typical,
        "step_p95": p95,
        "n_boundaries": int(len(boundary)),
        # 边界跳变是否明显超过普通波动 (>3x p95 视为可见跳变)
        "discontinuous": bool(boundary_jump > max(3 * p95, 0.05)),
    }


# ---- 基线稳定性 ----
def baseline_stability(X_healthy: np.ndarray, freeze_n: int,
                       feature_names: List[str], keep: float = 0.95) -> Dict[str, float]:
    """对比"前 freeze_n 条冻结基线" vs "全量基线"在健康尾段的 FAR.

    若冻结基线 FAR 明显高于全量, 说明早期样本不足以代表正常范围,
    需要更长积累或持续重训.
    """
    from .model import BaselineModel
    n = len(X_healthy)
    if n <= freeze_n + 10:
        return {"freeze_n": freeze_n, "far_frozen": float("nan"),
                "far_full": float("nan"), "tail_n": 0}
    tail = X_healthy[freeze_n:]

    def fit_oos(Xtr):
        fit_n = int(round(0.7 * len(Xtr)))
        return BaselineModel(feature_names=feature_names, keep=keep).fit(
            Xtr[:fit_n], Xtr[fit_n:])

    m_frozen = fit_oos(X_healthy[:freeze_n])
    m_full = fit_oos(X_healthy)
    return {
        "freeze_n": int(freeze_n),
        "far_frozen": far(m_frozen.score(tail)),
        "far_full": far(m_full.score(tail)),
        "tail_n": int(len(tail)),
    }


# ---- 单调性 ----
def monotonicity_by_level(values: np.ndarray, levels: np.ndarray) -> Dict[int, float]:
    """按等级(如 pump 0/1/2)给出均值, 检验逐级变化."""
    out = {}
    for lv in sorted(np.unique(levels)):
        out[int(lv)] = float(np.mean(np.asarray(values)[levels == lv]))
    return out
