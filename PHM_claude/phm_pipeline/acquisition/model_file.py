"""
解析 NC-Link model.json -> 候选寄存器/数据项清单, 供前端做通道映射.

model.json 是从机床 down 下来的设备模板 (NC_LINK_ROOT -> devices -> MACHINE -> ...).
其中:
  - CONTROLLER 下的 VARIABLE 结点对应寄存器表 (寄存器X/Y/F/.. -> @REG_X/@REG_Y/..),
    取值需带 index, 路径写法已被现场验证 (见 CNCDataGet/app.py 的 brief_reg_map).
  - AXIS 子树 (SERVO_DRIVER/MOTOR/SCREW 下的 POSITION/SPEED/CURRENT) 是 PHM 关心的
    进给系统信号, 但其精确请求路径随驱动版本而定, 这里给"猜测路径"并标 verified=False,
    必须前端 probe 确认后再用.

输出每个候选: {category, name, path, needs_index, verified, note}.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional


# 寄存器表中文名 -> @REG_ 后缀字母 (与现场验证的 app.py brief_reg_map 对应).
_REG_LETTER = {
    "寄存器X": "X", "寄存器Y": "Y", "寄存器F": "F", "寄存器G": "G",
    "寄存器R": "R", "寄存器W": "W", "寄存器D": "D", "寄存器B": "B",
    "寄存器I": "I", "寄存器Q": "Q", "寄存器K": "K", "寄存器T": "T",
    "寄存器C": "C",
}
_VAR_SPECIAL = {
    "通道0数据": "CHAN_0", "轴0数据": "AXIS_0", "轴1数据": "AXIS_1",
    "轴2数据": "AXIS_2", "轴5数据": "AXIS_5", "宏变量": "MACRO",
}


def _children(node: dict) -> List[dict]:
    out: List[dict] = []
    for key in ("configs", "dataItems", "components", "children", "subItems"):
        ch = node.get(key)
        if isinstance(ch, list):
            out.extend(c for c in ch if isinstance(c, dict))
    return out


def load_model(path_or_obj) -> dict:
    """从文件路径或已解析对象拿到 model dict."""
    if isinstance(path_or_obj, dict):
        return path_or_obj
    with open(path_or_obj, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_candidates(model: dict) -> List[Dict[str, object]]:
    """遍历模型树, 产出候选数据项清单."""
    cands: List[Dict[str, object]] = []
    devices = model.get("devices", [])

    def visit(node: dict, axis_name: Optional[str], trail: List[str]):
        ntype = node.get("type", "")
        nname = node.get("name", "")

        # --- 寄存器/变量表 (CONTROLLER 下的 VARIABLE) ---
        if ntype == "VARIABLE":
            letter = _REG_LETTER.get(nname)
            special = _VAR_SPECIAL.get(nname)
            if letter:
                cands.append({
                    "category": "寄存器", "name": nname,
                    "path": f"/MACHINE/CONTROLLER/VARIABLE@REG_{letter}",
                    "needs_index": True, "verified": True,
                    "note": "现场已验证路径写法, index 为寄存器下标",
                })
            elif special:
                cands.append({
                    "category": "变量表", "name": nname,
                    "path": f"/MACHINE/CONTROLLER/VARIABLE@{special}",
                    "needs_index": True, "verified": True,
                    "note": "通道/轴/宏变量, index 为下标",
                })

        # --- 进给轴信号 (AXIS/MOTOR/SCREW/SERVO_DRIVER 下的标量) ---
        if ntype == "AXIS":
            axis_name = nname  # 进入某轴子树, 记录轴名 (X轴/Y轴/..)
        if ntype in ("POSITION", "SPEED", "CURRENT") and axis_name:
            comp = trail[-1] if trail else ""          # MOTOR / SCREW / SERVO_DRIVER
            guessed = "/MACHINE/" + "/".join([t for t in trail if t] + [ntype])
            cands.append({
                "category": f"{axis_name}-{comp}", "name": f"{axis_name} {comp} {nname}",
                "path": guessed,
                "needs_index": False, "verified": False,
                "note": "猜测路径, 随驱动版本未必有效 -> 先 probe 再用",
            })

        new_trail = trail + [ntype] if ntype else trail
        for ch in _children(node):
            visit(ch, axis_name, new_trail)

    for dev in devices:
        if isinstance(dev, dict):
            visit(dev, None, [])

    # 机床状态/报警等常用整机项 (手册附录给了可用路径).
    cands.extend([
        {"category": "整机", "name": "机床状态", "path": "/MACHINE/STATUS",
         "needs_index": False, "verified": True, "note": "手册附录示例路径"},
        {"category": "整机", "name": "报警", "path": "/MACHINE/CONTROLLER/WARNING",
         "needs_index": False, "verified": True, "note": "手册附录示例路径"},
    ])
    return cands


def candidates_from_file(path: str) -> List[Dict[str, object]]:
    if not os.path.exists(path):
        return []
    try:
        return extract_candidates(load_model(path))
    except Exception:  # noqa: BLE001
        return []
