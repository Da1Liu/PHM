# 机床健康基线系统

本项目面向重型机床进给、主轴、液压三系统，回答“这台机床现在还正常吗”。核心是基于健康数据的 one-class 异常检测，不做 RUL，不以故障定位为主线。

## 当前主线

- 算法核：`PHM_claude/phm_pipeline/`，Python + numpy，成熟期算法锁定 PCA + T² + SPE。
- 数据契约：PostgreSQL `vibration_db` / `phm_v2` schema。
- 中心看板：`PHM_claude/phm_pipeline/server/dashboard.py` + 原生 JS v2 master-detail 看板。
- 采集子系统：`数控机床数据采集与状态监测系统/WebDashboard/`，Node OPC UA + C# NI-DAQmx 采集。
- NC-Link 现场采集器：`CNCDataGet/`，用于后续 NC-Link 台份。

更多项目约束先读 `AGENTS.md`、`docs/CURRENT_STATE.md`、`docs/INDEX.md`。

## 运行准备

中心侧 Python 依赖：

```powershell
cd PHM_claude
python -m pip install -r phm_pipeline/server/requirements.txt
Copy-Item .env.example .env
```

在 `PHM_claude/.env` 中填入真实 `PHM_PGPASSWORD`。该文件已被 `.gitignore` 排除。

采集 API 依赖：

```powershell
cd "数控机床数据采集与状态监测系统/WebDashboard/api"
npm install
Copy-Item .env.example .env
```

C# collector 配置：

```powershell
cd "数控机床数据采集与状态监测系统/WebDashboard/collector"
Copy-Item appsettings.example.json appsettings.json
```

在 `appsettings.json` 中填真实数据库口令和现场 NI 通道参数。该文件已被 `.gitignore` 排除。

## 常用命令

在 `PHM_claude/` 下运行：

```powershell
python -m phm_pipeline.regression_anchor
python -m phm_pipeline.run_selfcheck
python -m phm_pipeline.smoke_test
python -m phm_pipeline.server.dashboard --port 8080
```

采集 WebDashboard：

```powershell
cd "数控机床数据采集与状态监测系统/WebDashboard/api"
npm start
```

## 入库范围

本仓库保留运行所需源码、配置模板、文档、契约 SQL 和锁文件；不提交真实数据集、运行输出、数据库文件、日志、`node_modules`、Python 虚拟环境、编译产物、安装包和真实 `.env`/`appsettings.json`。

