# Edge Domain

边缘域负责现场采集和本地运行控制。第一阶段仍使用现有数据库，不做物理拆库。

当前归属:
- `数控机床数据采集与状态监测系统/WebDashboard/`
- Node OPC UA poller
- C# NI-DAQmx collector
- Edge UI: `/edge/`，兼容旧入口 `/`
- 采集配置、启停、抓波、导出、现场信号地址维护

未来迁移到 Edge Local DB:
- `phm_v2.acq_config` 的采集配置、控制、心跳字段
- `public.vib_features`
- `public.vib_events`
- `public.vib_raw_blocks`
- `public._OPCUA_2`
- `public._OPCUA_3`
- `public._OPCUA_new`
- `phm_v2.bridge_state` 或后续 sync watermark/outbox

正式说明: docs/architecture/cloud-edge-boundary.md。

