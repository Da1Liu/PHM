"""
NC-Link API Server 的 HTTP 客户端.

请求/响应格式以现场已跑通的 CNCDataGet/app.py 为准 (URL = /v1/{sn}/data/),
接口语义补充自 NC-Link应用开发指导手册 第5章.

只实现寄存器轮询所需的最小集: get_value / set_value / get_model / probe / ping.
另含 MockNclinkClient: 无硬件时合成响应, 让整套控制台可离线点通/演示.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import requests
except ImportError:  # pragma: no cover - requests 是运行期依赖
    requests = None


# NC-Link 数据项: 一条 path + 一个 index (集合类型寄存器才需要 index).
NclinkItem = Dict[str, object]


@dataclass
class NclinkResult:
    """get_value 的解析结果. flat 按 (请求顺序 x index顺序) 展平, 与 keys 一一对应."""

    status: str
    code: int
    keys: List[Tuple[str, Optional[int]]]   # [(path, index), ...] 与 flat 对齐
    flat: List[object]                       # 展平后的标量值
    raw: dict

    @property
    def ok(self) -> bool:
        return str(self.status).upper() == "SUCCESS"

    def as_map(self) -> Dict[Tuple[str, Optional[int]], object]:
        return {k: v for k, v in zip(self.keys, self.flat)}


def _flatten(x) -> List[object]:
    """把 NC-Link 的嵌套 value 数组展平成一维 (兼容 app.py 的 flatten_list)."""
    if not isinstance(x, list):
        return [x]
    out: List[object] = []
    for e in x:
        out.extend(_flatten(e)) if isinstance(e, list) else out.append(e)
    return out


def build_items(keys: Sequence[Tuple[str, Optional[int]]]) -> Tuple[List[NclinkItem], List[Tuple[str, Optional[int]]]]:
    """把 (path, index) 列表归并成 NC-Link items (同 path 的 index 合成数组),
    并返回服务端响应将要遵循的 **展平顺序** (items 顺序 x 各 item 的 index 顺序).

    与 app.py 的 brief_names 生成顺序一致, 用于把响应值映射回每个 key.
    """
    order: List[str] = []
    by_path: Dict[str, List[Optional[int]]] = {}
    for path, index in keys:
        if path not in by_path:
            by_path[path] = []
            order.append(path)
        by_path[path].append(index)

    items: List[NclinkItem] = []
    flat_keys: List[Tuple[str, Optional[int]]] = []
    for path in order:
        idxs = by_path[path]
        non_null = [i for i in idxs if i is not None]
        item: NclinkItem = {"path": path}
        if non_null:
            uniq = sorted(set(non_null))
            item["index"] = uniq[0] if len(uniq) == 1 else uniq
            for i in uniq:
                flat_keys.append((path, i))
        else:
            flat_keys.append((path, None))
        items.append(item)
    return items, flat_keys


class NclinkClient:
    """对接真实 NC-Link API Server."""

    def __init__(self, host: str, port: int, sn: str, timeout: float = 10.0):
        if requests is None:
            raise RuntimeError("需要 requests 库: pip install requests")
        self.host = host
        self.port = int(port)
        self.sn = sn
        self.timeout = timeout

    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _data_url(self) -> str:
        return f"{self.base}/v1/{self.sn}/data/"

    def _model_urls(self) -> List[str]:
        # 手册接口写法不统一, 真实 jar 多为 /v1/{sn}/model; 兜底再试 /{sn}/model.
        return [f"{self.base}/v1/{self.sn}/model", f"{self.base}/{self.sn}/model"]

    # ---- 取值 ----
    def get_value(self, keys: Sequence[Tuple[str, Optional[int]]],
                  timeout_ms: Optional[int] = None) -> NclinkResult:
        items, flat_keys = build_items(keys)
        body = {"operation": "get_value", "items": items}
        if timeout_ms:
            body["timeout"] = int(timeout_ms)
        resp = requests.post(self._data_url(), json=body, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        flat = _flatten(data.get("value", []))
        # 防御: 值数量与 key 数量不一致时按短的对齐, 不抛 (现场可能少返).
        n = min(len(flat), len(flat_keys))
        return NclinkResult(
            status=data.get("status", "UNKNOWN"),
            code=int(data.get("code", -1)) if str(data.get("code", "")).lstrip("-").isdigit() else -1,
            keys=flat_keys[:n] if n < len(flat_keys) else flat_keys,
            flat=flat[:len(flat_keys)] if len(flat) >= len(flat_keys) else flat,
            raw=data,
        )

    def set_value(self, path: str, index: Optional[int], value) -> dict:
        item: NclinkItem = {"path": path, "value": value}
        if index is not None:
            item["index"] = index
        body = {"operation": "set_value", "items": [item]}
        resp = requests.post(self._data_url(), json=body, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_model(self) -> Optional[dict]:
        """拉取设备模型文件. 失败返回 None (调用方可回退到本地 model.json)."""
        last_err = None
        for url in self._model_urls():
            try:
                resp = requests.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
            except Exception as e:  # noqa: BLE001
                last_err = e
        return None

    def probe(self, keys: Sequence[Tuple[str, Optional[int]]]) -> dict:
        """探测候选寄存器是否可取值. 返回 {ok, status, values:[{path,index,value}], error, raw}.

        不抛异常: 探测就是要让前端看到失败的接口 (model.json 接口随驱动版本未必有效).
        """
        try:
            r = self.get_value(keys, timeout_ms=2000)
            values = [{"path": p, "index": i, "value": v}
                      for (p, i), v in zip(r.keys, r.flat)]
            return {"ok": r.ok, "status": r.status, "code": r.code,
                    "values": values, "raw": r.raw, "error": None}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "status": "ERROR", "values": [],
                    "raw": None, "error": str(e)}

    def ping(self) -> Tuple[bool, str]:
        """连通性检查: 尝试拉 model, 失败再尝试一次空 get_value."""
        try:
            m = self.get_model()
            if m is not None:
                return True, "model ok"
        except Exception as e:  # noqa: BLE001
            return False, f"model error: {e}"
        return False, "no model response (API Server 未启动或 SN 不对?)"


class MockNclinkClient:
    """离线演示用: 对任意 keys 合成数值. 支持注入退化趋势, 便于走通整套控制台.

    drift: 全局退化系数 [0,1+], 0=健康. 由调用方随时间推高以模拟设备退化,
    使健康度/T2/SPE 产生可观测的变化, 验证前端与生命周期联动.
    """

    def __init__(self, host="mock", port=0, sn="MOCK-SN", seed: int = 0):
        self.host, self.port, self.sn = host, port, sn
        self._rng = np.random.default_rng(seed)
        self.drift = 0.0
        # 给每个 key 一个稳定的基准值, 保证多次轮询同一通道连续.
        self._base: Dict[Tuple[str, Optional[int]], float] = {}

    def _base_for(self, key) -> float:
        if key not in self._base:
            self._base[key] = float(self._rng.uniform(5.0, 50.0))
        return self._base[key]

    def get_value(self, keys, timeout_ms=None) -> NclinkResult:
        _items, flat_keys = build_items(keys)
        flat = []
        for k in flat_keys:
            b = self._base_for(k)
            noise = float(self._rng.normal(0, 0.02 * b + 1e-6))
            # 退化: 均值偏移 + 噪声放大, 制造"边际+关系"双重异常.
            val = b * (1.0 + 0.15 * self.drift) + noise * (1.0 + self.drift)
            flat.append(round(val, 4))
        return NclinkResult("SUCCESS", 0, flat_keys, flat,
                            {"status": "SUCCESS", "code": 0, "value": [flat]})

    def set_value(self, path, index, value):
        return {"status": "SUCCESS", "code": 0, "value": [True]}

    def get_model(self):
        return None  # 演示用本地 model.json

    def probe(self, keys):
        r = self.get_value(keys)
        return {"ok": True, "status": "SUCCESS", "code": 0,
                "values": [{"path": p, "index": i, "value": v}
                           for (p, i), v in zip(r.keys, r.flat)],
                "raw": r.raw, "error": None}

    def ping(self):
        return True, "mock client (无硬件演示模式)"
