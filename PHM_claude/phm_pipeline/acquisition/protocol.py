"""协议客户端接口: 把 Collector 依赖的"客户端"鸭子契约正式化, 作为多协议扩展点.

定位 (重要): 多协议的**主接缝是 phm_v2.telemetry 表 + signal 维表**, 不是这里的代码接口.
每种协议/硬件可以是各自独立的瘦采集器(任意语言, 直接写 telemetry):
  - 西门子 840D: OPC UA (现 Node 采集器, 线B)
  - 华中 HNC / 发那科 FANUC: NC-Link / FOCAS (各写各的瘦采集器)
  - NI / 国产振动传感器: 高频波形就地算特征 (C# native), 写 telemetry
PHM 统一用 PostgresSource 从 telemetry 消费, 与协议无关.

本接口只服务"**用 Python 同一套 Collector 轮询逻辑**采集的协议"(现 NC-Link, 将来可加
Python 版 OPC UA/FOCAS 客户端): 实现下列方法即可复用 collector.Collector 的
分窗/补眠/组装 record/拆角色逻辑, 不重写采集循环.

新增一个 Python 协议 = 写一个实现 ProtocolClient 的类 + 在 CLIENT_FACTORY 注册一行;
非 Python 协议 = 写独立瘦采集器写 telemetry (连这接口都不用碰).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

try:
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover - py<3.8
    Protocol = object  # type: ignore

    def runtime_checkable(c):  # type: ignore
        return c

# 一个被采集的数据项地址. NC-Link=(path,index); OPC UA=(node_id,None); FOCAS=(addr,kind).
Key = Tuple[str, Optional[object]]


@runtime_checkable
class ProtocolClient(Protocol):
    """Collector 依赖的最小客户端契约 (各协议实现).

    get_value 必须返回一个带 .as_map() -> {Key: value} 的结果对象 (见 NclinkResult),
    使 Collector 能按 entry.key() 取回每路读数; 其余方法供控制台连通/探测/写值.
    """

    def get_value(self, keys: Sequence[Key], timeout_ms: Optional[int] = None): ...
    def set_value(self, path: str, index: Optional[object], value) -> dict: ...
    def probe(self, keys: Sequence[Key]) -> dict: ...
    def ping(self) -> Tuple[bool, str]: ...
    def get_model(self) -> Optional[dict]: ...


def make_client(protocol: str, conn: Dict[str, object], mock: bool = False):
    """按协议名建客户端. conn 含 host/port/sn 或 endpoint 等协议各自所需.

    现仅 NC-Link 有 Python 客户端; opcua/focas 抛 NotImplementedError 并指明落地路径
    (优先各写独立瘦采集器写 telemetry; 若要复用 Collector 才在此实现 ProtocolClient).
    """
    p = (protocol or "nclink").lower()
    if p in ("nclink", "nc-link", "hnc"):
        from .nclink_client import NclinkClient, MockNclinkClient
        if mock:
            return MockNclinkClient(sn=str(conn.get("sn", "MOCK-SN")))
        return NclinkClient(str(conn["host"]), int(conn["port"]), str(conn["sn"]))
    if p in ("opcua", "opc-ua", "siemens"):
        raise NotImplementedError(
            "OPC UA(西门子840D): 首选用线B Node 采集器写 telemetry; "
            "若要 Python 复用 Collector, 在此返回一个实现 ProtocolClient 的 OpcuaClient "
            "(get_value(keys) 以 node_id 为 path, index=None).")
    if p in ("focas", "fanuc"):
        raise NotImplementedError(
            "FANUC FOCAS: 写独立瘦采集器写 telemetry; 或实现 ProtocolClient "
            "(get_value 以 FOCAS 数据项地址为 key).")
    raise ValueError(f"未知协议: {protocol}")


# 已实现 Python 客户端的协议 (供前端下拉/校验).
PYTHON_PROTOCOLS = ("nclink",)
