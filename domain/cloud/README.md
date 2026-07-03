# Cloud Domain

云端域负责中心看板、机群健康汇总、PHM 诊断展示、资产目录和同步接收。
第一阶段仍使用现有数据库，不做物理拆库。

当前归属:
- `PHM_claude/phm_pipeline/server/dashboard.py`
- Cloud Dashboard: `/cloud/`，兼容旧入口 `/v2/`
- 机群概览、趋势、诊断、维护、同步入口 `/api/sync`

未来迁移到 Cloud DB:
- `phm_v2.machine` 资产目录权威
- `phm_v2.signal` 的 PHM 语义字段
- `phm_v2.telemetry` 云端汇总副本
- `phm_v2.health_result`
- 未来的 site/gateway/sync status 表

正式说明: docs/architecture/cloud-edge-boundary.md。

