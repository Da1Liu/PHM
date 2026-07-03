# 运行与自检命令 (run-commands)

> 各组件的运行/自检/库连接一站式速查。更新: 2026-07-03 (加采集落库桥命令 / WebDashboard machine_id 调试入口)。
> 现场采集 (NI + OPC UA 两进程) 在子系统, 见 `数控.../WebDashboard/RUNBOOK_现场.md`。

## 算法核自检 (在 `PHM_claude/` 下)
```bash
python -m phm_pipeline.regression_anchor   # 共享核 vs step7-9 数值对照 (改算法核后必跑)
python -m phm_pipeline.run_selfcheck       # 端到端 (回放 UCI 液压)
python -m phm_pipeline.smoke_test          # 模块组合冒烟
```
没有 lint/CI; "测试" = 以上三脚本 (+ 控制台 `server/e2e_mock_test` + 看板 `server/dashboard_smoke`)。
```bash
python -m phm_pipeline.server.dashboard_smoke   # 中心看板冒烟 (DB-free: demo契约/503降级/day-mode), 改 dashboard 后跑
```

## 服务 (在 `PHM_claude/` 下)
```bash
python -m phm_pipeline.server.dashboard --port 8099   # 中心只读看板 Cloud Dashboard: /cloud/ (兼容 /v2/)
python -m phm_pipeline.server.dashboard --port 8099 --dev    # 强制 Flask 开发服务器 (调试用)
python -m phm_pipeline.server.dashboard --port 8099 --no-db  # demo 模式 (全 mock, 无需口令)
python -m phm_pipeline.server.app --mock              # NC-Link 采集控制台 (边缘侧, 无硬件演示)
python -m phm_pipeline.server.app --port 9000         # 控制台接真实 NC-Link API Server
```
- 生产前: `pip install -r phm_pipeline/server/requirements.txt` (含 `waitress`/`psycopg2-binary`)。
- 就绪探针: `GET /healthz` → 健康 200 / DB 不可达 503 (供服务管理器/负载均衡)。日志级别 env `PHM_LOG_LEVEL` (默认 INFO)。

## 采集落库桥 public→phm_v2 (在 `PHM_claude/` 下)
现场采集器实时写 `public.vib_features`; 桥增量搬进 `phm_v2.telemetry` 供算法核消费 (评分前先跑)。
```bash
python -m phm_pipeline.acquisition.pg_bridge --machine FIELD_2026_06_18                 # 增量搬振动特征
python -m phm_pipeline.acquisition.pg_bridge --machine FIELD_2026_06_18 --dry-run       # 只统计不写
python -m phm_pipeline.acquisition.pg_bridge --machine FIELD_2026_06_18 --reset-watermark  # 全量重导(慎用)
```
详见 `ACQUISITION_CONTRACT.md §4b`。

## WebDashboard 边缘网关 (在 `数控机床数据采集与状态监测系统/WebDashboard/` 下)
首阶段 WebDashboard/API/C# collector 默认按 `EDGE_MACHINE_ID` 读写 `phm_v2.acq_config`, 旧 `public.app_config` 只作 fallback。建议每个边缘实例显式设置机床 ID:
```powershell
$env:EDGE_MACHINE_ID='FIELD_2026_06_18'
$env:EDGE_BASE_URL='http://localhost:4000'
```

Node API / Web:
```powershell
cd '数控机床数据采集与状态监测系统/WebDashboard/api'
npm start
```
默认 `PORT=4000`; Edge UI 显式入口 `/edge/`、`/edge/config`、`/edge/signals`，兼容旧入口 `/`、`/config.html`、`/signals.html`。`/api/config`、`/api/opcua/catalog`、OPC UA 控制、NI 控制均按当前 `machine_id` 写对应机床的 `phm_v2.acq_config.data.control`。中心看板打开边缘工作台会自动追加 `?machine_id=<机床ID>`；手工调试也可访问 `http://localhost:4000/edge/config?machine_id=CNC_TEST` 或 `http://localhost:4000/edge/signals?machine_id=CNC_TEST`。OPC UA poller 由 1s reconcile 跟随当前活动机床的 `control.opcua_run`。

C# collector:
```powershell
cd '数控机床数据采集与状态监测系统/WebDashboard/collector'
$env:EDGE_MACHINE_ID='FIELD_2026_06_18'
$env:COLLECTOR_PGPASSWORD='口令'
dotnet build Collector.csproj --no-restore
```
构建需要 .NET SDK; 只有 runtime 的机器会报 `No .NET SDKs were found`。运行后 collector 轮询 `control.ni_run/capture_seq`, 并回写 `ni_state`/`ni_message`/`ni_heartbeat`/`ni_rows`/`ni_sps`/`session`/`capture_done`。

语法/冒烟检查:
```powershell
cd '数控机床数据采集与状态监测系统/WebDashboard/api'
node --check src/server.js
node --check src/configStore.js
node --check src/niControl.js
```
## 评分回写 (在 `PHM_claude/` 下)
```bash
python -m phm_pipeline.score_runner --machine FIELD_2026_06_18 --system spindle        # 写库
python -m phm_pipeline.score_runner --machine FIELD_2026_06_18 --system spindle --dry  # 只评分打印
```
详见 `docs/modules/score-runner.md`。典型链路: **桥 (搬振动特征) → score_runner (评分回写) → 看板**。

## 数据库
- 连接参数集中 `phm_pipeline/db_config.py::default_db()`: `PHM_PGHOST/PORT/USER/PGDATABASE` 默认 `localhost:5432/postgres/vibration_db`; **`PHM_PGPASSWORD` 必填, 无明文默认** (缺失即清晰报错)。看板纯演示不连库: `dashboard --no-db`。
- **口令所在 (优先级: 环境变量 > `PHM_claude/.env`)**:
  - 生产 (推荐, 持久, Windows 管理员 PowerShell): `[Environment]::SetEnvironmentVariable('PHM_PGPASSWORD','口令','Machine')` (重开 shell / 重启服务生效; 服务/计划任务用 Machine 级)。
  - 仓库内入口: 复制 `PHM_claude/.env.example` → `PHM_claude/.env`, 写 `PHM_PGPASSWORD=口令`。**`.env` 已 `.gitignore`, 不进版本库**; `default_db()` 启动时兜底读取 (环境变量已设则覆盖)。
  - 临时 (仅当前窗口): `$env:PHM_PGPASSWORD='口令'`。
- 建表 (在 `_integration_probe/` 下, psql 执行): `phm_v2_schema.sql` → `health_result_schema.sql` → `phm_v2_acq_config.sql` → `bridge_state_schema.sql` (后者桥运行时亦自建)。
- 回滚: `DROP SCHEMA phm_v2 CASCADE;` (与 public 旧表隔离)。

## Windows 控制台中文乱码
PowerShell 跑出现 GBK 乱码时, 命令前置 `PYTHONIOENCODING=utf-8` (仅显示问题, 入库为 UTF-8 不受影响)。





