# Collector —— 无界面 NI 振动采集器 (Step 5)

数控机床采集落库模块中**唯一必须留在硬件主机的 native 部分**：NI-DAQmx 高频振动采集 → PostgreSQL。
替代桌面端 `Form2` 的采集回路，去掉全部 WinForms。OPC UA、看板、读 API 等已在 Web 侧（见 `../api`、`../web`）。

## 设计
- **采集源抽象** `IVibrationSource`：
  - `SimulatedVibrationSource`（默认编入）：合成波形，无硬件即可验证落库/吞吐。
  - `NiDaqVibrationSource`（`#if NIDAQ` 守卫）：移植自 `Form2.start_sampling/OnDataReady` 的真实 NI 采集。
- **落库** `VibrationStore`：PostgreSQL **二进制 COPY 批量写**，吞吐远高于桌面端逐行 INSERT（"不损失性能"的关键）。表名沿用约定 `"_<base>_main"`。
- **采集/落库解耦**：采集线程只入队（`BlockingCollection`），专用 writer 线程做 COPY；DB 延迟不阻塞采集。每 2s 打印吞吐（样本/秒）。

## 目标框架与 NI 绑定（已定稿）
- **net472**：NI 无 .NET Core 版 DAQmx 程序集，故与桌面端一致用 net472，直接引用随驱动安装的
  `NationalInstruments.DAQmx`(64 位) 与 `NationalInstruments.Common`（`.csproj` 内 HintPath）。
- 用 **.NET 8 SDK** 编译（`Microsoft.NETFramework.ReferenceAssemblies` 提供引用程序集，无需 VS）。
- **NIDAQ 常量已默认定义**，真实 NI 源 `NiDaqVibrationSource` 始终编入。
- Npgsql 7.0.7（net472 兼容、含二进制 COPY）；配置用 Newtonsoft.Json。

## 构建 / 运行
```powershell
cd WebDashboard/collector
dotnet build -c Release                 # 已验证 0 错误
.\bin\Release\net472\Collector.exe      # 读 appsettings.json
```
`appsettings.json`：`Source`(simulated|nidaq)、采样率/通道/灵敏度、库连接、表名前缀。
前提：PostgreSQL 可连（密码重置脚本见 `../tools/reset-pg-password.ps1`）。

## 验证状态
- ✅ 编译：net472 + 真实 NI 源，0 错误。
- ✅ 运行落库：`Source=simulated` 跑通，COPY ~25600 样本/秒、0 丢批（与配置采样率一致）。
- ⏳ 真实 NI 采集：现场插卡（NI MAX 自检），`Source=nidaq` + 真实通道名即可。见 `../RUNBOOK_现场.md`。
