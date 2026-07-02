# ADR-005 多协议接缝 = telemetry + signal 维表 (非代码接口)

状态: 已采纳

## Decision
**傻采集器 (各协议/各语言各写各的) 只负责把读数写进 `phm_v2.telemetry`; PHM(Python) 统一从 telemetry 消费做工况分层 / 稳态门控 / 评分。** 多协议的接缝是**数据表**, 不是代码接口。
加一种协议/硬件 = 写一个瘦采集器 (任意语言) 写 telemetry + 在 `signal` 维表登记几行, **不碰已有代码**。

## Reason
- 首台西门子840D 走 OPC UA; 高频振动走 NI-DAQmx C# native; 后续台份可能华中/发那科走 NC-Link/FOCAS。**数据种类/数目/采集地址都不一定相同** → 系统不得假设统一固定通道集。
- 各采集路能力不同 (NC-Link 只有寄存器轮询、无高频波形)。

## Consequence
- `phm_pipeline/acquisition/` 是 **NC-Link 这一种协议的瘦采集器**, 不是通用采集层。
- 每台机床用自己的 `signal` 维表定义信号; `is_high_freq` 区分波形(走NI/C#直写)与标量遥测。
- 工况 `regime` 标注 / 稳态门控 / 评分 / 基线准入**集中在 Python 层** (regime 是跨源逻辑: 工况来自标量通道, 要按时间戳给振动打标)。
- `acquisition/protocol.py` 仅为"复用同一套 Python `Collector`"的协议提供 `ProtocolClient` 接口; 独立瘦采集器不必走它。

参见 `ACQUISITION_CONTRACT.md` (采集层全貌) / [[ADR-007]] (边缘/中心)。
