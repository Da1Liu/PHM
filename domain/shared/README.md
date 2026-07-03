# Shared Domain

共享域是云边之间的契约，不代表长期共享写权限。

第一阶段共享内容:
- `phm_v2` schema 仍是现有数据库契约
- `phm_v2.signal` 按字段分权: Cloud 维护 PHM 语义，Edge 维护现场地址
- `phm_v2.telemetry` 是 Edge -> Cloud 同步目标
- `/api/sync` 是未来 store-and-forward 边界

原则:
- Shared 表示数据契约共享，不表示两边都可以随意写。
- 新 API 必须先选择 Edge、Cloud 或 Shared。
- 新表必须先声明未来归属: Edge Local DB、Cloud DB 或同步契约。

正式说明: docs/architecture/cloud-edge-boundary.md。

