# 现场运行手册 —— 网页控制 NI / OPC UA 采集，看到振动波形

目标：USB 接 NI 采集卡 → 在网页上点「开始」采集 → 看到振动特征趋势与波形；OPC UA 独立开关。
前置（本机已就绪）：.NET 8 SDK、Node v20、PostgreSQL（密码 `584412135lwx`、库 `vibration_db`）、NI-DAQmx 26.3 + NI MAX。

## 进程构成（现场跑两个，各开一个窗口）
- **后端** `start-server.cmd` —— 看板 + OPC UA 轮询 + 采集配置/控制 API（http://localhost:4000）。
- **采集守护进程** `start-collector.cmd` —— NI 振动采集器，**常驻待命**，监听网页指令才采集（唯一 native 部分）。

> 双击 `.cmd` 即可运行，或在 cmd 里输入 `start-server.cmd`。`.cmd` 是纯 ASCII 启动器（避免 cmd 的 UTF-8 批处理乱码 bug），
> 实际逻辑在同名 `.ps1`（UTF-8 **带 BOM**，Windows PowerShell 才能正确读中文）。PowerShell 用户也可直接跑 `.ps1`。
> 注意：**不要**在这两个 cmd 里加 `chcp 65001`——中文输出按系统默认代码页(936)走，默认 cmd 窗口即可正确显示。

> 两块采集**互相独立**：OPC UA 在后端进程内开关；NI 由守护进程根据 DB `collector_control.ni_run` 开关。
> 配置/开关都在网页，写 DB（`app_config` 配置、`collector_control` 控制），两进程共享。

---

## 0. 硬件识别（NI MAX）
USB 接卡 → NI MAX → 设备和接口 看到 `cDAQ1Mod4`（本机已确认）→ 右键自检 → 测试面板看到信号 → 记下通道名 `cDAQ1Mod4/ai0…`。

## 1. 起后端
```cmd
cd WebDashboard
start-server.cmd          :: 首次会自动 npm install（也可直接双击）
```

## 2. 起采集守护进程（另开窗口）
```cmd
cd WebDashboard
start-collector.cmd       :: 打印「等待 Web 端开始采集指令」即就绪，先不采集
```

## 3. 网页配置（http://localhost:4000/config.html）
- **振动采集**：采集源 `nidaq`；通道填 NI MAX 真实物理名 + 灵敏度（默认 98.94 mV/g）；采样率/每通道采样数按需。
- **落盘策略**：默认「特征常驻 + 手动/事件原始块」。特征窗留空(=1秒/窗)；要自动留存异常波形则勾「事件触发」并填 RMS 阈值(g)。
- **OPC UA**：勾启用；profile 选 `kepserver` 或 `machine`；填 endpoint/账号密码。保存即热重启。

## 4. 网页开始采集并看波形（http://localhost:4000）
顶部有两块独立控制：
- **NI 振动采集**：点「开始」→ 守护进程开始采集，徽标变「采集中」并显示样本/秒；
  - 「振动特征趋势 (RMS, g)」面板实时出 4 通道 RMS 曲线（常态落盘，极省空间）。
  - 点「📸 抓取波形」→ 约 1~2 秒后「振动波形（原始块）」下拉出现新条目，选它看 4 通道原始波形。
  - 完事点「停止」。
- **OPC UA 状态量采集**：点「开始」→ 主轴/进给各轴/坐标三面板出数据；点「停止」结束。

## 5. 落盘说明（为什么不再担心爆盘）
- 旧版「一采样点一行」约 **208 GB/天**。现版常态只存**每秒每通道一行特征**（vib_features，≈ MB/天级）。
- 原始波形（vib_raw_blocks，float32 块 + PG 自带压缩）**只在手动抓取或事件触发时**存，按需取用。
- 关键诊断信息（RMS/峰值/峭度/波形片段）不丢，磁盘占用降几个数量级。

## 6. 最小验证清单
- [ ] 后端起，配置页保存成功
- [ ] 守护进程打印「等待…指令」（NI 徽标=就绪）
- [ ] 点 NI「开始」→ 徽标「采集中」、样本/秒 > 0、RMS 趋势出线
- [ ] 点「抓取波形」→ 波形面板出 4 通道波形
- [ ] （如需）OPC UA「开始」→ 上方三面板出数据
- [ ] 拔 USB 模拟故障：NI 徽标转「错误」并显示原因（守护进程不僵尸）；点「停止」清错误后可重开

---

## 附：文件级配置（备用）
- 后端连库/端口：`api/.env`（`PGPASSWORD`、`PORT`）。
- 采集器连库：`collector/appsettings.json`（DB 无 app_config 时回退）。运行时采集参数以 DB `app_config` 为准（配置页所写）。
- 故障/复位 SQL：`tools/_field_reset.sql`（清模拟数据、源设回 nidaq、控制行复位）。
